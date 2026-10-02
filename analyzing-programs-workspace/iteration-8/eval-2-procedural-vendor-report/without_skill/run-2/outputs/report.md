# ZMMR_VEND_LIST 报表程序走读报告

## 一、结论速览

| 维度 | 评价 |
|---|---|
| 程序类型 | 经典可执行报表（`REPORT` + `FORM` 过程化），非 OO |
| 业务内容 | 按供应商汇总采购订单数量，ALV 列表展示 |
| 主流程清晰度 | 好：`START-OF-SELECTION` 三步分离，取数 / 建字段目录 / 显示 |
| 最大隐患 | ① 空结果集直接 `MESSAGE ... STOP` 会 short dump；② 字段目录失败后仍继续执行 ALV；③ 全量单表读无分页/无 WHERE 之外的保护 |
| 现代化程度 | SQL 已用 Open SQL（新语法），但 UI 层仍是经典 FM + `TABLES` + 全局 `DATA` |

---

## 二、业务问题

业务方要回答的问题是：**"给我一份供应商清单，每个供应商名下有多少张采购订单。"**

- **输入**：两个选择屏幕范围 —— 供应商号 `s_lifnr`、采购组织 `s_ekorg`。
- **处理**：把供应商主数据表 `LFA1` 与采购订单头表 `EKKO` 按 `LIFNR` 内连接，按 `LIFNR + NAME1` 分组，统计去重后的订单号（`EBELN`）个数。
- **输出**：三列 ALV 网格 —— 供应商号、供应商名称、采购订单数，带斑马纹与多选信息。

```abap
COUNT( DISTINCT b~ebeln ) AS po_cnt
```

这个 `DISTINCT` 是统计口径的关键点：连接后同一张订单只会产生一行，理论上 `COUNT(*)` 也能得到同样结果；用 `DISTINCT` 表明作者对"一单可能因连接条件宽泛而多行"的防御性认知，属于**安全但冗余**的写法。

---

## 三、架构

程序采用教科书式的**三层直线架构**，无回调、无对话框、无状态管理：

```
选择屏幕 (s_lifnr / s_ekorg)
        │
        ▼
START-OF-SELECTION  ← 唯一流程控制点
        │
        ├─► FORM get_data        数据层：Open SQL → gt_out
        ├─► FORM build_fieldcat  元数据层：FM 生成 ALV fieldcat
        └─► FORM display_alv     视图层：FM 渲染 gt_out
```

### 全局数据结构

```abap
TABLES: lfa1, ekko.        " 仅为 SELECT-OPTIONS 提供字段参照

DATA: gt_out  TYPE TABLE OF zmmr_vend_s,   " 输出内表（Z 结构）
      gt_fcat TYPE slis_t_fieldcat_alv,    " ALV 字段目录
      gs_layo TYPE slis_layout_alv.        " ALV 布局控制
```

三者的生命周期是整个程序全程：`gt_out` 被 `get_data` 写、被 `display_alv` 读；`gt_fcat` 被 `build_fieldcat` 写、被 `display_alv` 读；`gs_layo` 只在 `display_alv` 内被设置一次。

`zmmr_vend_s` 是一个自定义 DDIC 结构（报表用的最小字段集），仅包含 `lifnr / name1 / po_cnt` 三个字段。它在这里承担双重角色：**数据容器**和 **fieldcat 生成的元数据来源**。

### 隐式契约

程序依赖三个未在代码中显式表达的约定：

1. `Z` 命名对象 `Zmmr_vend_s` 的字段顺序 = ALV 显示列顺序；
2. `zmmr_vend_s-po_cnt` 类型必须能承载 `COUNT(DISTINCT ...)` 的返回类型；
3. `REUSE_ALV_FIELDCATALOG_MERGE` 只做**技术**映射，不带**文本** —— 中文列标题必须靠 DDIC 字段标签，否则 ALV 显示的是 `LIFNR`/`NAME1`/`PO_CNT` 这样的字段名。这是最容易被忽略的隐性依赖。

---

## 四、执行流程详解

### Step 0：选择屏幕（隐式，代码中无显式 `SELECTION-SCREEN`）

`SELECT-OPTIONS` 在程序启动时由运行时自动生成输入界面。两个范围字段都是**非必填**，即用户可以全选直接执行 —— 这是后面所有性能与空结果问题的根源。

```abap
SELECT-OPTIONS: s_lifnr FOR lfa1-lifnr,
                s_ekorg FOR ekko-ekorg.
```

### Step 1：`FORM get_data`

**取数 SQL**：

```abap
SELECT a~lifnr,
       a~name1,
       COUNT( DISTINCT b~ebeln ) AS po_cnt
  FROM lfa1 AS a
  INNER JOIN ekko AS b ON a~lifnr = b~lifnr
  WHERE a~lifnr IN @s_lifnr
    AND b~ekorg IN @s_ekorg
    AND b~bstyp = 'F'
  GROUP BY a~lifnr, a~name1
  INTO TABLE @DATA(lt_vend).
```

逐条解读这个 SQL 的业务含义：

| 片段 | 作用 | 备注 |
|---|---|---|
| `INNER JOIN` | 只要在 `EKKO` 里有订单的供应商才出现 | **无订单的供应商被排除**，是"内连接"语义，隐含需求 |
| `a~lifnr IN @s_lifnr` | 供应商范围过滤 | 在内连接左表上，但 SQL 优化器会下推到连接条件 |
| `b~ekorg IN @s_ekorg` | 采购组织范围过滤 | 在右表，**连接后过滤**，语义正确 |
| `b~bstyp = 'F'` | 只统计采购订单 | `BSTYP` 是订单类别：`F`=采购、`L`=计划订单、`K`=库存调拨、`A`=框架协议等。这是**最关键的过滤条件**，说明报表只关心真实采购订单 |
| `GROUP BY lifnr, name1` | 按供应商聚合 | 用 `name1` 参与分组，虽冗余（同一 LIFNR 只有一个 NAME1），但语义清晰 |
| `COUNT(DISTINCT ebeln)` | 去重订单数 | 一个订单头有多行项目，但连接条件不含 `EBELPO`，所以头表本来就一行 |

**紧随其后的内联转换**：

```abap
gt_out = VALUE #( FOR ls IN lt_vend
                  ( lifnr = ls-lifnr name1 = ls-name1 po_cnt = ls-po_cnt ) ).
```

这是把 `lt_vend` 的匿名内表结构映射到 `Zmmr_vend_s` 类型的 `gt_out`。技术上正确（Open SQL 的结果内表通常与目标结构同构），但在字段完全一致时是**纯样板代码** —— 直接 `gt_out = lt_vend` 或 `MOVE-CORRESPONDING` 都可。

**分支处理**：

```abap
IF sy-subrc = 0.
  ...
ELSE.
  MESSAGE '无符合条件的供应商' TYPE 'I'.
  STOP.
ENDIF.
```

**这里是全程序最严重的问题。** `SELECT ... INTO TABLE` 之后：

- `sy-subrc = 0` 表示 SQL **执行成功**，**不保证有任何数据行**；
- 查询无命中时 `sy-subrc` 仍为 `0`，`lt_vend` 是空内表；
- 真正的错误（表不存在、字段不存在）在 Open SQL 3.0 中通常是**运行时异常/dump**，而不是让 `sy-subrc` 非零。

也就是说：**无数据时 `gt_out` 为空 → `build_fieldcat` 正常执行 → `display_alv` 用空内表调用 `REUSE_ALV_GRID_DISPLAY`**。这个 FM 传空 `T_OUTTAB` 在实际系统里可能弹出空网格、可能 short dump，行为不确定。

更糟的是 `MESSAGE ... TYPE 'I'` + `STOP` 的组合：`TYPE 'I'` 是信息提示，用户点确认后 `STOP` 直接终止整个事务 —— 在 `STOP` 后执行，实际效果等价于 `MESSAGE ... TYPE 'E'`（可继续的终止消息）或 `LEAVE TRANSACTION`。这里用 `I` + `STOP` 是混搭，写法不严谨。

### Step 2：`FORM build_fieldcat`

```abap
CALL FUNCTION 'REUSE_ALV_FIELDCATALOG_MERGE'
  EXPORTING
    i_structure_name = 'ZMMR_VEND_S'
  CHANGING
    ct_fieldcat     = gt_fcat.
IF sy-subrc <> 0.
  MESSAGE '字段目录生成失败' TYPE 'E'.
ENDIF.
```

**意图**：把 DDIC 结构 `ZMMR_VEND_S` 的技术信息（字段名、长度、数据元素、域值 help）自动映射成 ALV 字段目录，省去手工写 3 段 `APPEND VALUE #( ... )`。这是标准做法，避免了硬编码列定义。

**意图很好，实现有洞**：

1. **`REUSE_ALV_FIELDCATALOG_MERGE` 本身不设 `sy-subrc`**。它是 "REUSE_ALV_" 系列里少数不返回子返回码的 FM；失败通常通过异常（结构不存在 → `CX_SY_STRUCT_NOT_FOUND` 之类）或空 `ct_fieldcat` 体现。因此 `IF sy-subrc <> 0` 基本是**死代码**，`sy-subrc` 里残留的是上一次 SQL 的值。
2. **没有检查 `gt_fcat` 是否为空**。若结构不存在导致 FM 异常终止，这行检查救不了；若 FM 静默返回空 fieldcat，`MESSAGE TYPE 'E'` 也不会触发，程序会带着空 `it_fieldcat` 继续调 ALV。
3. **`TYPE 'E'` 不带 `MESSAGE ... ` 的终止行为**：E 消息会结束程序并回滚，这一点是**对的**，比 Step 1 好。但因为上一条的死代码判断，实际保护力度为零。

### Step 3：`FORM display_alv`

```abap
gs_layo-zebra = 'X'.
gs_layo-get_sel_info = 'X'.
CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
  EXPORTING
    is_layout   = gs_layo
    it_fieldcat = gt_fcat
  TABLES
    t_outtab    = gt_out.
```

- `zebra = 'X'`：斑马纹隔行底色，提升大量行数据的可读性。
- `get_sel_info = 'X'`：允许 ALV 记录用户选中的行（`RS_SEL_DATA` 附加行）。**但代码里没有任何地方读这个附加行** —— 说明这是从别的报表复制模板时留下的配置，或是预留的后续功能点（如"选中后跳转 PO 明细"）。
- **未设置** `i_callback_pf_status_set` / `i_callback_user_function` → ALV 无自定义工具栏/按钮，无法刷新、无法跳转、无法导出特定格式。
- **未设置** `i_save = 'A'` → ALV 默认**无导出 Excel/保存变式**功能。对一个典型的 PO 分析报表，缺 Excel 导出会被业务直接投诉。
- **未设置** `it_sort` → 结果按数据库返回顺序，通常是 `LIFNR` 升序，但不保证。
- `gs_layo` 是全局的，但只在 `display_alv` 内写 —— 与把 `gt_out`/`gt_fcat` 也做成全局相比，这里的"全局化"是不一致的：三个共享数据里两个需要跨 FORM 传递（因此全局），一个不需要（却也是全局）。属于**局部不一致的编码风格**。

### 完整执行时序

```
1. 运行时生成选择屏幕 → 用户填入 s_lifnr / s_ekorg → 按 F8
2. START-OF-SELECTION
3.   PERFORM get_data
4.     └─ Open SQL: LFA1 ⋈ EKKO, 过滤 bstyp='F', GROUP BY, COUNT(DISTINCT)
5.     └─ VALUE #( ) 映射到 gt_out
6.   PERFORM build_fieldcat
7.     └─ REUSE_ALV_FIELDCATALOG_MERGE(ZMMR_VEND_S) → gt_fcat
8.   PERFORM display_alv
9.     └─ 设置 zebra / get_sel_info
10.    └─ REUSE_ALV_GRID_DISPLAY(gt_out, gt_fcat) → 屏幕输出
11.    └─ ALV 交互（排序/筛选/选择），用户退出会话或触发消息
```

程序是**一次性执行、无循环、无回调、无状态持久化**的 —— 执行完 10 就结束，没有任何后续逻辑。这是它结构简单的根本原因。

---

## 五、按子程序分组讲解

### A 组：数据获取层 —— `get_data`

**职责**：把物理表数据转换为报表可展示的行集。

**做对的**：
- 用 Open SQL 新语法（`@` 转义、`AS` 表别名、内联 `DATA()`），符合 7.50+ 规范
- 聚合下沉到数据库，避免 `SELECT *` 到内存再用 `SORT`+`READ TABLE` 汇总的低效写法
- 用 `INNER JOIN` 而非取全量 `LFA1` 再筛，逻辑直达
- `bstyp = 'F'` 的业务过滤明确

**做得不够的**：
- 用 `sy-subrc` 判断有无结果（语义错误，见 Step 1）
- `VALUE #( FOR ... )` 的逐字段搬运在结构同构时是冗余的
- 没有对空选择屏幕做保护（见性能问题）
- `PO_CNT` 的 ALV 显示格式（是否带千分位、前导零）未设置

### B 组：元数据层 —— `build_fieldcat`

**职责**：由 DDIC 结构自动推导 ALV 列定义。

**做对的**：用 FM 自动生成而非手写，是 REUSE_ALV 系列的标准推荐做法 —— 结构改字段，ALV 自动跟着变，零维护成本。

**做得不够的**：`sy-subrc` 检查是无效代码（见 Step 2）。正确做法是在 FM 后检查结果：

```abap
IF gt_fcat IS INITIAL.
  MESSAGE '字段目录生成失败，DDIC 结构 ZMMR_VEND_S 可能不存在' TYPE 'E'.
ENDIF.
```

### C 组：视图层 —— `display_alv`

**职责**：把数据 + 字段目录 + 布局渲染成交互式网格。

**做对的**：`zebra` 和 `get_sel_info` 两项布局配置选得合理，是对"可读性"和"用户交互意图"的正向表达。

**做得不够的**：ALV 功能面太窄（见 Step 3 清单）—— 无回调、无导出、无排序、无状态栏汇总（行数/总单量合计行是这类报表的标准诉求）。

### D 组：全局声明区（隐式第四组）

```abap
TABLES: lfa1, ekko.
```

`TABLES` 语句在现代 ABAP 中已被 `DATA` 取代，官方标注为**过时（obsolete）**。此处仅为给 `SELECT-OPTIONS` 提供字段参照，是唯一合理的使用场景，但更地道的写法是直接引用表：

```abap
SELECT-OPTIONS: s_lifnr FOR lfa1-lifnr,
                s_ekorg FOR ekko-ekorg.
```

配合 `TABLES` 的完全移除（改用 `SELECT-OPTIONS ... FOR lfa1-lifnr` 仍需结构引用，或定义 `TYPES`/直接写 `lfa1-lifnr`）。

---

## 六、问题清单

按严重程度排序。

### 🔴 严重

| # | 位置 | 问题 | 后果 |
|---|---|---|---|
| 1 | `get_data:29` | 用 `sy-subrc` 判断"无数据" | `sy-subrc=0` 只代表 SQL 成功；空结果集直接流入 ALV，`REUSE_ALV_GRID_DISPLAY` 传空 `T_OUTTAB` 可能 dump 或显示空网格，用户无友好提示 |
| 2 | `build_fieldcat:44` | 检查 `sy-subrc`，但该 FM 不返回 `sy-subrc` | 判断是死代码（沿用上一步 SQL 的残留值），真正的失败（结构不存在→异常、空 fieldcat）无法被捕获 |
| 3 | `display_alv:52` | ALV 传空内表无保护 | 见 #1，形成 short dump 风险链 |
| 4 | 全局 | 选择屏幕非必填，用户可空条件全量执行 | `LFA1 ⋈ EKKO` 是经典笛卡尔放大 join，`EKKO` 在生产系统动辄百万级 `EBELN`，`COUNT(DISTINCT)` 需要排序去重 —— **空选择范围执行 = 数据库全表扫描 + 大排序，运行时可能到分钟级甚至超时**。这是最容易被低估的生产风险 |

### 🟠 中等

| # | 位置 | 问题 | 说明 |
|---|---|---|---|
| 5 | `display_alv:51` | `get_sel_info = 'X'` 但无回调、无消费选中行的逻辑 | 死配置。要么删掉，要么补 `i_callback_user_function` 实现"选中→跳转 PO 明细" |
| 6 | `display_alv:52` | 未设 `i_save = 'A'` | 无 Excel/本地文件导出，业务高频缺失功能 |
| 7 | `display_alv:52` | 未设 `it_sort` | 结果顺序依赖 DB，非确定行为 |
| 8 | `display_alv:52` | 未设 `es_sorttab`/`i_callback_pf_status_set` | 无工具栏、无 ALV 标准按钮（保存变式/布局变式/选择显示列），不可用性受限 |
| 9 | `get_data:33` | `MESSAGE '无..' TYPE 'I'. STOP.` 组合不当 | `I` 消息 + `STOP` 语义混乱。应为 `MESSAGE ... TYPE 'E'`（可继续）或 `MESSAGE ... TYPE 'S' LEAVE TRANSACTION` |
| 10 | `get_data:30-31` | `VALUE #( FOR ... )` 冗余逐字段搬运 | 结构同构时 `gt_out = lt_vend` 即可 |
| 11 | 全局 | `COUNT(DISTINCT)` 冗余 | 连接条件只到 `EKKO` 头表（一订单头一行），`COUNT(*)` 结果相同。`DISTINCT` 增加 DB 排序开销 |
| 12 | 全局 | `TABLES:` 语句过时 | 官方 obsolete，建议移除 |

### 🟡 轻微 / 健壮性

| # | 位置 | 问题 |
|---|---|---|
| 13 | `get_data` | 无 `IF NOT s_lifnr[] IS INITIAL AND NOT s_ekorg[] IS INITIAL` 的组合校验或预警提示 |
| 14 | `display_alv` | 无空结果/单结果的提示行（ALV 标题栏 `slis_msgid`/`slis_msgno`） |
| 15 | 全局 | `gs_layo` 无需全局化，`zebra`/`get_sel_info` 可作局部变量 |
| 16 | `build_fieldcat` | 未指定 `i_no_topology`，也没设 ALV 的默认排序/合计（`program g_tota`） |
| 17 | 全局 | 缺少 ALV 合计行（总供应商数、总订单数）—— 此类报表的标准诉求 |
| 18 | 全局 | 无单元测试 / 无 SE38 语法检查保护；`zmmr_vend_s` 存在与否无法从源码静态确认 |

---

## 七、改进建议

### 7.1 立即修复（不改结构，风险最低）

```abap
FORM get_data.
  SELECT a~lifnr,
         a~name1,
         COUNT( * ) AS po_cnt
    FROM lfa1 AS a
    INNER JOIN ekko AS b ON a~lifnr = b~lifnr
    WHERE a~lifnr IN @s_lifnr
      AND b~ekorg IN @s_ekorg
      AND b~bstyp = 'F'
    GROUP BY a~lifnr, a~name1
    INTO TABLE @gt_out.

  IF gt_out IS INITIAL.
    MESSAGE '无符合条件的供应商' TYPE 'S'.
    RETURN.
  ENDIF.
ENDFORM.
```

要点：
- 直接 `INTO TABLE @gt_out`，删掉中间内表与 `VALUE #( )`
- `COUNT( * )` 替代 `COUNT(DISTINCT)`（依据：连接只到头表）
- **判断 `IS INITIAL` 而非 `sy-subrc`** —— 这是正确的空结果检测方式
- `TYPE 'S'` + `RETURN` 回到 `START-OF-SELECTION` 末尾，ALV 不再被调用（比 `STOP` 干净，且不留下 dump 记录）

`build_fieldcat` 同样改为判空：

```abap
FORM build_fieldcat.
  CALL FUNCTION 'REUSE_ALV_FIELDCATALOG_MERGE'
    EXPORTING i_structure_name = 'ZMMR_VEND_S'
    CHANGING  ct_fieldcat     = gt_fcat.

  IF gt_fcat IS INITIAL.
    MESSAGE '字段目录生成失败，请检查 DDIC 结构 ZMMR_VEND_S' TYPE 'E'.
  ENDIF.
ENDFORM.
```

### 7.2 ALV 功能补全

```abap
FORM display_alv.
  gs_layo-zebra       = 'X'.
  gs_layo-get_sel_info = 'X'.

  TRY.
      CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
        EXPORTING
          is_layout      = gs_layo
          it_fieldcat    = gt_fcat
          it_sort        = VALUE #( ( fieldname = 'PO_CNT' descending = 'X' ) )
          is_variant     = gt_variant
          i_save         = 'A'
          i_default_layout = 'SAPLISMG'
          slis_msgid     = 'ZMMR'
          slis_msgno     = '000'
        TABLES
          t_outtab       = gt_out.
    CATCH cx_root INTO DATA(lx_root).
      MESSAGE lx_root->get_text( ) TYPE 'E'.
  ENDTRY.
ENDFORM.
```

要点：
- `it_sort` 按订单数降序 —— 这才是采购人员最想看的排序
- `i_save = 'A'` 打开 Excel 导出与布局变式保存
- `is_variant` + `slis_msgid/no` 提供状态栏标题
- **`TRY/CATCH` 包裹 ALV FM 是 ALV 编程的必备防御** —— FM 内部对空内表、`gt_out` 类型不匹配等的异常处理不可控，damp 一下比 dump 好

### 7.3 性能加固

在 `START-OF-SELECTION` 入口做空范围检测：

```abap
IF s_lifnr[] IS INITIAL AND s_ekorg[] IS INITIAL.
  " 至少确认是否真的要全量
  " 方案一：直接拒绝
  " MESSAGE '请至少输入供应商或采购组织范围' TYPE 'E'.
  " 方案二：允许但告警（数据量大时）
  " MESSAGE '未指定筛选条件，将全量扫描 EKKO，可能耗时较长' TYPE 'W'.
ENDIF.
```

更彻底的性能手段（按侵入性从低到高）：

1. **必填校验**（最低成本，直接掐掉最坏路径）
2. **SET PARAMETER ID / 带参数进入**：若这个报表总是从 PO 明细带着 `LIFNR` 跳进来，把 `s_lifnr` 设为默认带入
3. **上移到 CDS View**：把 `GROUP BY + COUNT` 做成 CDS 并加 DDL Source 聚合，后续报表可复用
4. **加数据库索引**：`EKKO-EKORG` + `EKKO-BSTYP` 组合索引（`LIFNR` 应该是 `EKKO` 的主键前导列，若非如此需核查）

### 7.4 现代化重构（可选，非必须）

若计划长期维护，建议逐步迁移：

| 当前 | 目标 |
|---|---|
| `REPORT ... FORM` | `CLASS lcl_report DEFINITION` + `LOCAL FRIENDS` / `START-OF-SELECTION` 中调用 |
| 全局 `gt_out`/`gt_fcat` | 类属性（`ty_output_tab` 类型），作用域明确 |
| `TYPE-POOLS: slis` | 7.40+ 改为 `cl_gui_alv_grid`，或直接上 `SALV` |
| `TABLES: lfa1, ekko` | 直接字段引用或 `DATA` |
| `MESSAGE '中文'` | `MESSAGE-ID` + `T100` 消息类，支持 `&1` 占位符与多语言 |

不过要客观说明：**当前程序规模（58 行、3 个 FORM）下，OO 重构的收益有限**。真正值得优先做的只有 7.1（正确性）和 7.2（可用性）。OO 化属于"维护人数增长或需要复用"时的自然演进，不应作为首要动作。

---

## 八、总结

`Zmmr_vend_list` 是一个**结构教科书化、执行流线性清晰、但防御性编程严重缺失**的小报表。

**它的优点**是流程分明的三段式拆分、Open SQL 聚合下沉、以及 `REUSE_ALV_FIELDCATALOG_MERGE` 的正确选型 —— 说明作者具备扎实的 ALV 基础和良好的结构直觉。

**它的缺陷**集中在三处，都是同一类思维盲区：**假设"底层一定成功"**。`sy-subrc` 用来判空（错）、`sy-subrc` 用来判 fieldcat 生成（更错）、空内表直接进 ALV（未防）。再加上选择屏幕非必填导致可触发全量 `EKKO` 扫描，整条链路在"数据量大"或"无数据"两个真实生产场景下都会暴雷。

**修复优先级**：
1. `IF gt_out IS INITIAL` 判空 + `RETURN`（5 分钟，堵 dump）
2. `IF gt_fcat IS INITIAL` 判空（3 分钟，堵静默失败）
3. `i_save = 'A'` + `it_sort`（2 分钟，堵可用性投诉）
4. 选择屏幕空范围校验（10 分钟，堵超时）
5. `TRY/CATCH` 包裹 ALV（5 分钟，堵残余风险）

前四项加起来不到半小时，能把这个报表从"能跑但会炸"提升到"能上线"。第五项和 OO 重构可以留到后续迭代。
