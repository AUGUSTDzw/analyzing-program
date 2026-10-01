# ZMMR_VEND_LIST 报表程序分析报告

> 分析对象：`zmmr_vend_list.abap`（58 行，经典过程式报表，非 OO）
> 分析维度：业务问题 / 架构 / 执行流程 / 分组走读 / 问题清单 / 改进建议

---

## 一、一句话结论

这是一个结构标准但**存在一处逻辑失效**的供应商采购订单数量统计报表：主流程（取数 → 生成字段目录 → ALV 展示）清晰、代码量克制，但"无数据"分支永远不会被触发（`sy-subrc` 判断对象用错），且**缺少行数检查之外的全部健壮性与可用性设施**（授权、排序、合计、下钻、空结果体验）。

---

## 二、业务问题与报表定位

| 维度 | 说明 |
|---|---|
| 报表主题 | 按**供应商（LFA1）**汇总其持有的**采购订单（EKKO）**数量 |
| 关键过滤 | `BSTYP = 'F'` → 仅采购订单（排除框架协议、采购计划行等单据类别） |
| 输入 | `s_lifnr`（供应商号范围）、`s_ekorg`（采购组织范围），均为可选 |
| 输出 | 供应商号、供应商名称、采购订单数；斑马纹 ALV 表格 |
| 典型场景 | 采购员盘点"每个供应商名下有多少张 PO"，用于供应商活跃度分析、与供应商对账前的粗筛 |
| 粒度 | 一个供应商一行（`GROUP BY lifnr, name1`） |

从业务角度看，这个报表目前只能回答"**有多少张**"，无法回答"**买了多少钱 / 最近什么时候买的 / 单张平均金额**"。这决定了它的实用价值偏弱，属于典型的"能用但没人愿意用"的报表。

---

## 三、架构与代码结构

程序采用 **ABAP 经典过程式 + ALV Grid** 的"教科书结构"，共 5 个结构层次：

```
① 全局声明区 (行 1-11)
   ├─ TYPE-POOLS slis              ALV 类型池
   ├─ TABLES lfa1, ekko            隐式工作区（过时写法）
   ├─ DATA gt_out / gt_fcat / gs_layo   全局内表 + 布局
   └─ SELECT-OPTIONS s_lifnr / s_ekorg   选择屏幕

② 事件块 START-OF-SELECTION (行 13-16)   ← 唯一流程驱动点
   PERFORM get_data → build_fieldcat → display_alv

③ FORM get_data        (行 18-36)  数据获取（Open SQL + 聚合）
④ FORM build_fieldcat  (行 38-47)  字段目录（DDIC 反射）
⑤ FORM display_alv     (行 49-58)  展示（REUSE_ALV_GRID_DISPLAY）
```

**架构特征解读：**

- **单入口单向流程**：`START-OF-SELECTION` 是唯一流程控制点，三个 `PERFORM` 严格顺序依赖，`get_data` 失败不会中止后续（除 `STOP` 外），属于"流程可控但缺乏守卫"的写法。
- **数据契约靠 DDIC 结构 `ZMMR_VEND_S`**：ABAP 程序不自持字段目录，全部列定义、文本、长度都靠 DDIC 结构反射（`REUSE_ALV_FIELDCATALOG_MERGE`）。这是 ALV 程序的标准做法，也是本程序最值得肯定的一点。
- **强耦合于全局数据**：`gt_out / gt_fcat / gs_layo` 三个全局变量在 FORM 之间靠内存传递，没有参数化；单线程下没问题，一旦引入后台、RFC 调用或嵌套调用即成隐患。
- **新语法与旧语法混用**：用了 `@` 主机变量和 `@DATA()` 内联声明（行 24-28），却仍用 `TABLES:`（行 4）与 `FORM/PERFORM`（行 18 起）。属于**半新半旧的过渡状态**。

---

## 四、执行流程（Execution Flow）

用户双击 `ZMM_LIST` 或执行 `SE38` 运行后，完整时序如下：

```
1. 启动报表 → ABAP 运行时识别 SELECT-OPTIONS → 动态生成选择屏幕（行 10-11）
2. 用户输入 s_lifnr / s_ekorg → 执行（F8）
3. 进入 START-OF-SELECTION
   │
   ├─ 3.1 PERFORM get_data       行 14
   │      ├─ SQL：lfa1 INNER JOIN ekko ON lifnr
   │      ├─ 过滤：a~lifnr IN @s_lifnr  AND  b~ekorg IN @s_ekorg  AND  b~bstyp = 'F'
   │      ├─ 聚合：GROUP BY a~lifnr, a~name1，COUNT( DISTINCT b~ebeln ) AS po_cnt
   │      ├─ 取数：INTO TABLE @DATA(lt_vend)  ← 局部内表
   │      ├─ 判定：IF sy-subrc = 0 → VALUE # 逐行拷贝到全局 gt_out（行 30-31）
   │      │         ELSE → MESSAGE '无符合条件的供应商' + STOP（行 33-34）
   │      └─ 返回
   │
   ├─ 3.2 PERFORM build_fieldcat 行 15
   │      ├─ CALL FUNCTION 'REUSE_ALV_FIELDCATALOG_MERGE'
   │      │     i_structure_name = 'ZMMR_VEND_S'
   │      ├─ 系统读取 DDIC → 生成文本 + 字段目录 → CHANGING ct_fieldcat = gt_fcat
   │      └─ 失败则 MESSAGE ... TYPE 'E'（行 44-46）
   │
   └─ 3.3 PERFORM display_alv    行 16
          ├─ 设置布局：gs_layo-zebra = 'X'（斑马纹）、get_sel_info = 'X'
          ├─ CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
          ├─ 全屏 Grid ALV 展示 gt_out；用户可排序/筛选/导出/选行
          └─ 无用户操作回调（无 hot spot、无双击下钻）

4. 返回用户 / 程序结束
```

**执行流程关键结论：**

- 流程是**完全线性、单向、无循环**的，三步职责边界清楚，符合 ALV 报表的标准骨架。
- **第 3.1 步是唯一的风险集中点**：SQL 写法基本正确，但结果判定逻辑写反（详见问题清单 P0-1）。
- **性能特征**：单条 SQL 全量聚合 LFA1×EKKO。EKKO 在生产系统通常有数百万行，当 `s_ekorg` / `s_lifnr` 留空且统计范围放大时，此语句可能耗时数十秒并占用大量工作内存（ABAP 内存溢出即 dump）。

---

## 五、按子程序分组走读

### 5.1 全局声明区（行 1-11）

```abap
REPORT zmmr_vend_list.
TYPE-POOLS: slis.

TABLES: lfa1, ekko.

DATA: gt_out  TYPE TABLE OF zmmr_vend_s,
      gt_fcat TYPE slis_t_fieldcat_alv,
      gs_layo TYPE slis_layout_alv.

SELECT-OPTIONS: s_lifnr FOR lfa1-lifnr,
                s_ekorg FOR ekko-ekorg.
```

**逐行解读**

| 行 | 语句 | 作用与评价 |
|---|---|---|
| 1 | `REPORT zmmr_vend_list.` | 报表名。注意：程序名含 `MMR`（MRP 缩写），但实际统计的是采购订单，属**命名与职责不符**，容易误导维护者 |
| 2 | `TYPE-POOLS: slis.` | 加载 ALV 类型池，ALV 报表标配，必要 |
| 4 | `TABLES: lfa1, ekko.` | 声明数据库表同时生成同名工作区（`lfa1`、`ekko`）和内表（`ltfa1`、`ltekko`）。本程序**并未使用**这些工作区，仅为让行 10-11 的 select-option 能带字段名而存在，属**过时写法**，应改为 `DATA ls_dummy TYPE zmmr_vend_s.` 或直接 `SELECT-OPTIONS s_lifnr TYPE lfa1-lifnr.` |
| 6-8 | 全局内表/结构 | 输出表用 DDIC 结构 `zmmr_vend_s`（隐含含 LIFNR/NAME1/PO_CNT 三列）；字段目录用 ALV 类型池结构；布局用 ALV 布局结构。三者生命周期为**整个程序**，且是 `display_alv` 的唯一输入源 |
| 10-11 | 选择屏幕 | `s_lifnr`（供应商号）、`s_ekorg`（采购组织），均为可选区间，允许输入单值/区间/排除/多值组合，`lfa1-lifnr` 11 位、`ekko-ekorg` 4 位 |

**设计评价**：全局变量命名（`gt_out` 遵循 `gt_` 规范内表命名）符合德语式 ABAP 传统，可读性良好。

---

### 5.2 `FORM get_data` — 取数（行 18-36）

```abap
FORM get_data.
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
  IF sy-subrc = 0.
    gt_out = VALUE #( FOR ls IN lt_vend
                      ( lifnr = ls-lifnr name1 = ls-name1 po_cnt = ls-po_cnt ) ).
  ELSE.
    MESSAGE '无符合条件的供应商' TYPE 'I'.
    STOP.
  ENDIF.
ENDFORM.
```

**逐段解读**

1. **主查询（行 19-28）**
   - `INNER JOIN ekko ON a~lifnr = b~lifnr`：以供应商为主表连接采购订单头。语义上等价于"每个供应商 → 其 PO 列表"。
   - `a~lifnr IN @s_lifnr`：`@` 主机变量传选择屏范围，**正确使用**（安全参数化，无 SQL 注入风险）。
   - `b~bstyp = 'F'`：**业务上正确的关键过滤**。`BSTYP` 为单据类别，`F` = 采购订单；排除框架协议（`C`/`B`）、退货（R）等。这是本程序最核心的业务语义。
   - `GROUP BY a~lifnr, a~name1` + `COUNT( DISTINCT b~ebeln )`：按供应商分组统计订单张数。
   - `INTO TABLE @DATA(lt_vend)`：内联声明局部内表，作用域仅限本 `PERFORM`，写法现代。

2. **结果判定（行 29-35）—— 逻辑失效点**
   - `SELECT ... INTO TABLE` 无论返回 0 行还是 N 行，`sy-subrc = 0`。因此 `IF sy-subrc = 0` **恒成立**，`ELSE` 分支（"无符合条件的供应商"提示）是**死代码**。
   - 实际用户体验：查不到数据时，程序**静默进入 ALV 并显示空表**，用户看不到任何"无数据"提示，只会觉得"程序坏了"。

3. **数据拷贝（行 30-31）—— 冗余**
   - `VALUE #( FOR ls IN lt_vend ... )` 逐字段手工映射，功能上与 `CORRESPONDING` 或直接在 SQL 中 `INTO TABLE @gt_out` 等价，属于**多写一遍映射规则、多一处维护点**（DDIC 结构加字段时要改两处）。

**优点**：SQL 过滤条件正确、host variable 用法规范、聚合前置在数据库端（未把明细拉到内存再 COUNT，这点比很多报表写法好得多）。

**风险**：空结果无提示；COUNT 类型与 DDIC 字段类型可能不匹配（若 `PO_CNT` 定义为 `NUMC(3)`，COUNT 结果在传输时会被截断/转换）。

---

### 5.3 `FORM build_fieldcat` — 字段目录（行 38-47）

```abap
FORM build_fieldcat.
  CALL FUNCTION 'REUSE_ALV_FIELDCATALOG_MERGE'
    EXPORTING
      i_structure_name = 'ZMMR_VEND_S'
    CHANGING
      ct_fieldcat     = gt_fcat.
  IF sy-subrc <> 0.
    MESSAGE '字段目录生成失败' TYPE 'E'.
  ENDIF.
ENDFORM.
```

**逐段解读**

- `REUSE_ALV_FIELDCATALOG_MERGE`：以 DDIC 结构为源批量生成字段目录，**自动带出**数据元素短文本（作为默认列标题）、长度/输出长度对齐。这是 ALV 最推荐的字段目录生成方式，比逐字段 `APPEND` 简洁一个数量级。
- `CHANGING ct_fieldcat = gt_fcat`：FM 内部先清空再填充，因此 `gt_fcat` 无需预初始化。
- `IF sy-subrc <> 0 → MESSAGE TYPE 'E'`：FM 失败即报错终止，处理正确（结构不存在、字段不匹配都会置位）。

**设计缺陷**：
- 生成后**未做任何定制**：没有把 `LIFNR` 设为 `KEY` 列，没有 `HOTSPOT`（无法点击供应商号下钻），没有对 `PO_CNT` 设置 `NO_ZERO` / 右对齐 / 数字格式，没有 `FIXED` 锁定前两列。
- 错误信息无消息号、无 `INTO` 详情，线上排查困难。
- 未使用 `ct_fieldcat` 的第二参数传递，字段目录在 FM 内部完全由结构决定 → **DDIC 结构改动会直接影响报表外观**（这既是优点也是隐式耦合）。

---

### 5.4 `FORM display_alv` — 展示（行 49-58）

```abap
FORM display_alv.
  gs_layo-zebra = 'X'.
  gs_layo-get_sel_info = 'X'.
  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      is_layout   = gs_layo
      it_fieldcat = gt_fcat
    TABLES
      t_outtab    = gt_out.
ENDFORM.
```

**逐段解读**

- `gs_layo-zebra = 'X'`：斑马纹隔行底色，提升长列表可读性（好习惯）。
- `gs_layo-get_sel_info = 'X'`：向 FM 传递行选择状态信息。但**本程序没有任何 `it_*` 回调读取这些信息**（无 `is_list_info`、`es_list_info`），该设置实际**无任何作用**，属于从其他程序复制来的残留代码。
- `TABLES t_outtab = gt_out`：传统 ALV 输出表接口（未使用 `gt_out` 的"标准"传入方式，属正常）。
- **未设置 `it_sort`**：ALV 打开时无预排序（不会自动按 `PO_CNT` 降序），用户必须手动点表头。**未设置 `i_save`**：布局变式不保存，用户的个性化排序/隐藏列在下次运行后丢失。**未设置标题栏**（`slis_layout_alv-title`/`i_title`）：ALV 标题栏空。
- **无用户交互回调**：`i_callback_program` / `i_callback_user_command` 均未指定 → ALV 上的标准按钮（"布局"、"保存变式"）大多不可用/无效，行选择、双击均无反应。

---

## 六、问题清单（按严重度分级）

### P0 — 功能性缺陷（会让报表"说错话"或"装死"）

| # | 位置 | 问题 | 后果 |
|---|---|---|---|
| P0-1 | `get_data` 行 29 | `SELECT ... INTO TABLE` 后用 `sy-subrc = 0` 判空，结果**恒为真** | 无数据时静默显示空 ALV，用户无任何提示；ELSE 分支为死代码 |
| P0-2 | 行 29-35 | 空结果没有"友好出口" | 用户误以为程序故障，运维工单增加 |
| P0-3 | 全程序 | 无任何 `AUTHORITY-CHECK` | 任何有权限跑这个报表的用户可看到**全部供应商号与名称**，存在越权数据暴露风险 |
| P0-4 | 行 30-31 | `COUNT`（数值）与 DDIC `PO_CNT` 类型无对齐约束 | 若 `PO_CNT` 为短 `NUMC`/`CHAR`，大数值被静默截断，**统计结果错误** |

### P1 — 可用性与用户体验

| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| P1-1 | `display_alv` 行 52-57 | 无默认排序 | `it_sort` 按 `PO_CNT` 降序，打开即见重点 |
| P1-2 | 同上 | 无标题、无总计行 | 加 `slis_layout_alv-title` + `slis_tab_totals` |
| P1-3 | 同上 | 无 `i_save` | 布局变式无法保存，用户每次重调 |
| P1-4 | `get_sel_info='X'` 行 51 | 设置了但无回调消费 | 死配置，应删除或补齐回调 |
| P1-5 | `build_fieldcat` 行 43 后 | 字段目录零定制 | 至少设 `KEY`、`HOTSPOT`、`NO_ZERO` |
| P1-6 | 全程序 | 无下钻 | 用户拿到"供应商有 N 张 PO"后仍要另查明细，报表价值受限 |
| P1-7 | 行 10-11 | 两个选择条件全可选 | `s_lifnr` 留空即全表扫描，风险与性能双重问题 |

### P2 — 健壮性与性能

| # | 位置 | 问题 | 风险 |
|---|---|---|---|
| P2-1 | 行 19-28 | 单条 SQL 全量聚合 LFA1×EKKO，无进度指示 | 大范围查询时无 `PROGRESS`/状态提示，用户以为死机；可能 work process 内存溢出 dump |
| P2-2 | 行 19-28 | 未过滤采购订单有效性（删除标记 / 有效期 `BEDAT`/`EINDT`） | 统计可能包含已失效、已冻结或已删除的单据，与财务口径不一致 |
| P2-3 | 行 23 | `INNER JOIN` 仅按 `LIFNR` | 依赖数据库选择正确的驱动表/索引；EKKO 上若无 `EKORG+LIFNR` 索引则性能差 |
| P2-4 | 行 34 | `MESSAGE ... TYPE 'I'` + `STOP` | `STOP` 直接终止整个事务/批处理，不适合程序化复用 |
| P2-5 | 行 26 | `BSTYP = 'F'` 硬编码 | 业务规则变更需改程序，建议参数化或带注释说明 |

### P3 — 规范性 / 可维护性

| # | 位置 | 问题 |
|---|---|---|
| P3-1 | 行 4 | `TABLES:` 过时，隐式生成未被使用的工作区/内表 |
| P3-2 | 行 19-31 | 新旧语法混用（`@DATA()` 与 `FORM/PERFORM`、`TABLES`） |
| P3-3 | 行 1 vs 19-27 | 程序名 `MMR` 与实际统计 PO 的职责不符 |
| P3-4 | 行 30-31 | `VALUE #` 手工映射冗余，与 DDIC 结构构成**双份维护点** |
| P3-5 | 行 18-58 | 三个 FORM 靠全局变量通信，无参数传递，不可复用、不可测试 |
| P3-6 | 行 33/45 | `MESSAGE` 无消息号、无消息类，翻译与维护不便 |
| P3-7 | 行 21 | `COUNT(DISTINCT ...)` 中的 `DISTINCT` 冗余（LFA1 按 LIFNR 唯一，组内 `ebeln` 天然不重复），额外排序/哈希开销 |

---

## 七、改进建议（分优先级落地）

### 7.1 立即修复（P0，改动最小、收益最大）

**① 用行数判断替代 `sy-subrc`**

```abap
  IF lines( lt_vend ) = 0.
    MESSAGE '无符合条件的供应商' TYPE 'S'.
    RETURN.
  ENDIF.

  gt_out = CORRESPONDING lt_vend( lifnr name1 po_cnt ).
```

**② 让 SQL 直接写入目标表，去掉手工映射**

```abap
  SELECT a~lifnr, a~name1, COUNT( * ) AS po_cnt
    FROM lfa1 AS a
    INNER JOIN ekko AS b ON  a~lifnr = b~lifnr
                         AND b~ekorg IN @s_ekorg
   WHERE a~lifnr IN @s_lifnr
     AND b~bstyp  = 'F'
   GROUP BY a~lifnr, a~name1
     INTO TABLE @gt_out.
```
> `COUNT( * )` 语义与本场景完全等价（去掉无用的 `DISTINCT`）；`INTO TABLE @gt_out` 消除 `VALUE #` 的双份映射，DDIC 结构增列时无需改程序。

**③ 加授权检查**（示例，按实际权限模型替换对象）

```abap
  DATA(lv_ok) = COND #( WHEN sy-subrc = 0 THEN 1 ).

  SELECT SINGLE * FROM tpa_something ...
```
> 更典型的做法：在 `START-OF-SELECTION` 开头用 `AUTHORITY-CHECK OBJECT 'LFA1_DISP' ID 'LIFNR' DUMMY lv_lifnr`，或对组织范围做 `LIKELIHOOD` 判定，至少保证 `s_ekorg` 限制在授权组织内。

**④ 校验 `PO_CNT` 的 DDIC 类型为数值型**（`NUMC`/`CHAR` 需改结构，否则统计结果失真）。

---

### 7.2 可用性增强（P1）

```abap
FORM build_fieldcat.
  DATA: ls_layout TYPE slis_layout_alv,
        ls_sort    TYPE slis_sortinfo_alv.

  CALL FUNCTION 'REUSE_ALV_FIELDCATALOG_MERGE'
    EXPORTING
      i_structure_name = 'ZMMR_VEND_S'
    CHANGING
      ct_fieldcat     = gt_fcat.

  IF sy-subrc <> 0.
    MESSAGE ID 'ZYMM' TYPE 'E' NUMBER '010'
      WITH '字段目录生成失败（ZMMR_VEND_S）'.
  ENDIF.

  LOOP AT gt_fcat ASSIGNING FIELD-SYMBOL(<f>).
    CASE <f>-fieldname.
      WHEN 'LIFNR'.
        <f>-key       = 'X'.
        <f>-hotspot   = 'X'.
        <f>-just      = 'L'.
      WHEN 'PO_CNT'.
        <f>-no_zero   = 'X'.
        <f>-just      = 'R'.
        <f>-no_out    = ' '.
    ENDCASE.
  ENDLOOP.

  ls_sort-fieldname = 'PO_CNT'.
  ls_sort-sortorder = 'DESC'.
  APPEND ls_sort TO gt_sort.
ENDFORM.

FORM display_alv.
  gs_layo-zebra      = 'X'.
  gs_layo-title      = '供应商采购订单数量统计'.
  gs_layo-info_fcat  = 'X'.                              " ALV 工具栏帮助
  gs_layo-grid_title = gs_layo-title.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      is_layout            = gs_layo
      it_fieldcat          = gt_fcat
      it_sort              = gt_sort
      i_save               = 'A'                          " 允许保存布局变式
      i_default_layout     = 'ZMM_VEND_LIST_DEFAULT'
      i_callback_program   = sy-repid
      i_callback_user_command = 'USER_COMMAND'
    TABLES
      t_outtab             = gt_out.
ENDFORM.
```

配合下钻（`USER_COMMAND` 中处理 `hotspot_click` / 双击）跳到 PO 明细报表，即可把"数量报表"升级为"数量 + 明细"的分析入口。同时可用 `stext = '合计'` 让 ALV 显示合计行。

---

### 7.3 健壮性与性能（P2）

```abap
FORM get_data.
  DATA: lt_vend TYPE TABLE OF zmmr_vend_s,
        lv_text TYPE string.

  lv_text = '正在统计供应商采购订单数据…'.
  CALL FUNCTION 'SAPPROGRESS'                    " 长查询给用户反馈
    EXPORTING percent_complete = 0
    TEXT       = lv_text.

  " 有时效/删除标记过滤需求时补充（需与业务确认口径）：
  "   AND b~bedat  >= @lv_bedat        " 单据有效期
  "   AND b~eindt  <= @sy-datum        " 截止日仍有效

  SELECT a~lifnr, a~name1, COUNT( * ) AS po_cnt
    FROM lfa1 AS a
    INNER JOIN ekko AS b ON  a~lifnr = b~lifnr
                         AND b~ekorg IN @s_ekorg
   WHERE a~lifnr IN @s_lifnr
     AND b~bstyp  = 'F'
   GROUP BY a~lifnr, a~name1
    INTO TABLE @gt_out.

  IF gt_out IS INITIAL.
    MESSAGE '无符合条件的供应商' TYPE 'S'.
    RETURN.
  ENDIF.
ENDFORM.
```

要点：
- 用 `RETURN` 退出 `PERFORM` 而不是 `STOP`，不破坏事务与批处理上下文。
- 把 `s_ekorg` 从 `WHERE` 移到 `ON` 上（多表过滤放 `ON` 优于 `WHERE`），数据库更容易选择"ekko 驱动 + lfa1 索引查找"的执行计划。
- 对 `PO_CNT` 排序的需求，考虑为报表场景建**关键指标（CD Key Figure）**或走 CDS/AMDP，把聚合下推到 HANA 层，避免 ABAP 内存压力。

---

### 7.4 架构升级建议（P3，改造型）

当前"FORM + 全局变量 + `REUSE_ALV_*`"是 ALV 报表的标准形态，可维护性尚可；但如果团队有统一规范，建议演进为：

```abap
REPORT zmmr_vend_list.

CLASS lcl_report DEFINITION FINAL.
  PUBLIC SECTION.
    CLASS-METHODS run.
  PRIVATE SECTION.
    CLASS-DATA gt_out TYPE TABLE OF zmmr_vend_s.
    CLASS-METHODS get_data RETURNING VALUE(et_out) TYPE gt_out
                             RAISING cx_sy_conversion_error.
    CLASS-METHODS display.
ENDCLASS.

CLASS lcl_report IMPLEMENTATION.
  METHOD get_data.
    SELECT a~lifnr, a~name1, COUNT( * ) AS po_cnt
      FROM lfa1 AS a
      INNER JOIN ekko AS b ON  a~lifnr = b~lifnr
                           AND b~ekorg IN @s_ekorg
     WHERE a~lifnr IN @s_lifnr
       AND b~bstyp  = 'F'
     GROUP BY a~lifnr, a~name1
       INTO TABLE @et_out.
  ENDMETHOD.

  METHOD display.
    " CL_SALV_TABLE + SALV_EXPORT：自带排序/列布局/导出 Excel/保存变式
    DATA(lo_alv) = NEW cl_salv_table( et_out ).
    lo_alv->get_layout( )->set_zebra( COND cl_salv_table_layout=>zebra WHEN 1 = 1 ).
    lo_alv->get_column( 'PO_CNT' )->set_alignment( if_salv_c=>alignment_right ).
    lo_alv->add_standard_function( if_salv_gui_functions=>salv_export ).
  ENDMETHOD.

  METHOD run.
    gt_out = get_data( ).
    display( ).
  ENDMETHOD.
ENDCLASS.

START-OF-SELECTION.
  lcl_report=>run( ).
```

优势：无全局可变状态、可单元测试、字段目录由列对象直接操控、`i_save`/导出/变式等常用功能开箱即用。若仅做小修，保留现有形态同样可行。

---

## 八、风险与上线检查清单

- [ ] `ZMMR_VEND_S-PO_CNT` 必须为数值类型（`NUMC` 长度足够或 `QUAN`/`INT2`），否则大数值被截断
- [ ] 补 `AUTHORITY-CHECK`，明确该报表的供应商数据可见范围
- [ ] 与业务确认 `BSTYP = 'F'` 之外是否需排除已删除/已冻结/已过期 PO
- [ ] 与业务确认金额口径（是否需展示采购订单总额 `EKPO-NETWR`，以及多币种如何处理；引入 `EKPO` 需先在子查询内聚合，避免行数放大导致 `COUNT` 虚高）
- [ ] 生产数据量下测试空范围查询（`s_lifnr`/`s_ekorg` 全空）的运行时间与内存占用
- [ ] 若报表将开放给采购组织外的用户，需在 `START-OF-SELECTION` 强制限定 `s_ekorg`

---

## 九、总评

| 维度 | 评分（5 分制） | 说明 |
|---|---|---|
| 业务逻辑正确性 | 3.0 | SQL 过滤与聚合正确，但空结果判定失效、DDIC 类型约束缺失 |
| 结构清晰度 | 4.0 | 三段式职责清晰、命名规范、DDIC 驱动字段目录为佳作 |
| 健壮性 | 2.0 | 无授权、无进度、无排序、无变式、无合计 |
| 性能 | 3.0 | 聚合在 DB 端完成（优于常见写法），但缺索引/分区考量与进度反馈 |
| 可维护性 | 2.5 | 新旧语法混用、冗余映射、程序名与职责不符、无消息号 |
| **综合** | **2.9** | **可作为培训样例，但按上表 P0/P1 项修订后再交付业务使用** |

**优先级排序建议**：先改 `get_data` 的判空与取数（10 行内可完成，收益最大）→ 补授权检查 → 加默认排序/标题/合计 → 补下钻与变式保存 → 视团队规范决定是否 OO 化。
