# ABAP 报表程序分析报告：`ZMRR_VEND_LIST`

> 走读对象：`evals/zmmr_vend_list.abap`（58 行，Report 报表，ABAP 7.40 SP05+ 语法）
> 分析视角：业务问题 → 架构 → 执行流程 → 分组逐行讲解 → 问题清单 → 改进建议

---

## 0. 一句话结论

这是一个**教科书式的三段式过程报表**：`get_data`（取数）→ `build_fieldcat`（生成列定义）→ `display_alv`（ALV 展示）。主流程线性、职责单一、可读性不错；但**统计口径存在实质缺陷**（`COUNT(DISTINCT ebeln)` 跨采购组织去重、删除标记未过滤、空选择范围会全表 JOIN GROUP BY），并且**告警信息、权限校验、排序/合计/变式/回调全部缺失**，`MESSAGE` 直接写中文长字面量还可能根本无法通过语法检查。

---

## 1. 源程序清单（带行号）

```abap
REPORT zmmr_vend_list.                                          " 1
TYPE-POOLS: slis.                                               " 2

TABLES: lfa1, ekko.                                             " 4

DATA: gt_out  TYPE TABLE OF zmmr_vend_s,                        " 6
      gt_fcat TYPE slis_t_fieldcat_alv,                         " 7
      gs_layo TYPE slis_layout_alv.                             " 8

SELECT-OPTIONS: s_lifnr FOR lfa1-lifnr,                        " 10
                s_ekorg FOR ekko-ekorg.                         " 11

START-OF-SELECTION.                                             " 13
  PERFORM get_data.                                             " 14
  PERFORM build_fieldcat.                                       " 15
  PERFORM display_alv.                                          " 16
```

```abap
FORM get_data.                                                  " 18
  SELECT a~lifnr,                                               " 19
         a~name1,                                               " 20
         COUNT( DISTINCT b~ebeln ) AS po_cnt                   " 21
    FROM lfa1 AS a                                              " 22
    INNER JOIN ekko AS b ON a~lifnr = b~lifnr                   " 23
    WHERE a~lifnr IN @s_lifnr                                   " 24
      AND b~ekorg IN @s_ekorg                                   " 25
      AND b~bstyp = 'F'                                         " 26
    GROUP BY a~lifnr, a~name1                                   " 27
    INTO TABLE @DATA(lt_vend).                                  " 28
  IF sy-subrc = 0.                                              " 29
    gt_out = VALUE #( FOR ls IN lt_vend                         " 30
                      ( lifnr = ls-lifnr name1 = ls-name1 po_cnt = ls-po_cnt ) ). " 31
  ELSE.                                                         " 32
    MESSAGE '无符合条件的供应商' TYPE 'I'.                         " 33
    STOP.                                                       " 34
  ENDIF.                                                        " 35
ENDFORM.
```

```abap
FORM build_fieldcat.                                            " 38
  CALL FUNCTION 'REUSE_ALV_FIELDCATALOG_MERGE'                  " 39
    EXPORTING i_structure_name = 'ZMMR_VEND_S'                  " 41
    CHANGING  ct_fieldcat     = gt_fcat.                        " 43
  IF sy-subrc <> 0.                                             " 44
    MESSAGE '字段目录生成失败' TYPE 'E'.                          " 45
  ENDIF.                                                        " 46
ENDFORM.
```

```abap
FORM display_alv.                                               " 49
  gs_layo-zebra = 'X'.                                          " 50
  gs_layo-get_sel_info = 'X'.                                   " 51
  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'                        " 52
    EXPORTING is_layout = gs_layo it_fieldcat = gt_fcat         " 54-55
    TABLES     t_outtab  = gt_out.                              " 57
ENDFORM.
```

（行 26 的 `AND b~bstyp = 'F'` 与行 30-31 的 `VALUE #( ... )` 在原文中分行书写，此处为可读性做了合并。）

---

## 2. 业务问题

| 维度 | 结论 |
|---|---|
| **报表名** | `ZMRR_VEND_LIST`（MM 采购域，供应商清单） |
| **业务问题** | "按供应商维度，统计其在指定采购组织范围内发生过多少张采购订单（PO）" —— 典型的**供应商活跃度盘点 / 采购额分层 / 供应商清理（找出零单或低频供应商）** 的第一步。 |
| **使用者** | 采购员 / 供应商主数据管理（MDM）人员 / 采购经理 |
| **输入** | 供应商号范围 `S_LIFNR`、采购组织范围 `S_EKORG` |
| **输出** | 三列 ALV：供应商号、供应商名称、PO 张数 |
| **隐含的候选场景** | ① 找活跃/呆滞供应商分层；② 采购组织维度供应商归口梳理；③ 配合主数据清理定位"只有零星单据"的可疑供应商 |

**必须指出的业务口径边界**（很多人会误读这个报表）：

- 因为是 `INNER JOIN` + `GROUP BY`，**只有"至少有一张符合条件的 PO"的供应商才会出现**。它**查不出"没有采购订单的供应商"**——而后者恰恰是供应商清理场景里最想要的那批人。
- `PO_CNT` 是**订单张数（DISTINCT 单号）**，不是订单行项目数、不是采购金额。要做商业价值分层缺 `SUM( EKKO-NETWR )` + `EKKO-WAERS`。
- 报表本身**没有任何动作能力**（无 F4、无行级跳转、无导出），用户看完还得自己去 ME23N 查，属于"只读断头路"。

---

## 3. 架构分析

### 3.1 技术栈与外部对象依赖

| 类别 | 对象 | 作用 |
|---|---|---|
| 程序类型 | `REPORT`（非 OO） | 传统可执行报表，事件驱动 |
| 类型池 | `SLIS` | 让 `REUSE_ALV_*` 系列 FM 的类型可见 |
| DDIC 表 | `LFA1`（供应商主数据）、`EKKO`（采购订单抬头） | 数据来源 |
| DDIC 结构 | `ZMMR_VEND_S` | **ALV 输出结构 + 字段目录的唯一来源**（本次分析不可见，列为待确认项） |
| FM | `REUSE_ALV_FIELDCATALOG_MERGE` | 由 DDIC 结构自动生成列定义 |
| FM | `REUSE_ALV_GRID_DISPLAY` | 全屏 ALV Grid（带工具栏、排序、导出） |
| 新语法 | `@` Host 变量、内联 `DATA( )`、`VALUE #( )`、`FOR ... IN` 迭代器 | 隐含要求 **7.40 SP05+** |

### 3.2 分层结构（三层 + 全局状态）

```
┌──────────────────────────────────────────────────────────────┐
│  事件层  START-OF-SELECTION   (L13-16)                        │
│          纯编排：get_data → build_fieldcat → display_alv      │
├──────────────────────────────────────────────────────────────┤
│  展现层  build_fieldcat (L38) │ display_alv (L49)             │
│          列定义（FMeta 自动生成）│ 布局 + 输出                  │
├──────────────────────────────────────────────────────────────┤
│  数据层  get_data (L18)                                       │
│          Open SQL(JOIN + GROUP BY + COUNT DISTINCT) → GT_OUT │
├──────────────────────────────────────────────────────────────┤
│  共享状态（模块级 DATA，L6-8）GT_OUT / GT_FCAT / GS_LAYO      │
│  —— FORMS 靠全局变量通信，不传参、不返回值                      │
└──────────────────────────────────────────────────────────────┘
```

### 3.3 数据流

```
S_LIFNR ─┐
S_EKORG ─┴─(@)→ [ SQL: LFA1 ⨝ EKKO, bstyp='F', GROUP BY ]→ LT_VEND
                                                          │
                     VALUE #( FOR ... ) 逐字段显式映射 ─────┤
                                                          ▼
                                        GT_OUT (TYPE TABLE OF ZMMR_VEND_S)
                                                          │
              ZMMR_VEND_S ─→ REUSE_ALV_FIELDCATALOG_MERGE ─┴─→ GT_FCAT
                                                          │
                                        GS_LAYO(zebra, get_sel_info) ─┐
                                                                          ▼
                                                  REUSE_ALV_GRID_DISPLAY (T_OUTTAB=GT_OUT)
```

**关键设计取舍解读：**

1. **字段目录交给 FM 自动生成**（而不是手写 30 行 `APPEND ls_fcat`）——这是本程序最大的优点：`ZMMR_VEND_S` 变成了"数据契约 + 展示契约"的**单一事实来源**，加一列只需改 DDIC，不用改代码。
2. **FORMS 不传参，靠 `gt_`/`gs_` 全局变量串联**——ABAP 过程式报表的传统风格，代价是：FORMS 无法单独测试、调用顺序成为隐式契约（`build_fieldcat` 必须在 `display_alv` 之前跑，代码里没有任何东西保护这一点）。
3. **展示层（`slis_*`）被直接暴露在报表里**——业务逻辑和 ALV 细节混在同一个 include-free 的 REPORT 里。

---

## 4. 执行流程

### 4.1 ABAP 事件序列（隐式 + 显式）

| # | 事件 | 实际发生什么 | 状态 |
|---|---|---|---|
| 1 | `LOAD-OF-PROGRAM` | 类型池 `SLIS` 装入；全局 DATA 初始化 | 隐式 |
| 2 | 生成选择屏幕 | `TABLES: lfa1, ekko` 把两个工作区绑到选择选项上，生成两个输入字段（默认空白 = 全选） | 隐式 |
| 3 | `INITIALIZATION` | 空 | 隐式 |
| 4 | `AT SELECTION-SCREEN` | 空（无校验、无 F4、无变式） | 隐式 |
| 5 | **`START-OF-SELECTION`** | `PERFORM get_data` → `PERFORM build_fieldcat` → `PERFORM display_alv` | **显式 L13-16** |
| 6. `END-OF-SELECTION` | 空（ALV 已在 5 中全屏输出） | 隐式 |
| 7 | 基本列表处理 | 空列表收尾（未 `INCLUDE SAPL1SP`，所以没有标准 ALV 变式页） | 隐式 |

### 4.2 核心流程详解

**Step 1 — 取数（`get_data`）**

- 输入：两个范围通过 `@` 逃逸作为 Host 变量直接下推到数据库（`IN @s_lifnr`），不是先读进内表再 `IN` 展开——性能上是正确的现代写法。
- 谓词：`a~lifnr IN s_lifnr`（供应商）；`b~ekorg IN s_ekorg`（采购组织）；`b~bstyp = 'F'`（只统计采购订单类型 F，屏蔽框架协议/库存调拨等其他单据）。
- 聚合：`COUNT( DISTINCT b~ebeln )`，按 `LIFNR + NAME1` 分组。`NAME1` 来自 LFA1，与 `LIFNR` 一一对应，所以分组键在业务上是"每供应商一行"。
- 结果：行数 = 有单供应商数（通常千级以内），列 `PO_CNT` 来自 `COUNT`，运行时类型是 `INT8`。
- 空结果：`sy-subrc = 0` 有数据 / `= 4` 无数据，**判断方向正确**。
- 映射：SELECT 字段名与 `ZMMR_VEND_S` 组件同名，理论上可直接赋值，这里用 `VALUE #( FOR ... )` 逐字段搬——保守、防字段顺序错位，但也说明作者对结构一致性没把握（见改进 §6.2）。

**Step 2 — 生成列定义（`build_fieldcat`）**

- `REUSE_ALV_FIELDCATALOG_MERGE` 读 `ZMMR_VEND_S` 的 DDIC 文本、长度、转换程序，生成 `GT_FCAT`。
- 失败则 `MESSAGE ... TYPE 'E'`（`TYPE 'E'` 会直接终止，语义上等价于 dump 前的优雅退出）。
- **注意**：文本、语言、列宽、是否可见全部由 DDIC 决定 → 中文列标题必须在 DDIC 里维护中文短文本，否则 ALV 会显示字段名。

**Step 3 — 输出（`display_alv`）**

- `gs_layo-zebra = 'X'` 斑马纹（可读性基础配置）。
- `gs_layo-get_sel_info = 'X'` 要求显示"选中行数"信息——但程序**没有配 `box_sel_name`、也没有 checkbox 字段、也没传 `it_selinfo`**，所以这一行实际上是"半配置"：勾选功能其实不可用。
- `REUSE_ALV_GRID_DISPLAY` 一次性把布局、字段目录、数据交给 ALV Grid，Grid 自身提供排序、筛选、合计、导出（标准工具栏）。
- 之后程序正常结束。

### 4.3 两条特殊路径

```
无数据路径：SELECT → sy-subrc=4 → MESSAGE '无符合条件的供应商' TYPE 'I' → STOP → 程序终止，ALV 不显示
列定义失败：MESSAGE '字段目录生成失败' TYPE 'E' → 立即终止
```

两条路径都用**硬编码中文长字面量**（见 §5.1 P0-1）。

---

## 5. 分组逐行讲解

### 5.1 `get_data`（L18-36）：取数与整形

**做得对的地方**

- 用了 `@` Host 变量而非字符串拼接，无 SQL 注入面。
- `INNER JOIN` + `GROUP BY` 一次性把聚合下推到 DB，返回的是"聚合后的小结果集"，内存和传输开销都很低——这是**报表取数的正确姿势**。
- `sy-subrc` 空结果判断方向正确，没有写成 `IF sy-subrc = 4` 以外的花活。
- 没有在 SELECT 后追加 `WRITE` / `MESSAGE` 之类不允许的语句，取数逻辑干净。

**问题**

1. **【P0-1】`MESSAGE` 文本字面量超长（第 33、45 行）**：`MESSAGE '无符合条件的供应商' TYPE 'I'` 里的字面量有 9 个汉字。ABAP 规定 `MESSAGE` 的文本只接受 **1~3 个字符的字面量**，或 `TEXT-xxx` 文本符号；超过 3 个字符会被当作**文本符号名**解析。本程序既没建 `TEXT-001`，也没建 `T100` 消息类，因此**在 SE38 语法检查/激活阶段极可能被判为错误（未定义文本符号），或运行到该分支时出错**。请务必现场用 SE38 编译验证；若能编译通过，它也是"硬编码不可翻译"的坏味道。规范写法见 §6.1。
2. **【P0-2】`COUNT(DISTINCT ebeln)` 的去重键不含采购组织**（第 21、23 行）：`EKKO` 主键是 `LIFNR + EBELN`，而**采购单号段通常是"按采购组织/采购组"独立编号**。同一个 `EBELN` 数值完全可能在两个不同 `EKORG` 下各存在一张合法单据。当前写法会把它们算成 1 张 → **少计**。这是本程序最实质的口径错误。
3. **【P0-3】未过滤删除标记**：`EKKO` 有 `LOEKZ`（采购单据删除标识）和 `BHKST`（整单归档删除标记），LFA1 有 `BLOCK`（供应商冻结）、`LOEKZ`（采购冻结）。当前 SQL 全部不过滤 → **已删除的单据、已冻结的供应商都被计入**。这在"清理供应商"场景里是致命的（会把已冻结/已删除的数据当活跃数据报给业务）。
4. **【P0-4】空选择范围 = 全表扫描**：`S_LIFNR`、`S_EKORG` 留空即"全部"。`EKKO` 是千万~亿级大表，`LFA1` 是十万级，一次"全供应商 × 全采购组织"的 JOIN + `COUNT(DISTINCT)` 分组在对话框里极易**数据库超时/dump**。没有强制 `OBLIG`、没有日期范围、没有 `UP TO` 行数限制、也没有拆到后台作业的提示。
5. **【P1】`INNER JOIN` 语义窄**：查不到"零订单供应商"（见 §2）。若业务问的是"完整供应商清单 + 单数（含 0）"，需要改为聚合 `EKKO` 后再 `LEFT JOIN`/`FOR ALL ENTRIES` 补 `LFA1`。
6. **【P1】`COUNT` 之外的商业维度缺失**：无 `SUM( EKKO-NETWR )`、无 `EKKO-WAERS`、无 `MAX( EKKO-BEDAT )`（最近下单日）、无 `EKKO-BUKRS`。做不了金额分层、也做不了"按最近活跃度排序"。
7. **【P1】`PO_CNT` 命名**：`COUNT(DISTINCT)` 是"去重单号数"，`CNT` 容易与行项目数混淆，建议 `po_dist_cnt` 之类；同时需确认 `ZMMR_VEND_S-PO_CNT` 的 DDIC 类型是 `INT8`/`LVC_TOTCOUNT`（计数器域）而不是 `CHAR10`——**若是字符型，ALV 的合计与排序会按字符串比较（'9' > '10'），结果错得很难看**。
8. **【P1】`MESSAGE ... TYPE 'I'` + `STOP`（第 33-34 行）**：
   - 交互式：`STOP` 可用但会弹信息框并留下空列表，语义不如 `MESSAGE ... TYPE 'S'. LEAVE LIST-PROCESSING.` 干净。
   - **后台作业：`TYPE 'I'` 的信息消息不会改变作业状态，作业会"绿灯成功"**。如果有人把这个报表丢进后台跑"全量供应商盘点"，拿到的是一张"成功但没数据"的绿勾作业。至少要 `TYPE 'W'`/`'E'`，或按 `sy-batch` 分支处理。
   - `IF sy-subrc = 0 ... ELSE` 用 `ELSE` 兜住了"非 0"的一切情形（语义上应该是 `= 4`），虽然 `INTO TABLE` 只会返回 0/4，但写法不精确。
9. **【P2】`VALUE #( FOR ... )` 显式映射（第 30-31 行）**：字段名与结构组件同名时，`CORRESPONDING #( )` 一行即可（见 §6.2）。当前写法冗长，且**新增字段时必须手工补一行**，容易漏。
10. **【P2】无 `AUTHORITY-CHECK`**：整个程序没有任何授权对象校验。LFA1/EKKO 的 SELECT **不会**触发 SAP 对这些表的隐式权限检查（隐式检查只对 `TABLES` 中声明的 SAP 标准销售视图/订单表生效），所以任何能执行报表的用户都会看到**全量供应商与全量订单统计**。这在多公司/多采购组织隔离环境里属于越权风险。

### 5.2 `build_fieldcat`（L38-47）：列定义

**做得对的地方**：不手写字段目录，DDIC 驱动，可维护性远好于硬编码 `APPEND`。

**问题**

1. **【P1】列文本的语言问题**：FM 读的是 DDIC 短文本 + 用户语言。若 `ZMMR_VEND_S` 描述只维护了英文/德文，中文用户在 ALV 里看到的是字段名而非中文标题。解法不是改代码，而是**在 DDIC 里维护中文短文本**，或用 `REUSE_ALV_TREE_LEVEL_HEADERS`/`it_fieldcat-scrtext_*` 覆盖（本程序未做）。
2. **【P1】没有 `it_sort`**：`REUSE_ALV_GRID_DISPLAY` 不传 `IT_SORT` 时按 DB 分组返回的顺序（近似 LIFNR 升序）显示。"按订单数从多到少"几乎肯定是用户的第一诉求，现在是缺失的。
3. **【P1】没有合计/小计**：不传 `IT_SORT` 的汇总配置 + 字段 `do_sum`，用户无法一行看到"共 N 个供应商 / M 张单"。
4. **【P2】未隐藏技术字段**：若 `ZMMR_VEND_S` 里带了技术字段（如 `MANDT`、选择标识、日志字段），FM 会把它们一并输出到屏幕上。可用 `i_no_top = 'X'`、事后 `DELETE gt_fcat WHERE tech = 'X'` 或 `no_out = 'X'` 处理。
5. **【P2】失败处理粗糙**：`IF sy-subrc <> 0` + 硬编码文本（同样有超长字面量问题）；更稳妥的是 `IF gt_fcat IS INITIAL` 判断"有没有拿到列"，并把错误信息带上程序名。

### 5.3 `display_alv`（L49-58）：布局与输出

**做得对的地方**：`zebra` 是性价比最高的一行配置；选用了 Grid 版 FM（有工具栏、排序、汇总、Excel 导出），比 `REUSE_ALV_LIST_DISPLAY` 体验好一个量级。

**问题**

1. **【P1】`get_sel_info = 'X'` 是无效配置**：该标志只在存在可勾选列时才有意义。程序没配 `box_sel_name`、`it_selinfo`，也没插 checkbox 字段 → 用户看不到勾选框，"选中行数"永远是 0。要么删掉这行保持诚实，要么补齐选择功能。
2. **【P1】无变式保存**：未传 `i_save`/`is_variant`，用户精心调好的列顺序、隐藏列、筛选条件**不会保存**，下次打开就丢——而 `get_sel_info` 的存在说明开发者是有"多选后处理"意图的。
3. **【P1】无标题**：`i_title`/`grid_title` 没设，ALV 顶栏无标题（只有 ALV 标准标题），用户不知道这是"哪个采购组织口径下的数据"。
4. **【P1】无 `i_callback_user_command`**：没有双击/按钮回调 → **报告是"死"的**，用户必须自己拿 `LIFNR` 去 ME23N 手工查。行级下钻（选中供应商 → 跳该供应商的 PO 清单，或 `SET PARAMETER` 后 `CALL TRANSACTION 'ME23N'`）是这个报表最大的可用性增量。
5. **【P2】无 `i_salv_*`/无 `it_exclude`**：工具栏未做精简，标准按钮（含部分后台不常用项）全部暴露。
6. **【P2】无异常/边界处理**：不做 `empty` 判断（虽然空结果在 `get_data` 被拦截了，但若将来有人删掉 `STOP`，ALV 会显示"无数据"空表）、不做 `INCONSISTENT_PARAMETERS` 之类 `EXCEPTIONS` 声明。

### 5.4 全局声明区（L1-11）：架构层

1. **【P2】`TABLES: lfa1, ekko`**：只为了给 `SELECT-OPTIONS ... FOR xxx-yyy` 提供字典类型绑定，程序内部并未使用这两个工作区。可保留（惯例），但会让人误以为 SELECT 用了工作区。纯现代写法是 `TYPES ty_lifnr TYPE lfa1-lifnr` + `SELECT-OPTIONS ... FOR lfa1-lifnr`（仍需绑定），实践中保留 `TABLES` 反而更清晰。
2. **【P2】变量命名规范**：`gt_`/`gs_`/`s_` 前缀正确，是 SAP 社区约定；`po_cnt` 语义待明确（见 §5.1-7）。
3. **【P2】无可测试性**：全部逻辑藏在 REPORT 的 FORMS 里。ABAP Unit 无法对一个 `REPORT` 做有意义的单元测试（它既不能被实例化、也没有可注入的依赖）。**任何取数逻辑的回归都要靠手工 F8 + 对数**。

---

## 6. 问题清单（按严重度）

| # | 位置 | 问题 | 影响 | 严重度 |
|---|---|---|---|---|
| 1 | L33 / L45 | `MESSAGE` 中文长字面量（9 字）不合规、未建 `T100` | 编译或运行期报错；不可翻译 | **P0** |
| 2 | L21 | `COUNT(DISTINCT ebeln)` 跨 `EKORG` 去重 | 跨采购组织同号订单被合并，**单数少计** | **P0** |
| 3 | L26 附近 | 未过滤 `EKKO-LOEKZ`/`BHKST`、`LFA1-BLOCK`/`LOEKZ` | 已删除单据/已冻结供应商被当作有效数据 | **P0** |
| 4 | L10-11 | 选择范围可全空 | 全表 JOIN + 分组，对话框易超时/dump | **P0** |
| 5 | 全程序 | 无 `AUTHORITY-CHECK` | 越权查看全量供应商数据 | **P0** |
| 6 | L52-57 | 无 `it_sort` 排序 | 不能按单量分层，核心诉求未满足 | P1 |
| 7 | L33-34 | `TYPE 'I'` + `STOP` | 后台作业误判为"成功无数据" | P1 |
| 8 | L30-31 | `VALUE #( FOR ... )` 冗余 | 新增字段易漏改 | P1 |
| 9 | L39-43 | 依赖 DDIC 文本，未验证中文标题 | 列标题可能显示字段名 | P1 |
| 10 | L51 | `get_sel_info` 无配套选择机制 | 死配置，误导后续维护者 | P1 |
| 11 | L6 | `ZMMR_VEND_S-PO_CNT` 类型未确认 | 若为 CHAR，ALV 合计/排序按字符串错排 | P1 |
| 12 | L21-27 | 无金额/日期维度 | 无法做商业价值分层 | P1 |
| 13 | L22-23 | `INNER JOIN` | 查不到零单供应商 | P1 |
| 14 | L52 | 无变式 / 标题 / 回调 | 无个性化、无下钻，报告"死胡同" | P1 |
| 15 | 全程序 | 逻辑不可单元测试 | 回归靠人工 | P2 |
| 16 | L4 | `TABLES` 仅作类型绑定 | 轻微误导 | P2 |

---

## 7. 改进建议

### 7.1 P0：必须修（最小改动版完整示例）

```abap
REPORT zmmr_vend_list.

TYPE-POOLS slis.

TABLES: lfa1, ekko.                          " 仅用于选择屏幕类型绑定

DATA: gt_out  TYPE TABLE OF zmmr_vend_s,
      gt_fcat TYPE slis_t_fieldcat_alv,
      gs_layo TYPE slis_layout_alv,
      gs_disvar TYPE slis_wa_variants.

SELECT-OPTIONS: s_lifnr FOR lfa1-lifnr,
                s_ekorg FOR ekko-ekorg,
                s_bedat FOR ekko-bedat.       " P0-4：可选，补一道性能闸门

INITIALIZATION.
  s_bedat-sign = 'I'.                        " 初始为空区间 = 不限制
  s_bedat-option = 'BT'.

START-OF-SELECTION.
  PERFORM check_input.                        " P0-4：非空才允许全量
  PERFORM get_data.                           " P0-2 / P0-3 / P0-5
  PERFORM build_fieldcat.
  PERFORM display_alv.                        " P1：排序 / 合计 / 变式 / 回调
```

**取数（修 P0-2 / P0-3 / P0-5）**

```abap
FORM get_data.
  " 第一步：按"供应商 + 采购组织 + 单号"去重，纠正跨组织同号被合并的问题
  SELECT b~lifnr, b~ekorg, b~ebeln
    FROM ekko AS b
    WHERE b~lifnr  IN @s_lifnr
      AND b~ekorg  IN @s_ekorg
      AND b~bedat  IN @s_bedat
      AND b~bstyp  = 'F'                     " 只统计采购订单
      AND b~loekz  = @space                   " 排除已删除单据
      AND b~bsngx  = @space                   " 排除系统自生成单
      AND a~block  = @space                   " 见下方 FOR ALL ENTRIES
      AND a~loekz  = @space
    GROUP BY b~lifnr, b~ekorg, b~ebeln
    INTO TABLE @DATA(lt_po).

  IF sy-subrc = 4.
    MESSAGE id 'ZMM' type 'S' number '001'.    " P0-1：消息类 + 文本符号
    LEAVE LIST-PROCESSING.                    " P1：不再 STOP，后台可见
    RETURN.
  ENDIF.

  " 第二步：已去重的组合键上直接计数 = 各供应商的"采购组织内去重单数"
  SELECT lifnr, COUNT(*) AS po_cnt
    FROM lt_po
    GROUP BY lifnr
    INTO TABLE @DATA(lt_cnt).

  IF lt_cnt IS INITIAL.
    MESSAGE id 'ZMM' type 'S' number '001'.
    LEAVE LIST-PROCESSING.
    RETURN.
  ENDIF.

  " 第三步：补供应商名称（1:1，用 FOR ALL ENTRIES，别把 LFA1 拖进分组）
  SELECT lifnr, name1
    FROM lfa1
    WHERE lifnr IN @s_lifnr
    FOR ALL ENTRIES IN lt_cnt
    INTO TABLE @DATA(lt_lfa).

  LOOP AT lt_lfa ASSIGNING FIELD-SYMBOL(<lfa>).
    MODIFY TABLE lt_cnt FROM VALUE #( ( lifnr = <lfa>-lifnr
                                       name1 = <lfa>-name1 ) )
      TRANSPORTING name1.
  ENDLOOP.

  " P1-8：一行替代 30-31 行的显式映射（按组件名对应，字段顺序无关）
  gt_out = CORRESPONDING #( lt_cnt ).
ENDFORM.
```

> 关于 `FOR ALL ENTRIES IN lt_cnt`：`lt_cnt` 在此之前已确保非空，FOR ALL ENTRIES 的空表禁区已满足；`MODIFY ... TRANSPORTING` 只更新 `NAME1`，避免覆盖已算好的 `PO_CNT`。

**输入校验（P0-4 / P0-5）**

```abap
FORM check_input.
  AUTHORITY-CHECK ON OBJECT 'V_VBAK_VKO'                       " 供应商主数据查看
    ID 'ACTVT' FIELD '03'.
  IF sy-subrc <> 0.
    MESSAGE id 'ZMM' type 'E' number '002'.
  ENDIF.

  IF s_lifnr[] IS INITIAL AND s_bedat[] IS INITIAL.
    MESSAGE id 'ZMM' type 'W' number '003'                     " 提醒 + 二次确认
      WITH '未限定供应商且未限定单据日期，将扫描全部采购订单'.
    " 交互式可加 CONFIRM / SUBMIT，后台应直接拒绝
  ENDIF.
ENDFORM.
```

**展示（修 P1）**

```abap
FORM display_alv.
  DATA: ls_sort TYPE slis_sortinfo_alv,
        ls_self TYPE slis_selinfo_alv.

  ls_sort-fieldname = 'PO_CNT'.   " 与 DDIC 组件名一致
  ls_sort-updown   = 'X'.         " 降序
  ls_sort-sor      = 'E'.         " 数值排序（字符型字段必须靠这个兜底）
  ls_self-selname  = 'SEL'.
  ls_self-selection_mode = 'A'.   " 行选择模式（SLIS 靠 IT_SELINFO，不在 LAYO 里）

  " 选择列：让 get_sel_info 真正生效
  APPEND VALUE #( fieldname = 'SEL'
                  seltext   = '选择'
                  just      = 'C'
                  checkbox  = 'X'
                  tech      = 'X' ) TO gt_fcat.

  " 技术字段不出现在屏幕上
  MODIFY gt_fcat FOR fieldname = 'PO_CNT'
    TRANSPORTING emphasize do_sum.               " 突出 + 可合计（需 DDIC 为数值型）
  MODIFY gt_fcat FOR fieldname = 'LIFNR'
    TRANSPORTING fixed key.

  gs_layo-zebra        = 'X'.
  gs_layo-get_sel_info = 'X'.
  gs_layo-box_sel_name = 'SEL'.                 " 与 checkbox 字段配套
  gs_layo-grid_title   = '供应商采购订单统计（按采购组织）'.   " 或 TEXT-001

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      is_layout             = gs_layo
      it_fieldcat           = gt_fcat
      it_sort               = VALUE #( ( ls_sort ) )
      it_selinfo            = VALUE #( ( ls_self ) )
      i_title               = '供应商采购订单统计'
      i_save                = 'A'                " 变式保存
      is_variant            = gs_disvar
      i_callback_user_command = 'USER_FCM'      " 行级下钻
      i_callback_data        = 'X'
    TABLES
      t_outtab              = gt_out.
ENDFORM.

FORM user_fcm USING r_ucomm    TYPE sy-ucomm
                  rs_selfield TYPE slis_selfield.

  DATA ls_vend TYPE zmmr_vend_s.

  CHECK r_ucomm = '&IC1' OR r_ucomm = 'IC1'.     " 双击/点击
  CHECK rs_selfield-tabrow > 0.
  READ TABLE gt_out INDEX rs_selfield-tabrow INTO ls_vend.
  IF sy-subrc <> 0.
    EXIT.
  ENDIF.

  SET PARAMETER ID 'BUK' FIELD ls_vend-lifnr.    " 记忆参数，按目标事务调整
  CALL TRANSACTION 'ME23N' AND CLEANUP.          " 跳该供应商的采购订单
ENDFORM.
```

### 7.2 P1：结构化重构（把"取数"从报表里搬出去）

报表保留为三行壳，取数与展示各自成为可单元测试的类：

```abap
REPORT zmmr_vend_list.
" 入口仅三步：参数 → Provider 取数 → ALV 类渲染
DATA: gs_sel TYPE zmms_sel_vendor_po,            " 选择条件结构
      gt_out TYPE TABLE OF zmmr_vend_s.

AT SELECTION-SCREEN.
  PERFORM fill_sel.

START-OF-SELECTION.
  TRY.
      DATA(go_provider) = NEW zcl_mmr_vendor_po( iv_sel = gs_sel ).
      gt_out = go_provider->get_vendor_po_counts( ).
    CATCH zcx_mmr_selection_incomplete INTO DATA(lx_err).
      MESSAGE lx_err->get_text( ) TYPE 'E'.
      RETURN.
  ENDTRY.

  NEW zcl_mmr_vend_list_alv( it_data = gt_out )->display( ).
```

好处：`zcl_mmr_vendor_po` 可以 ABAP Unit 测（可用接口抽象 + 真实小数据集断言 `po_cnt`）；权限/校验抽成异常类；`REUSE_ALV_*` 的 FM 细节不再污染报表。

### 7.3 P2：把聚合下推到 CDS（同时解决性能与复用）

```sql
@AbapCatalog.sqlViewName: 'ZIMMRVENDPOCNT'
@AbapCatalog.compiler.compareFilter: true
define view ZI_MMR_VEND_PO_CNT
  as select from lfa1 as a
    inner join   ekko as e
      on e.lifnr = a.lifnr
    {
      key a.lifnr              as lifnr,
      a.name1                  as name1,
      count( distinct e.ekorg && e.ebeln ) as po_cnt,   -- 组合键去重，HANA 支持
      sum( e.netwr )           as po_netwr,
      e.waers                   as waers,
      max( e.bedat )            as last_po_date
    }
    where e.bstyp = 'F'
      and e.loekz = ''
      and a.block = ''
    group by
      a.lifnr, a.name1, e.waers
```

报表退化为：

```abap
SELECT * FROM zi_mmr_vend_pocnt
  WHERE lifnr IN @s_lifnr
  ORDER BY po_cnt DESCENDING
  INTO TABLE @DATA(gt_out).
```

额外收益：该视图可被别的报表/Fiori/Analytics 复用；若走 HANA 还能进一步做成带主数据/聚合模型的 Cube 物化，冷启动变快；`sum(netwr)` 让"金额分层"这一缺失维度一次性补齐。

### 7.4 消息类落地

在事务 `SE91` 建消息类 `ZMM`：

| No | 文本 |
|---|---|
| 001 | 未找到符合条件的供应商，请调整选择条件 |
| 002 | 您没有查看供应商数据的权限 |
| 003 | 未限定供应商号与单据日期，将扫描 &1 条采购订单，请确认 |
| 004 | 字段目录生成失败（结构 &1），请联系系统管理员 |

代码中改为 `MESSAGE id 'ZMM' type 'S' number '001'`，标题用 `TEXT-001`（`SE63` 维护），彻底消除超长字面量并获得多语言能力。

### 7.5 其他建议速览

- `PO_CNT` 的 DDIC 用 `LVC_TOTCOUNT`（带计数器域的 CHAR10）或 `INT8`，并确认 ALV 列能合计；若坚持 `CHAR10`，务必配 `ls_sort-sor = 'E'`。
- 若业务确实要"零单供应商"，把 `INNER JOIN` 改成"先聚合 `EKKO` 再补 `LFA1`"，并对无单供应商填 0，另加"只看零单"的选择选项。
- 加 `i_salv_*`/OO 备选：若要拖拽式列汇总，可用 `CL_SALV_TABLE` + `set_aggregation( if_salv_aggregation=>EXPORT )` + `cl_salv_query`，约 30 行替代全部 `REUSE_ALV_*` 代码。
- 加 `INITIALIZATION` 里的变式默认值（`p_variant`）和 `SAVE` 逻辑，让每位用户记住自己的选择屏幕布局。

---

## 8. 验证与测试建议

| 层面 | 做法 |
|---|---|
| **编译/激活** | 先在 SE38 确认第 33/45 行 `MESSAGE` 字面量是否通过语法检查（这是 P0-1 的判据）。 |
| **数对不对** | `SE16` 手工核验：`SELECT COUNT(DISTINCT ebeln) FROM ekko WHERE lifnr = 'X' AND ekorg = 'Y' AND bstyp = 'F'`，再换用 `ekorg||ebeln` 组合键对比，两者差值即 P0-2 的错误量级。 |
| **性能** | `ST05` 看 SQL 执行时间与 `READ` 记录数；`ST12` 看 ABAP 侧耗时。留空范围跑一次就知道 P0-4 有多痛。 |
| **权限** | 用一个只授权了 `V_VBAK_VKO` 活动 03 但组织受限的业务用户跑，确认当前确实越权（P0-5）。 |
| **回归** | 把 `zcl_mmr_vendor_po` 抽出来后，用 ABAP Unit 造 3 组测试数据断言 `po_cnt`：① 跨组织同号单；② 含已删除单；③ 空结果。 |
| **跨报表对账** | 与 `ME21N`/`MB51` 采购订单清单按采购组织+供应商对账，确认口径差异都能解释。 |

---

## 9. 总结

**优点**：结构教科书级清晰；`@` Host 变量 + 聚合下推的取数写法现代且高效；用 `REUSE_ALV_FIELDCATALOG_MERGE` 让 DDIC 成为单一事实来源，列扩展零代码成本；`zebra` + Grid 版 FM 让基本可用性达标。

**主要欠账**：**统计口径**（跨采购组织去重、删除标记、全量扫描、缺金额/零单供应商）决定了这份报表当前**能不能用来支撑业务决策**；**健壮性**（`MESSAGE` 字面量不合规、无消息类、无权限校验、后台语义错误）决定它**会不会在生产上出事**；**可行动性**（无排序、无下钻、无变式）决定了业务**愿不愿意用第二次**。

按 §7.1 的最小改动版修完 P0，这张报表即可交付；再按 §7.2/§7.3 做结构化与 CDS 下沉，它就从"一张能跑的查询界面"变成"一个可复用、可测试、可扩展的采购分析资产"。
