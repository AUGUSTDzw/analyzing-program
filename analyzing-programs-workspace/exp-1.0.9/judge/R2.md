# 代码分析报告：`ZMRR_PERF_EVAL_VEND`

- **分析对象**：`D:\Workspace\Skills\analyzing-programs\Test-source\zvend.abap`
- **规模**：357 行（含空行与注释），1 个 REPORT、1 个全局类型/数据结构块、1 个本地类（5 个方法）、1 个 START-OF-SELECTION 事件块
- **技术栈**：ABAP OO（7.40 语法）+ SALV（`CL_SALV_TABLE` 及 Form Layout 系列）+ EKKO/EKPO/LFA1 聚合查询
- **分析日期**：2026-10-09
- **代码引用**：本报告所有 `引用` 均逐字取自源码，仅在必要时换行；`建议`/`说明` 段落为分析人员补充，非源码

---

## 0. 一句话结论

这是一个**能跑通 Demo、但无法支撑其名称所承诺的业务价值**的报表：代码以「对象化」为壳，实际是**五个重复的 `SELECT` + `MODIFY` 循环**；OO 结构是装饰性的（零属性、零抽象、全靠 ABAP 全局变量），业务口径在五个指标之间**互相不一致**，并且存在一条**必然导致运行时 dump 的错误路径**。

**严重问题 44 项**（P0 致命/数据错误 12、P1 性能与可用性 9、P2 设计与可维护性 17、P3 业务深度 6）。

---

## 1. 程序身份与业务目标重建

### 1.1 三套不一致的「自我命名」

| 载体 | 实际文本 | 暗示的业务 |
| --- | --- | --- |
| `REPORT` 名（第 1 行） | `zmmr_perf_eval_vend` | **Performance** Evaluation + **Vend**or |
| 类名（第 58 行） | `lcl_perf_eval` | Performance Evaluation |
| 页面标题（第 278 行） | `MM: Vendor Evaluation` | Vendor Evaluation（没有 Performance） |
| 列标题（第 222/229/234/241/248 行） | `RFQ Created` / `Quotation Maintained` / `PO Created` / `Cont. Created` / `Sch. Crea.` | 文档**创建笔数** |

**分析**：程序名承诺的是「供应商**绩效**评估」，实现产出的是「供应商**单据笔数统计**」。`Performance` 这个词在整个 357 行代码里没有任何对应的计算逻辑——没有评分、没有阈值、没有加权、没有等级。这是本报告最重要的一条业务级批判（见 §9.1 / F39、F40）。

### 1.2 推断的真实业务目标

从输出结构反推，开发者的意图大致是：

> 给采购经理一张表：每个供应商在指定日期区间内，创建了多少张询价单 / 多少张维持了报价 / 多少张采购订单 / 多少份合同 / 多少份计划协议，用于判断"该供应商的采购活动是否活跃 / 是否有框架协议"。

这个目标本身**不是没有价值**（例如用于识别"长期只走零星订单、无框架协议覆盖"的供应商），但它离「绩效评估」很远，而且当前实现连这个弱目标都**没有做完整**（见 §5、§9）。

### 1.3 使用者与典型使用姿势

选择屏幕只有两个字段（第 48–51 行）：

```abap
SELECTION-SCREEN BEGIN OF BLOCK b1 WITH FRAME TITLE TEXT- 001.
  SELECT-OPTIONS : s_lifnr FOR wa_disp- lifnr,
   s_bedat FOR wa_disp- bedat.
SELECTION-SCREEN END OF BLOCK b1.
```

推定的操作是：MM 经理进 `ZMMR_PERF_EVAL_VEND`，不填或填一个很宽的日期区间，回车，等一秒，看一屏数字。

**这正是本程序性能与正确性问题最容易暴露的场景**（无默认区间 → 全表聚合，见 §8）。

---

## 2. 结构地图

```
REPORT zmmr_perf_eval_vend
├── [全局] TYPES: t_disp / t_temp / t_lfa1                (5-22)   ← 输出结构 / 中间结构 / 名称结构
├── [全局] DATA: ABAP OO 句柄 + ls_color                    (25-38)  ← 类"私有"状态全在这里
├── [全局] DATA: it_disp / wa_disp / it_temp / wa_temp / it_lfa1 / wa_lfa1  (41-46)
├── [全局] SELECTION-SCREEN s_lifnr / s_bedat               (48-51)
├── [局部类] lcl_perf_eval                                 (58-348)
│   ├── constructor   (76-86)   → cl_salv_table=>factory，绑全局 it_disp；失败则 MESSAGE+EXIT
│   ├── fill_disp     (88-188)  → 5 个指标 SELECT + 名称 FOR ALL ENTRIES 回填 + SORT
│   ├── build_fc      (189-252) → 8 段 TRY/CATCH 设置列文本/颜色/可见性
│   ├── disp_alv      (254-270) → 编排 + set_all + striped + display
│   ├── set_tol       (271-327) → 构造 top-of-list（标题网格 + 右侧 logo）
│   └── end_of_page   (329-346) → 构造 footer（条目数）
└── START-OF-SELECTION                                      (351-357)
    ├── DATA obj_rep TYPE REF TO lcl_perf_eval
    ├── CREATE OBJECT : obj_rep
    ├── obj_rep->fill_disp( )
    └── obj_rep->disp_alv( )
```

### 2.1 执行流（正常路径）

```
START-OF-SELECTION
   └─ CREATE OBJECT obj_rep
        └─ constructor ─────────────────────► gr_table 绑定全局 it_disp
   └─ fill_disp
        ├─ SELECT #1 (bstyp='A')            ──► it_disp  [rfq]         ← 覆盖写
        ├─ SELECT #2 (bstyp='A', statu='A')  ──► it_temp  [CNT]        ─┐
        │    └─ LOOP: MODIFY it_disp (无 APPEND 分支) ★F04             │
        ├─ REFRESH it_temp                                                       │
        ├─ SELECT #3 (bstyp='F', bsart<>'UB')──► it_temp  [CNT]        ─┐
        │    └─ LOOP: MODIFY it_disp → 失败则 APPEND 新行               │
        ├─ REFRESH it_temp                                                       │
        ├─ SELECT #4 (bstyp='K')            ──► it_temp  [CNT]        ─┐
        │    └─ LOOP: MODIFY it_disp → 失败则 APPEND 新行               │
        ├─ REFRESH it_temp                                                       │
        ├─ SELECT #5 (bstyp='L')            ──► it_temp  [CNT]        ─┐
        │    └─ LOOP: MODIFY it_disp → 失败则 APPEND 新行               │
        └─ SELECT LFA1 FOR ALL ENTRIES      ──► it_lfa1                │
             └─ LOOP: READ + MODIFY name1 ; SORT it_disp BY lifnr
   └─ disp_alv
        ├─ set_tol       (建 lr_grid/lr_gridx/lr_logo)
        ├─ build_fc      (8 列格式)
        ├─ end_of_page   (建 lr_footer)
        └─ gr_table->display( )
```

**架构判断**：控制流完全线性、无分支、无循环嵌套——**这是一个纯过程程序**。`lcl_perf_eval` 的 5 个方法之间只通过**全局变量**耦合，类本身不含任何状态。若把它拉平写成 5 个 FORM，整个程序行数不会减少 10 行。OO 在这里是**语法糖而非设计**（详见 §10）。

---

## 3. 数据模型与 ALV 字段语义

```abap
TYPES:BEGIN OF t_disp,
   lifnr TYPE lifnr,
   name1 TYPE name1_gp,
   bedat TYPE bedat,
   rfq  TYPE I ,
   quot TYPE I ,
   po   TYPE I ,
   cont TYPE I ,
   sch  TYPE I ,
END OF t_disp,
```

| 字段 | 类型 | ALV 可见 | 实际填充来源 | 备注 |
| --- | --- | --- | --- | --- |
| `LIFNR` | `LIFNR` (CHAR10) | 是 | 全部 5 个 SELECT 的 `GROUP BY` | 唯一天然键（业务上） |
| `NAME1` | `NAME1_GP` (CHAR30) | 是 | `SELECT ... FROM LFA1 FOR ALL ENTRIES` | 需核实与 `LFA1-NAME1` 的类型兼容性（F44-adjacent，见 §11） |
| `BEDAT` | `BEDAT` (DATS) | **否**（`set_visible(abap_false)` + `set_technical`） | **从不填充，永远为空** | 只为选择屏幕而存在（F20） |
| `RFQ` | `I` | 是 | SELECT #1 | 计数 |
| `QUOT` | `I` | 是 | SELECT #2 | 计数 |
| `PO` | `I` | 是 | SELECT #3 | 计数 |
| `CONT` | `I` | 是 | SELECT #4 | 计数 |
| `SCH` | `I` | 是 | SELECT #5 | 计数 |

**关键观察 1**：5 个计数字段全部使用内建类型 `I`（4 字节内建整数）。在 SALV 中 `I` 会按 ALV 常规整数格式显示，功能上没问题；但对于**计数**这种天然 0/1/2 的量，`INT1`/`INT2` 才是语义正确的类型，并能显著降低 ALV 到界面传输的数据量。属于低危但确实存在的建模瑕疵。

**关键观察 2**：`bedat` 是一个**纯粹的选择屏幕载体**，被 `set_visible(abap_false)` 主动隐藏，同时在数据层永远为空。这是把「输入参数结构」和「输出展示结构」混成一个的典型症状（F20）。

**关键观察 3**：所有计数列没有设置 `set_align`、数字格式（`set_cell_layout` / `do_zae_database = 'X'`）、列宽、单位。SALV 的 `set_optimize`（第 194 行）会自动压缩列宽，在长供应商名（30 字符）场景下 5 个数字列会被挤到很窄。可用性问题。

---

## 4. `fill_disp` 逐步走读（核心逻辑）

### 4.1 RFQ（第 89–96 行）

```abap
"RFQ
SELECT a~lifnr COUNT( DISTINCT a~ebeln ) AS rfq FROM ekko AS a
JOIN ekpo AS b ON a~ ebeln = b ~ebeln
INTO CORRESPONDING FIELDS OF TABLE it_disp
WHERE a~lifnr IN s_lifnr AND bedat IN s_bedat
AND b~loekz NE 'X'
AND a~bstyp = 'A'
GROUP BY a~lifnr .
```

- 语义：`DCL='A'`（询价单）中，存在**至少一个未删除行项目**的凭证数。
- `INTO CORRESPONDING FIELDS OF TABLE`（**覆盖写**）——因为是第一个查询，语义正确。
- `COUNT(DISTINCT)` 修掉了 JOIN 引入的行项目膨胀，正确。
- **但删除标识用的是 `b~loekz NE 'X'`**，而后面三个指标用 `b~loekz EQ space`。见 F06。

### 4.2 QUOT（第 99–112 行）

```abap
"Quot
SELECT lifnr COUNT( DISTINCT ebeln ) AS CNT FROM ekko
APPENDING CORRESPONDING FIELDS OF TABLE it_temp
WHERE lifnr IN s_lifnr AND bedat IN s_bedat
AND loekz EQ space
AND ( bstyp = 'A' AND statu = 'A' )
GROUP BY lifnr.
```

- **注意**：这里的 `loekz` 写的是**未限定表别名**的 `loekz`，而查询 `FROM ekko`（**没有 JOIN ekpo**）。若 `EKKO` 没有 `LOEKZ` 字段则无法通过激活——但程序显然能跑，因此 `EKKO` 应当存在同名字段。**需核实：`EKKO` 是否真有 `LOEKZ`，以及它与 `EKPO-LOEKZ` 语义是否相同**（`EKKO-LOEKZ` 若是"凭证级删除标识"，则本处是凭证级过滤，与其他三个指标的行级过滤**根本不是同一个粒度**，问题比 F05/F06 严重得多）。
- 更要命的是：`statu` 字段同样未限定别名，且无注释（F44）。
- **结构性缺陷**：这个循环**没有 `IF sy-subrc` / `APPEND` 分支**（对比 4.3）。见 F04。

### 4.3 PO（第 114–132 行）

```abap
" PO
REFRESH it_temp.
SELECT lifnr COUNT( DISTINCT a~ ebeln ) AS CNT FROM ekko AS a JOIN ekpo AS b ON a~ ebeln = b ~ebeln
APPENDING CORRESPONDING FIELDS OF TABLE it_temp
WHERE lifnr IN s_lifnr AND bedat IN s_bedat
AND b~loekz EQ space
AND bsart NE 'UB'
AND ( a~ bstyp = 'F' )
GROUP BY lifnr.

LOOP AT it_temp INTO wa_temp .
   wa_disp- lifnr = wa_temp -lifnr.
   wa_disp- po = wa_temp -CNT.
  MODIFY it_disp FROM wa_disp TRANSPORTING lifnr po WHERE lifnr = wa_temp-lifnr .
  IF sy-subrc NE 0.
    APPEND wa_disp TO it_disp .
  ENDIF .
  CLEAR : wa_disp, wa_temp.
ENDLOOP .
```

- `bsart NE 'UB'`：**没有任何注释**说明为什么要排除 `UB`。见 F08。
- `MODIFY ... TRANSPORTING` 后判 `sy-subrc`，失败则 `APPEND` 新行——这是**补齐 UNION 语义**的正确做法，PO/CONT/SCH 三段都有。QUOT 段没有。F04 的根因就在这里。

### 4.4 CONT / SCH（第 134–170 行）

结构与 4.3 完全相同，只有 `a~ bstyp = 'K'` / `= 'L'` 之别。**三段是 15 行 × 3 的复制粘贴**。

### 4.5 名称回填（第 172–183 行）

```abap
SELECT lifnr name1 FROM lfa1
INTO CORRESPONDING FIELDS OF TABLE it_lfa1
FOR ALL ENTRIES IN it_disp
WHERE lifnr = it_disp -lifnr.

LOOP AT it_disp INTO wa_disp .
  READ TABLE it_lfa1 INTO wa_lfa1 WITH KEY lifnr = wa_disp-lifnr .
  IF sy-subrc EQ 0.
     wa_disp- name1 = wa_lfa1 -name1.
    MODIFY it_disp FROM wa_disp TRANSPORTING lifnr name1 WHERE lifnr = wa_disp- lifnr .
  ENDIF .
ENDLOOP .
```

- `FOR ALL ENTRIES` 用法本身正确（驱动表 `it_disp` 在 SELECT 前已非空或为空——为空时返回空结果集，不报错但也不报错，符合预期）。
- 性能上是 O(n×m) 的线性查找（F16）。
- 在 `LOOP AT it_disp` 内对同一张表 `MODIFY`——技术上合法（不改变行数与键结构），但 ATC 会告警，可读性也差。

### 4.6 排序

```abap
SORT it_disp BY lifnr .
```

排序放在最后是正确的（避免 `MODIFY ... WHERE` 因排序失效而全表扫描）。**但程序从未调用 `gr_table->set_key( 'LIFNR' )`**，SALV 的初始显示顺序依赖内表顺序而不是 key——这一点恰好与排序配合正确，属于"碰巧对"（F42-adjacent）。

---

## 5. 核心批判：五个指标的口径矩阵

这是全程序最值得业务方关注的部分。把 5 个 SELECT 的过滤条件摊平对比：

| 指标 | DCL (`BSTYP`) | 行项目删除过滤 | 其他状态过滤 | `BSART` 过滤 | 是否补 `APPEND` |
| --- | --- | --- | --- | --- | --- |
| `RFQ` | `'A'` | `b~loekz NE 'X'` | — | — | 不适用（基准集） |
| `QUOT` | `'A'` | `loekz EQ space`（**表别名缺失，粒度存疑**） | `statu = 'A'` | — | **否** ★ |
| `PO` | `'F'` | `b~loekz EQ space` | — | `bsart NE 'UB'` | 是 |
| `CONT` | `'K'` | `b~loekz EQ space` | — | — | 是 |
| `SCH` | `'L'` | `b~loekz EQ space` | — | — | 是 |

**结论：五个数字被并排放在同一张表里，暗示它们可比、可加总、可画趋势。实际上它们的定义各不相同。**

具体后果：

1. **行集合取决于哪个指标先"命中"供应商**（F04）。设某供应商 X 只有报价、没有任何询价单：SELECT #2 返回 X，循环里 `MODIFY` 在 `it_disp`（此时只含 SELECT #1 命中的供应商）中找不到 X，`sy-subrc ≠ 0`，**但代码什么都不做**——X 被丢弃。设供应商 Y 只有合同没有询价单：SELECT #4 循环会 `APPEND` 它，Y 出现在结果里。**同一个报表，一类供应商看得到、另一类看不到，取决于任意一个指标的命中顺序**。这是本程序最严重的数据正确性缺陷之一。

2. **`RFQ` 与 `QUOT` 都是 `BSTYP='A'` 的同一批凭证**，两者唯一的差别是 `loekz` 的写法和一个未加注释的 `statu`（F07）。在 SAP 中，**供应商的正式报价（Vendor Quotation）本身就是 `DCL='A'` 的一张单据**——也就是说询价单和报价单在数据模型里是同一种对象，"是否已有供应商报价"通常靠**单据来源 / 伙伴角色 / `MEMORY` 标志 / `BSTYP` 的细分**来区分，而不是靠一个 `STatu`。当前实现把同一类对象拆成两列并用一个来路不明的状态位区分，**几乎可以肯定是错维度的**。需业务澄清。

3. **`bsart NE 'UB'` 让 PO 计数静默偏低**（F08）。`BSART='UB'` 是分包采购订单的订单类型，排除它意味着"该供应商的分包订单笔数"完全不体现在报表里，而界面上没有任何提示。用户看到 PO=3 无法知道"实际有 5 张，其中 2 张是分包"。

4. **`loekz NE 'X'` vs `EQ space`**（F06）。若 `LOEKZ` 的值域只有 `' '` 与 `'X'`，两者功能等价，问题只是可读性；一旦值域扩展（例如出现删除标记 `'D'`），`RFQ` 列会**立刻变成错的**。当前写法把一个隐式契约写死了。

---

## 6. OO 封装评估：类里没有类

### 6.1 零属性

```abap
CLASS lcl_perf_eval DEFINITION .
  PUBLIC SECTION.
  METHODS: constructor ,
   fill_disp.
  METHODS build_fc.
  METHODS disp_alv.
  METHODS set_tol.
  METHODS end_of_page.
ENDCLASS.                   "lcl_perf_eval DEFINITION
```

`DEFINITION` 段里**没有 `DATA` / `CLASS-DATA` / `METHODS ... RETURNING` / 接口**。这个类的全部状态在第 25–46 行的报告级 `DATA` 里：

```abap
DATA: "it_layout   TYPE lvc_s_layo,
       gr_table TYPE REF TO cl_salv_table,
       gr_functions TYPE REF TO cl_salv_functions,
       ...
```

**后果**：

- **不可单元测试**。`fill_disp` 直接读全局 `s_lifnr` / `s_bedat` 并写全局 `it_disp`，测试时无法注入数据、无法断言结果。
- **不可复用**。想做一个"按供应商清单导出"的变体，只能复制整个报表。
- **并发/嵌套不可用**。同一个程序内不能同时跑两个实例。
- **构造器名不副实**：`constructor` 只做了一件事——把 SALV 绑到全局表。

### 6.2 构造器的失败路径是致命的（F01 / F02 / F03）

```abap
METHOD constructor.
  TRY.
     cl_salv_table=> factory( IMPORTING r_salv_table = gr_table CHANGING t_table = it_disp ). "Calling Factory Obj of Cl_ALV_TABLE
  CATCH cx_salv_msg.
  ENDTRY .

  IF gr_table IS INITIAL .
    MESSAGE TEXT -002 TYPE 'I' DISPLAY LIKE 'E'.
    EXIT .
  ENDIF .
ENDMETHOD.                   "constructor
```

问题有三层：

1. **`CATCH cx_salv_msg.` 是空处理**。异常被吞掉，`gr_table` 保持初始值——**失败原因永久丢失**，日志里什么都没有（F03）。
2. **`EXIT` 只跳出构造器**。ABAP 中 `EXIT` 在方法里就是 `RETURN`，控制权回到 `START-OF-SELECTION` 的下一行，程序**不会终止**（F02）。
3. **调用方不检查任何返回值**：

```abap
CREATE OBJECT : obj_rep. " Creating Object

obj_rep->fill_disp( ). " Calling class Methods
obj_rep->disp_alv( ).
```

于是必然执行到 `disp_alv( )` → `build_fc( )` → 第 193 行：

```abap
gr_columns = gr_table->get_columns ( ).
```

`gr_table` 为初始引用 → 抛出 **`CX_SY_REF_IS_INITIAL`** → 第一个 `TRY` 只捕获 `cx_salv_not_found`，捕获不到 → 逃逸出 `disp_alv` → **运行时错误 / 短转储**（F01）。

**即：构造失败时，用户不会看到"初始化失败"的友好提示，而是看到一个莫名其妙的 dump。** 讽刺的是，代码里那句 `MESSAGE TEXT -002` 就是想给友好提示的，但控制流设计让它永远走不到。

**正确写法**（示意）：

```abap
" 方案 A：加 OUTGOING 参数
METHODS constructor IMPORTING iv_source TYPE REF TO cl_salv_table
                 RETURNING VALUE(rv_ok) TYPE abap_bool.

" 方案 B（更 OO）：工厂 + 异常
METHOD fill_disp.
  TRY.
      cl_salv_table=>factory( IMPORTING r_salv_table = gr_table
                              CHANGING  t_table = it_disp ).
    CATCH cx_salv_error ##NEEDED.
      RAISING.
  ENDTRY.
ENDMETHOD.
```

### 6.3 可见性（F24）

5 个方法全部 `PUBLIC`，但外部只调用 `fill_disp`（第 356 行）与 `disp_alv`（第 357 行）；`constructor` 由 `CREATE OBJECT` 隐式调用。**`build_fc` / `set_tol` / `end_of_page` 是纯内部步骤，却被暴露为公共 API**——任何外部调用者都可以在 ALV 已 display 之后调用它们，产生不可预期的副作用。

### 6.4 命名（F25 / F26）

| 现有命名 | 问题 | 建议 |
| --- | --- | --- |
| `set_tol` | 读起来像 "set tolerance"（容差）；实际是"设置 top of list" | `build_top_of_list` |
| `end_of_page` | SALV 没有"页尾分页"概念；实际是构建 footer | `build_footer` |
| `lcl_perf_eval` vs `..._vend` vs `MM: Vendor Evaluation` | 同一对象三套名字 | 统一为 `lcl_vendor_doc_count` 之类**与实际功能一致**的名字 |

`set_tol` 还暴露了一个设计问题：它同时**创建对象**（`lr_grid` / `lr_logo`）并**写全局句柄**，返回 `void`。副作用隐藏在方法名后面。

---

## 7. 构造器绑定全局表的后果（F23）

```abap
cl_salv_table=> factory( IMPORTING r_salv_table = gr_table CHANGING t_table = it_disp ).
```

`CHANGING t_table` 要求 `IT_DISP` 是**全局静态变量**（不能是方法局部变量）。这条 API 约束直接反推出了整个设计：数据必须住在全局，类才拿得到。

**后果链**：全局表 → 零属性类 → 不可测 → 不可复用。同时 `gr_table` 在整个程序生命周期内持有 `it_disp` 的引用，意味着**一旦 `display( )` 之后任何地方修改 `it_disp`，ALV 不会自动刷新**。当前流程恰好在 display 前完成所有写入，属于"碰巧安全"。

---

## 8. 性能剖析

### 8.1 五个全表聚合 + 一个 FOR ALL ENTRIES

| 查询 | 表 | JOIN | 聚合 | 默认参数下的代价 |
| --- | --- | --- | --- | --- |
| #1 RFQ | EKKO | EKPO | `COUNT(DISTINCT ebeln)` | EKKO×EKPO 全量（数千万行级别） |
| #2 QUOT | EKKO | — | `COUNT(DISTINCT ebeln)` | EKKO 全量 |
| #3 PO | EKKO | EKPO | `COUNT(DISTINCT ebeln)` | EKKO×EKPO 全量 |
| #4 CONT | EKKO | EKPO | `COUNT(DISTINCT ebeln)` | EKKO×EKPO 全量 |
| #5 SCH | EKKO | EKPO | `COUNT(DISTINCT ebeln)` | EKKO×EKPO 全量 |
| #6 名称 | LFA1 | FAE | — | 供应商数 × 索引查找 |

**F13（严重）**：`s_bedat` 无默认值、无必输校验。用户直接回车 = **5 次全量 `COUNT(DISTINCT)` 聚合 + 4 次 EKPO JOIN**。`COUNT(DISTINCT)` 强制数据库在每个 `LIFNR` 分组内做去重排序/散列，是聚合里最贵的形态之一。在生产 EKKO 有 5000 万行的系统上，这很可能是**分钟级**甚至直接 `SYSTEM`/超时终止。

**F14（结构性）**：五个查询**扫的是同一批行**。正确做法是一次条件聚合：

```abap
SELECT a~lifnr
       COUNT( DISTINCT CASE WHEN a~bstyp = 'A' AND b~loekz = 'X'  THEN a~ebeln END ) AS rfq
       ...
  FROM ekko AS a JOIN ekpo AS b ON a~ebeln = b~ebeln
 WHERE a~lifnr IN s_lifnr
   AND a~bedat IN s_bedat
 GROUP BY a~lifnr
```

一次扫描、五列条件聚合。**代价从 5× 降到 1×，且口径差异被集中到一个地方，可审计、可维护。**

### 8.2 内存中的 O(n·m)

**F15**：5 段 `LOOP AT it_temp` 中各执行一次 `MODIFY it_disp FROM wa_disp ... WHERE lifnr = ...`——ABAP 内表无索引，`MODIFY ... WHERE` 是线性扫描。5 × n × m。若 n = m = 50,000，即 125 亿次行比较。

**F16**：`LOOP AT it_disp` 内 `READ TABLE it_lfa1 WITH KEY` + `MODIFY it_disp ... WHERE`，再叠加一层 O(n·m)。

**改进**：把名称合并进主查询（LFA1 JOIN，或对 `it_lfa1` 先 `SORT lifnr`，用带 key 的内表）；把指标合并进单次聚合（8.1）。ABAP 侧全部消失。

### 8.3 缺失的防护

无 `PACKAGE SIZE`、无二次进入保护、无 SQL 性能跟踪、无超时处理。报表若被后台或高频执行，无任何自我保护。

---

## 9. 业务深度批判

### 9.1 名不副实（F39 / F40）

名为 "Performance Evaluation"，输出只有 5 个**文档笔数**。没有：

- **金额**（采购额、订单金额、已付金额）——无法区分"10 张 10 万的 PO"和"500 张 200 元的 PO"
- **交期**（计划交货 vs 实际交货、按期交付率）——供应商绩效的核心指标之一
- **质量**（退货率、拒收率、检验不合格批次）
- **价格**（价格偏差、与框架价的偏离）
- **服务**（交货及时性、问题响应、单据完整性）
- **评分逻辑**（没有加权、没有阈值、没有等级、没有趋势）

**批判**：当前输出的唯一可解读信息是"这个供应商在指定时间窗内被创建了几张各类单据"。**这衡量的是"采购员的下单行为"，不是"供应商的绩效"。** 用这张表给供应商评级，业务方一定会误用——而报表的命名（`PERF_EVAL`、页面标题）恰恰在鼓励这种误用。

### 9.2 计数不等于绩效（F41）

即便退一步接受"只比笔数"，这个指标仍然是**结构性有偏**的：

- 未区分单据是否**已审批/已过账**。刚创建就被作废的询价单照样计数。
- 未区分是否**已收货**。开了不执行的订单同样计数。
- 计划协议（`SCH`）一张可以挂几百个订单行，`PO` 一张可以只有一行。**"笔数"在跨文档类型之间根本不同量纲。** 把 `RFQ=5 / PO=20 / SCH=1` 放在一行上比较，没有任何意义。
- 未按**时间归一化**（F42）：一个 2019 年就停止合作的老供应商和一个本月新建的供应商，窗口选择不同时计数天差地别。
- 未按**供应商规模**归一化：大型总包供应商天然比小型专精供应商单据多。

### 9.3 一个值得肯定的设计意图

程序确实有几处**体现了业务思考**的地方，作者显然不是随手写的：

- 用 `COUNT(DISTINCT ebeln)` 而不是 `COUNT(*)`——正确避免了 JOIN 导致的行项目膨胀（F: 正确，应保留并在注释中固化）。
- 选择"补 `APPEND` 分支"来实现 UNION 语义（PO/CONT/SCH 三段）——思路正确，只是 QUOT 段漏了。
- `SORT it_disp BY lifnr` 放在所有 `MODIFY ... WHERE` **之后**——避免了排序导致 `MODIFY` 全表扫描。
- `FOR ALL ENTRIES` 用在 LFA1 而不是主查询——至少考虑了主查询的性能。

**但这些优点都是"局部正确、整体失焦"**：正确的细节拼出了一个语义不成立的整体。

---

## 10. ALV 与前端呈现评估

### 10.1 空 CATCH 导致静默降级（F27）

```abap
TRY.
   gr_column ?= gr_columns-> get_column( 'LIFNR' ).
   ls_color- col = 3 .
   gr_column-> set_color( ls_color ).
CATCH cx_salv_not_found.
ENDTRY .
```

8 段完全相同的结构（LIFNR / NAME1 / BEDAT / RFQ / QUOT / PO / CONT / SCH）。问题：

- 列是通过**硬编码的 3 字符技术名**（即 `T_DISP` 的字段名）查找的。
- 任何人重命名 `t_disp-po` 为 `t_poid`（很自然的一次重构），**程序不会报错**，8 个 `CATCH` 全部静默吞掉 `cx_salv_not_found`，ALV 变成全默认表头、无颜色、`BEDAT` 重新可见。**这是一条无声的回归路径。**
- `?=`（对象引用带初始值赋值）在 `get_column` 上是多余的——该方法**抛异常**而不是返回初始值，`?=` 与 `=` 在这里行为相同。这个写法传递了一个错误的信号（以为它可能返回初始值）。

**改进**：把 8 段压成一个循环 + 一个结构化定义表，并把异常处理改成"至少 `WRITE` 一条诊断信息"或累积错误标志在 `disp_alv` 统一 `MESSAGE`。

### 10.2 布局构造中的魔法值（F28）

```abap
lr_label = lr_gridx->create_label ( row = 2 column = 1
TEXT = 'Vendor No # :' tooltip = 'Vendor #.' ).
```

第 316–319 行有 4 行连续的空 label：

```abap
lr_label = lr_gridx->create_label ( row = 5 column = 1 ).
lr_label = lr_gridx->create_label ( row = 6 column = 1 ).
lr_label = lr_gridx->create_label ( row = 7 column = 1 ).
lr_label = lr_gridx->create_label ( row = 8 column = 1 ).
```

**这 4 个空的 label 是为了让 logo 区域有垂直空间而硬凑的"占位符"，但源码里没有任何一行注释说明这一点。** 任何一个后来的维护者删掉它们，都会得到一个"莫名其妙挤在一起"的页面，且完全不知道为什么。

### 10.3 页脚数字会显示前导零（F09）

```abap
DATA :lf_lines TYPE sy-tfill .
...
lf_lines = LINES( it_disp ).
...
lf_flow-> create_text( TEXT = 'Total Number of Entries' );
lf_flow = lr_footer->create_flow ( row = 2 column = 2 ).
lf_flow-> create_text( TEXT = lf_lines );
```

`create_text` 的 `TEXT` 参数是 `string`。把**内建类型** `sy-tfill`（`TYPE I`，长度 4）隐式转换成 `string` 时，ABAP 使用内建表示，**左填充零**。因此页脚会显示：

```
Total Number of Entries   0042
```

而不是 `42`。

**修法**（任选一）：

```abap
lf_flow->create_text( TEXT = |{ lf_lines }| ).
" 或
DATA lv_lines_txt TYPE string.
lv_lines_txt = CONV string( lf_lines ).
```

同样的模式还出现在 `lv_text TYPE C LENGTH 10`（第 273 行）——它只被用来承接 `WRITE` 的输出，纯粹是权宜之计。

### 10.4 硬编码资源（F29）

```abap
lr_logo-> set_right_logo( 'ZCHEM_N_LOGO_SMALL' ). " Image From OAER T.code
```

- `ZCHEM_...` 是一个**客户自定义的图形资源名**，依赖 OAER/CSOMGET 传输到目标系统。
- 跨 client、跨系统（新系统 QAS→PRD、或上云的 Steampunk 迁移）时**极可能缺失**，导致空白 logo 或 `S240` 类运行时错误。
- 图形名硬编码，无配置点，无 fallback。
- 注释 `" Image From OAER T.code` 只说明了来源，没说明**依赖**——依赖信息写在了注释里而不是被设计隔离掉。

### 10.5 功能全开（F41-adjacent）

```abap
gr_functions = gr_table-> get_functions ( ).
gr_functions-> set_all( abap_true ).
```

`set_all( abap_true )` 一次性打开 SALV 的**全部**标准功能，包括**打印**（Print to spooler）。在一个可能返回 5 万行、且每次都做重聚合的报表上，默认允许打印意味着随时可能产生一个几百 MB 的假脱机作业。

**改进**：

```abap
gr_functions->set_all( abap_false ).
gr_functions->set_standard( abap_true ).
gr_functions->set_sort( abap_true ).
gr_functions->set_filter( abap_true ).
gr_functions->set_totals( abap_true ).
" 明确不打开 print / 不需要的 export
```

### 10.6 缺失的 ALV 能力

| 缺失 | 后果 |
| --- | --- |
| `gr_table->get_layout_settings( )->set_key( 'ZALV_VEND' )` + `set_default_layout` | 每个用户每次都要重新排序/筛选/调列（F17） |
| `set_key( 'LIFNR' )` | 排序行为不受 ALV 管理，仅靠内表顺序"碰巧"正确 |
| `set_default_sort` | 同上 |
| `set_striped_pattern` 有，但无 `set_no_header` / 无 `set_header_text` | 标题散落在 layout 里，不在 SALV header 中 |
| 空结果提示 | 查无数据时得到一个完全空白的 ALV，用户无法区分"程序坏了"和"确实没数据"（F18） |
| `bedat` 的 F4（`LFA1` 供应商搜索帮助） | 用户必须手敲 10 位供应商号（F19） |
| 日期区间必输 + 默认期间 | 性能灾难的入口（F13） |
| `AT SELECTION-SCREEN ON VALUE-REQUEST FOR s_lifnr` | 见上 |

---

## 11. 需求侧确认清单（⚠️ 需核实）

以下项目**我不下结论**，需要在目标系统上确认：

| # | 待核实项 | 怎么核实 | 若为真的后果 |
| --- | --- | --- | --- |
| 1 | **`INCLUDE <color>.`（第 191 行）出现在 METHOD 实现体内是否合法？** | 在目标系统上激活；或 SE38 → 语法检查 | 若 `<COLOR>` 含可执行语句 → **语法错误**；若只含 `TYPES`/`CONSTANTS`（ABAP 允许方法开头做局部声明）→ 合法，但是**完全无用的死代码**（程序只用到 `cl_salv_display_settings=>true` 这个类常量，不需要任何 include）。两种情况下都应删除。 |
| 2 | **`WRITE s_bedat-low DD/MM/YYYY TO lv_text .`（第 299/301 行）在类方法中是否允许？** | 激活验证 | ABAP 对方法体内可用语句有限制列表。若不允许 → **语法错误**；若允许 → 仍应重写为 `\|{ s_bedat-low DATE = USER }\|`，因为 `WRITE ... TO` 是过时特性，且其输出对齐方式（左对齐带尾随空格 / 右对齐）需要确认，会直接污染后面传给 `create_text(TEXT = lv_text)` 的字符串与 tooltip。 |
| 3 | **`EKKO` 是否存在 `LOEKZ` 和 `STATU` 字段？** | SE11 → EKKO | 第 102 行的 `loekz` 与第 104 行的 `statu` 都未限定表别名且 `FROM ekko` 无 JOIN。若 `EKKO-LOEKZ` 是**凭证级**删除标识（而非行级），则 QUOT 指标与 PO/CONT/SCH 的**过滤粒度根本不同**——这比 §5 描述的还要严重。 |
| 4 | **`STATU` 的值域与业务含义？** | SE11 / F1 | `statu = 'A'` 被用来把 `BSTYP='A'` 的单据拆成"RFQ"和"Quotation"两列。在 SAP 中供应商报价本身就是 `DCL='A'` 的单据，通常靠单据来源/伙伴角色区分。**需向业务确认这个 `STATU='A'` 到底代表什么**，否则 QUOT 列很可能是错的。 |
| 5 | **`T_DISP-NAME1` 用 `NAME1_GP` 是否与 `LFA1-NAME1` 的数据元素/长度完全兼容？** | SE11 → `LFA1-NAME1` | `INTO CORRESPONDING FIELDS` 只按**字段名**匹配，不校验类型。若长度不同 → 运行期转换错误或静默截断。 |
| 6 | **`BSART='UB'` 为什么被排除？** | 业务/需求方 | 排除分包订单会**静默压低** PO 计数，界面无任何提示。若是刻意为之（例如分包走另一张报表），应写进注释并考虑加一列或加提示。 |
| 7 | **文本符号 `TEXT-001` / `TEXT-002` 在哪里定义？** | SE63 / SE38 → Goto → Text elements | 源码中**没有** `TEXT-xxx` 定义段。两者必须在文本元素中维护。未随报表传输、或文本元素被误删 → **短转储**（"消息 002 未找到"）。同时它们未经翻译（无 `T: 文本` 段）。 |
| 8 | **`CREATE OBJECT : obj_rep.`（第 354 行）的冒号语法是否合法？** | 激活验证 | 只有 1 个对象时冒号是多余的。需确认在目标 release 上是否被接受。 |
| 9 | **本程序的调用场景？**（对话框 / 只能前台 / 有无后台变式） | 需求方 | 若被后台或高频调度，F13/F17 的影响会被放大数倍。 |

---

## 12. 问题清单（44 项）

### P0 — 会导致 dump 或数据错误（12 项）

| ID | 位置 | 问题 | 影响 |
| --- | --- | --- | --- |
| **F01** | 82-85 → 193 | `gr_table` 为初始时，`build_fc` 的 `gr_columns = gr_table->get_columns ( )` 抛 `CX_SY_REF_IS_INITIAL`，而 `TRY` 只捕 `cx_salv_not_found` | **运行时短转储**（构造失败路径必然 dump） |
| **F02** | 84 | 构造器里 `EXIT .` 只 `RETURN` 构造器，**不终止程序**，调用方无从得知失败 | 错误被吞，执行流继续往下走 |
| **F03** | 79-80 | `CATCH cx_salv_msg.` **空处理**，异常原因永久丢失 | 现场无任何可诊断信息 |
| **F04** | 107-112 | QUOT 循环**缺 `IF sy-subrc` / `APPEND` 分支**（对比 128-130） | **"只有报价、没有询价单"的供应商整行从结果中消失**；行集合取决于指标命中顺序 |
| **F05** | 100-105 | QUOT 无行项目删除过滤（`FROM ekko` 无 JOIN ekpo） | 与 PO/CONT/SCH 口径不一致，QUOT 可能包含已删除行项目 |
| **F06** | 94 vs 119/139/158 | `b~loekz NE 'X'` vs `b~loekz EQ space` | 功能上可能等价，但把"值域只有 ' ' 和 'X'"的隐式契约写死；值域一变 RFQ 列立刻出错 |
| **F07** | 90-96 vs 100-105 | RFQ 与 QUOT **都是 `BSTYP='A'`**，仅靠未注释的 `statu` 区分 | 极可能是**错维度**（SAP 中供应商报价本身即 `DCL='A'`），QUOT 列语义存疑 |
| **F08** | 120 | `bsart NE 'UB'` 无任何注释，静默剔除分包订单 | PO 列偏低且**不可解释**，用户无法察觉 |
| **F09** | 331, 344 | `sy-tfill`（`TYPE I`）隐式转 `string` 会**左填充零**，页脚显示 `0042` | UI 缺陷 |
| **F10** | 299, 301 | 类方法内 `WRITE ... TO`（⚠️ 需核实是否允许）；输出格式过时、对齐/尾随空格不确定 | 标题与 tooltip 文本污染；⚠️ 可能是语法错误 |
| **F11** | 191 | `INCLUDE <color>.` 出现在 METHOD 内（⚠️ 需核实）；且程序只用到 `cl_salv_display_settings=>true`，**完全不需要它** | 死代码 / ⚠️ 可能是语法错误 |
| **F12** | 297 | 页面标签写 `'Posting Date:'`，但 `BEDAT` 是**凭证创建日期** | 术语错误，用户对时间口径产生误解 |

### P1 — 性能与可用性（9 项）

| ID | 位置 | 问题 | 影响 |
| --- | --- | --- | --- |
| **F13** | 48-51 | `s_bedat` 无默认值、无必输校验 | 不填日期 → **5 次全量 `COUNT(DISTINCT)` 聚合 + 4 次 EKPO JOIN**，分钟级 |
| **F14** | 90-160 | 5 个 SELECT 扫同一批行 | 应合并为**单次条件聚合**；代价可降 5×，口径集中可审计 |
| **F15** | 110, 127, 146, 165 | `LOOP` 内 `MODIFY it_disp ... WHERE`（线性扫描） | ABAP 侧 O(n·m)，50k 供应商量级不可接受 |
| **F16** | 177-183 | `LOOP AT it_disp` 内 `READ TABLE` + `MODIFY` 同一张表 | O(n·m)；ATC 告警；可读性差 |
| **F17** | 268 | 从未设置 ALV layout key / 默认布局 / 初始排序 | 用户布局不持久化，每次重排 |
| **F18** | 356-357 | 空结果时无任何提示，直接 display 一个空 ALV | 用户无法区分"程序坏了"和"确实没数据" |
| **F19** | 48-51 | `s_lifnr` 无 F4 搜索帮助（可挂 `LFA1` 供应商搜索帮助） | 用户必须手敲 10 位供应商号 |
| **F20** | 8, 213-217 | `bedat` 字段在数据层**永远为空**（5 个 SELECT 都不填它），却被用作选择屏幕载体、并被 `set_visible(abap_false)` 隐藏 | 输入结构与展示结构混为一体；ABAP 侧没有"选择条件"概念 |
| **F21** | 全程序 | 无任何 `AUTHORITY-CHECK` | 供应商主数据与采购额信息对所有有事务权限的人全开 |

### P2 — OO 设计与可维护性（17 项）

| ID | 位置 | 问题 | 影响 |
| --- | --- | --- | --- |
| **F22** | 58-67 + 25-46 | 类**零属性**，全部状态住在报告级 `DATA` | 不可单元测试、不可复用、不可多实例 |
| **F23** | 78 | 构造器用 `CHANGING t_table = it_disp` 把 SALV **绑死全局表** | 被 SALV API 反推出"数据必须在全局"这一错误设计；display 后改 `it_disp` 不刷新 |
| **F24** | 59-65 | 5 个方法全 `PUBLIC`，但外部只调 `fill_disp` / `disp_alv` | `build_fc` / `set_tol` / `end_of_page` 是纯内部步骤却被暴露 |
| **F25** | 1, 58, 278 | 三套名字：`zmmr_perf_eval_vend` / `lcl_perf_eval` / `MM: Vendor Evaluation` | 同一对象三种称呼，维护时无从判断哪个是"正式名" |
| **F26** | 64-65, 271, 329 | `set_tol`（读作"set tolerance"）实为"设置 top of list"；`end_of_page` 实为构建 footer | 命名误导；两个方法都是 `RETURNING` 空、只写全局句柄的副作用型过程 |
| **F27** | 192-250 | 8 处 `CATCH cx_salv_not_found. ENDTRY.` **空处理** | 列技术名一旦不匹配（如重命名 `t_disp-po`），ALV **静默**失去表头/颜色/`BEDAT` 重新可见，无任何告警 |
| **F28** | 196, 207, 316-319, 48, 83 | 魔法值与不可见依赖：`ls_color- col = 3`（黄）、第 316-319 行 4 个**空 label 占位**（为 logo 留白，无注释）、`TEXT-001`/`TEXT-002` 需在源码外的文本元素中维护 | 后人删除空 label 就得到"莫名其妙挤在一起"的页面；文本元素丢失则短转储 |
| **F29** | 325 | `lr_logo-> set_right_logo( 'ZCHEM_N_LOGO_SMALL' )` 硬编码客户图形 | 跨 client / 跨系统 / 上云迁移时极可能缺失；无 fallback、无配置点 |
| **F30** | 49-50 vs 108-131 | `wa_disp` 同时充当**选择屏幕的结构源**（`FOR wa_disp- lifnr`）和**回填工作区**（`LOOP AT it_temp INTO wa_temp` 后又 `MODIFY` 同一结构） | 隐性耦合：改结构定义会同时影响选择屏幕与回填逻辑 |
| **F31** | 88 | `fill_disp` 无 `REFRESH it_disp`、无幂等保护 | 重复调用会把已 `APPEND` 的行再加一遍；`wa_disp` 入口处也未清空 |
| **F32** | 288, 302 | `CONCATENATE lv_text ' to ' s_lifnr -high INTO lv_text SEPARATED BY space.` —— `' to '` **本身已含空格**，再 `SEPARATED BY space` | 标题显示为 `1234000123  to   1234000999`（多重空格） |
| **F33** | 272-273 | `lv_text( 30) TYPE C` / `lv_date TYPE C LENGTH 10` 传给需要 `string` 的 `TEXT` 参数 | 固定长度风险（虽当前放得下）；应直接用 `string` |
| **F34** | 91, 108, 116, 125, 163, 175, 181, 314 | token 被空格污染：`a~ ebeln`、`b ~ebeln`、`wa_disp- lifnr`、`s_lifnr -high`、`sy- datum` | ABAP 能正常分词，但读者/预处理器极易误判；`~`/`-` 差异只在空白，肉眼审查极易看漏 |
| **F35** | 275, 323, 336, 354 vs 194, 215, 261 | 过时语法（`CREATE OBJECT`、`WRITE`）与 7.40 语法（`?=`、`abap_true`、`VALUE =`）**混用**；全文 0 处内联声明 | 风格不统一；AT 顾问报告里会被单列 |
| **F36** | 352, 354 | `DATA : obj_rep ...` 写在 `START-OF-SELECTION` **内部**；`CREATE OBJECT : obj_rep.` 带**多余冒号**（⚠️ 需核实语法） | 非常规写法；冒号在单对象时无意义 |
| **F37** | 195, 203, 213, 220, 227, 233, 239, 245 | 8 段几乎完全相同的 `TRY ... ENDTRY` 样板，未抽象为"列配置表 + 循环" | 40 行 → 可压到 12 行；每加一列都要复制 6 行 |
| **F38** | 204-206, 238-242 | `set_long_text` / `set_medium_text` 内容重复；未设 `set_align`、列宽、数字格式（计数列应为 `INT1`/`INT2` + `do_zae_database`） | ALV 排版靠 `set_optimize` 硬挤，长供应商名下列宽拥挤 |

### P3 — 业务深度（6 项）

| ID | 位置 | 问题 | 影响 |
| --- | --- | --- | --- |
| **F39** | 1, 58, 278 | 名为 `PERF_EVAL`（绩效评估），全文**无任何评分/阈值/加权/等级逻辑** | 命名与内容严重背离，**鼓励业务方误用**这张表给供应商评级 |
| **F40** | 90-160 | 只有 5 个**文档笔数**；无金额、交期、质量、价格、服务任一维度 | 无法支撑任何供应商评估决策；"10 张大额 PO"与"500 张小额 PO"无法区分 |
| **F41** | 90-160 | 不区分单据是否已审批/已过账、是否已收货；`SCH` 一单可挂数百行而 `PO` 一行也是一单 | **笔数在跨文档类型之间不同量纲**，并排比较无意义 |
| **F42** | 90-160 | 计数**不按时间窗长度、也不按供应商规模归一化** | 不同时间窗、不同规模的供应商不可比，趋势解读必然出错 |
| **F43** | 全程序 | 源码中**没有一行注释解释口径**（哪些单据算、哪些不算、为什么排除 `UB`） | 口径知识只存在于开发者脑中；接手者无法维护，需求变更无从下手 |
| **F44** | 104 | `AND ( bstyp = 'A' AND statu = 'A' )` 中 `statu` 字段归属与值域未确认（⚠️ **需核实**） | 若 `EKKO-STATU` 不存在则激活失败；若语义不是"已报价"，则 QUOT 列整体失效 |

---

## 13. 重构方案（建议，非源码）

### 13.1 数据层：五合一条件聚合

当前 5 个 `SELECT` 扫同一批行（F14）。合并为一次：

```abap
" 建议代码
SELECT a~lifnr
       COUNT( DISTINCT CASE WHEN a~bstyp = 'A' THEN a~ebeln END ) AS rfq
       ,COUNT( DISTINCT CASE WHEN a~bstyp = 'F'
                              AND a~bsart <> 'UB' THEN a~ebeln END ) AS po
       ,COUNT( DISTINCT CASE WHEN a~bstyp = 'K' THEN a~ebeln END ) AS cont
       ,COUNT( DISTINCT CASE WHEN a~bstyp = 'L' THEN a~ebeln END ) AS sch
  FROM ekko AS a
  JOIN ekpo AS b ON a~ebeln = b~ebeln
 WHERE a~lifnr IN @s_lifnr
   AND a~bedat IN @s_bedat
   AND b~loekz = @space
 GROUP BY a~lifnr
```

收益：

1. **数据库侧 5× → 1×** 扫描。
2. **五个口径写在同一处**，一眼可审、可测、可改（F43 的根本解法）。
3. ABAP 侧的 `it_temp` / 4 个 `LOOP` / 4 个 `MODIFY` / 4 个 `APPEND` **全部消失**（F15、F04 同时解决——行集合天然是 UNION，不再依赖"谁先命中"）。
4. 直接 `INTO CORRESPONDING FIELDS OF TABLE it_disp`，`INTO` 与 `GROUP BY` 的别名天然对应。

**保留 `COUNT(DISTINCT CASE ...)` 是关键**：只有当 `CASE` 命中时才计入 DISTINCT，未命中返回 `0000`，DISTINCT 不受污染。

**名称合并**（F16）：

```abap
SELECT a~lifnr, MAX( l~name1 ) AS name1
  FROM ekko AS a
  JOIN ekpo AS b ON a~ebeln = b~ebeln
  JOIN lfa1 AS l ON l~lifnr = a~lifnr
 WHERE ...
 GROUP BY a~lifnr
```

去掉 `it_lfa1`、去掉 `FOR ALL ENTRIES`、去掉 `LOOP AT it_disp` + `READ TABLE` + `MODIFY` 三件套。

### 13.2 结构层：把全局搬进类

```abap
" 建议代码
CLASS lcl_vendor_doc_count DEFINITION FINAL
  PUBLIC SECTION.
    INTERFACES zif_report.
    METHODS constructor
      IMPORTING is_sel TYPE ty_selection.
    METHODS run RETURNING VALUE(rt_rows) TYPE tt_vendor_count.
  PRIVATE SECTION.
    DATA ms_sel   TYPE ty_selection.
    DATA mt_rows  TYPE tt_vendor_count.
    METHODS read_counts.
    METHODS enrich_names.
    METHODS configure_alv.
ENDCLASS.
```

- `mt_rows` 成为**类的属性** → `fill_disp` 可被单测（喂 `is_sel`，断言 `rt_rows`）。
- `configure_alv` 只做一件事并**接受 `cl_salv_table` 作为输入参数** → 解决 F23（构造器不再绑全局）。
- `set_tol` → `build_top_of_list( IMPORTING io_parent ... ) RETURNING VALUE(ro_layout) TYPE REF TO cl_salv_form_layout_logo`，`end_of_page` → `build_footer( ... ) RETURNING VALUE(ro_footer) TYPE REF TO cl_salv_form_layout_grid` → 解决 F24、F26（返回对象而非写全局）。
- 全部 `PRIVATE`，只暴露 `run` → 解决 F24。

### 13.3 错误处理

```abap
" 建议代码：让异常传出去，而不是在构造器里 MESSAGE + EXIT
METHOD fill_disp.
  TRY.
      cl_salv_table=>factory( IMPORTING r_salv_table = gr_table
                              CHANGING  t_table = mt_rows ).
    CATCH cx_salv_error.
      " 不处理，直接让 run() 的调用方看到异常，或在此 MESSAGE 后 RAISE
      RAISE EXCEPTION TYPE zcx_vendor_report.
  ENDTRY.
ENDMETHOD.
```

顶层：

```abap
START-OF-SELECTION.
  TRY.
      NEW lcl_vendor_doc_count( is_sel = s_sel )->run( ).
    CATCH zcx_vendor_report.
      MESSAGE '供应商评估数据读取失败，请联系系统管理员（SM21 查详细日志）'
              TYPE 'S' DISPLAY LIKE 'E'.
      " 或者直接 RETURN，保证不 dump
  ENDTRY.
```

解决 F01、F02、F03。

### 13.4 ALV 配置表化

```abap
" 建议代码：替代 8 段 TRY
TYPES: BEGIN OF ty_col_def,
         tech_name TYPE string,
         short     TYPE string,
         medium    TYPE string,
         long      TYPE string,
         color     TYPE c LENGTH 1,
         visible   TYPE abap_bool,
         technical TYPE abap_bool,
       END OF ty_col_def.

DATA gt_col_def TYPE STANDARD TABLE OF ty_col_def WITH NON-UNIQUE SORTED KEY tech_name
  WITH DEFAULT KEY.

" 初始化一次，之后：
LOOP AT gt_col_def INTO DATA(ls_def).
  TRY.
      gr_column = gr_columns->get_column( ls_def-tech_name ).
      ...
    CATCH cx_salv_not_found.
      " 关键：不再静默吞掉
      APPEND VALUE #( ) TO mt_config_errors.
  ENDTRY.
ENDLOOP.

IF mt_config_errors IS NOT INITIAL.
  " 至少提示：ALV 列配置有 N 列未生效
ENDIF.
```

解决 F27、F37。

### 13.5 前端与选择屏幕

```abap
" 建议代码
INITIALIZATION.
  s_lifnr-low  = '0000000001'.
  s_lifnr-high = '9999999999'.
  s_bedat-low  = sy-datum - 365.
  s_bedat-high = sy-datum.

AT SELECTION-SCREEN ON VALUE-REQUEST FOR s_lifnr.
  CALL FUNCTION 'F4_LIFNR'
    EXPORTING
      i_kunnr  = s_lifnr-low
      i_lifnr  = s_lifnr
    EXCEPTIONS
      not_found = 1
      OTHERS     = 2.
  IF sy-subrc <> 0.
    MESSAGE ID sy-msgid TYPE 'S' NUMBER sy-msgno.
  ENDIF.

AT SELECTION-SCREEN ON CHANGE OF s_bedat.
  IF s_bedat-low > s_bedat-high.
    MESSAGE '起始日期不能大于结束日期' TYPE 'E'.
    SET SCREEN POSITION 1.
  ENDIF.
```

配合 `s_bedat` 设为必输（或至少给出默认近 12 个月），解决 F13、F19。

同时：

```abap
" 建议代码：布局持久化 + 空结果提示 + 功能裁剪
gr_table->get_layout_settings( )->set_key( 'ZALV_VENDCOUNT' ).
gr_table->get_layout_settings( )->set_default_layout( 'ZALV_VENDCOUNT' ).
gr_table->get_column_settings( )->set_key( 'ZALV_VENDCOUNT' ).
gr_table->get_column_settings( )->set_fixed( 'LIFNR' 'NAME1' ).
gr_functions->set_all( abap_false ).
gr_functions->set_standard( abap_true ).
gr_functions->set_sort( abap_true ).
gr_functions->set_filter( abap_true ).
gr_functions->set_totals( abap_true ).

IF it_disp IS INITIAL.
  MESSAGE '所选条件无数据。请放宽供应商范围或日期区间。' TYPE 'S'.
  RETURN.
ENDIF.
```

解决 F17、F18、F41-adjacent（F10.5）。

---

## 14. 行动优先级建议

### 立刻做（阻断性，先确认再改）

1. **激活验证** `INCLUDE <color>.`（F11）与 `WRITE ... TO`（F10）是否合法 —— 这两条决定程序能否正常编译。
2. **SE11 确认 `EKKO-STATU` / `EKKO-LOEKZ`**（F44、F05）—— 决定 QUOT 列是否成立。
3. **修 F01/F02/F03**：让构造失败走 friendly message 而不是 dump。这是**改动量最小、收益最大**的一条。
4. **向业务确认 F07（RFQ vs QUOT 的区分维度）与 F08（为什么排除 `UB`）**—— 这两条决定报表的**核心业务语义**是否正确。

### 短期做（正确性 + 性能）

5. **修 F04**：给 QUOT 循环补 `IF sy-subrc NE 0. APPEND ... ENDIF.`，让五段口径一致。
6. **改 13.1 的单次条件聚合**：一次改动同时解决 F04、F13、F14、F15、F16 五个问题，是**投入产出比最高的单点重构**。
7. **统一五指标口径矩阵**（F05/F06/F07/F08），并把口径写进源码注释（F43）。

### 中期做（工程化）

8. 13.2 的类重构（把全局搬进属性、加返回值、收敛可见性）。
9. 13.4 的列配置表化 + 13.5 的选择屏幕/布局/功能裁剪。
10. 清掉 F11 的死 include、F32/F33/F34 的格式与 token 空格、F38 的列宽与数字格式。

### 需要业务决策（不是技术问题）

11. **这张报表到底要做什么？** 如果目标是供应商绩效，需要引入金额、交期、质量数据（来自 `EKKP`/`EKBE`/`MSEG`/`QM` 等），完全重写数据模型（F39、F40）。
12. 如果目标只是"单据笔数盘点"，请**改名**（如 `ZMRR_VENDOR_DOC_COUNT`）并把标题改成与内容一致的措辞，消除误用风险（F39）。**改名比补齐 5 个绩效维度便宜得多。**

---

## 15. 结语

这份代码没有"技术性胡写"的痕迹——作者知道 `COUNT(DISTINCT)` 的必要性、知道 `MODIFY ... WHERE` 要放在 `SORT` 之后、知道 `FOR ALL ENTRIES` 该用在哪里、甚至知道要手写 header 布局而不是交给 SALV 默认。**它在局部是有思考的。**

但它同时犯了一个**元层面的错误**：用 OO 的语法包装了一段过程式代码，然后给了一个与产出不符的名字。于是：

- 结构上的错误（零属性类、全局耦合、构造器失败路径）是**由"装饰性 OO"这个选择必然派生**的，不是孤立 bug；
- 性能上的错误（5 次全量聚合）是**由"每个指标一个查询"这个选择必然派生**的；
- 数据正确性错误（F04/F07）是**由"没有一份写下来的统一口径"这个选择必然派生**的。

**最值得记住的一条**：这个程序最贵的 bug 不是任何一行具体的代码，而是**全文 357 行没有一行注释说明"RFQ 是怎么算出来的"**。当没有人能说清 QUOT 列到底在数什么的时候，接下来任何人做的任何修改（包括本报告建议的合并聚合）都是在不可知的语义上叠加改动。

先问清口径，再动代码。
