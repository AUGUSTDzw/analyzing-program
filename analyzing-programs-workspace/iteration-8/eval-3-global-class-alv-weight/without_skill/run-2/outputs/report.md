# ZCL_STOCK_CHECK 全局类 Onboarding 分析报告

| 项 | 值 |
| --- | --- |
| 对象名 | `ZCL_STOCK_CHECK` |
| 对象类型 | 全局类（**Class-Pool**，`CLASS-POOL` 形式，`PUBLIC FINAL CREATE PUBLIC`） |
| 归属 | MM Reporting team（源码注释声明） |
| 源码规模 | 256 行；1 个结构类型 + 1 个表类型 + 9 个公开方法 + 2 个私有方法体 |
| 依赖 | `MARD`、`MARA`、`MAKT`；ALV `CL_GUI_ALV_GRID` + `CL_GUI_CUSTOM_CONTAINER` |
| 一句话结论 | **这是一个只写了"骨架和数据方法"、从未被接通的报表类**：取数/校验/样式方法全部是孤儿，`display_alv` 里没有一行取数代码，且存在 **7 处编译期/运行期 Blocker**（不存在的 DDIC 字段、未声明的属性、`CLASS-EVENTS` 缺失、`MODIFY` 语义导致的行翻倍）。当前状态**不可能编译通过，也不具备任何业务价值**。 |

---

## 1. 业务问题与业务背景

### 1.1 这段代码想解决什么

从头部注释和类名可以反推出业务意图：

```abap
*&---------------------------------------------------------------------*
*& Report        ZCL_STOCK_CHECK
*&---------------------------------------------------------------------*
*& Global class: stock / weight sanity check for raw materials.
*& Owned by: MM Reporting team.
*&---------------------------------------------------------------------*
```

关键词是 **stock / weight sanity check for raw materials（原材料的库存与重量合理性校验）**。这类需求在制造业 MM 场景中非常典型：

- MM 关键用户每周/月度需要对一批原材料做**数据体检（data sanity check）**，而不是日常的库存查询；
- 典型问题场景：
  - 库存在系统里有值，但**按单位重量推算出的理论重量与实际毛重不符**（单位换算错、`MEINS`/`MEHL` 不一致）；
  - 库存数量与库位**容量上限**冲突（堆垛/罐容/料仓容量被超额占用）；
  - 物料主数据（`EINA`/`NTGEW`）缺失导致后续成本核算、装箱单、运输申报出错；
- 期望的产出是一张 **带颜色标识的 ALV 清单**：哪些行"正常"、哪些行"可疑"（红/黄/绿），并支持双击下钻到 `MMBE`/`MB03` 去追查。

### 1.2 代码实际能回答的问题

| 业务问题 | 设计意图 | 实际状态 |
| --- | --- | --- |
| 列出某工厂 + 指定物料号范围内的库存记录 | `collect_stock` | 逻辑写了，但 SELECT 用了 `MARD` 上不存在的字段；`WHERE` 无库位过滤 → 扫全厂；空 IN 范围会丢弃限制 |
| 补齐物料描述 | `enrich_text` | 逻辑写了，但 `MODIFY` 用在无键表上 → 数据**翻倍**；线性查找 O(n²)；语言硬编码 `'ZH'` |
| 计算单位重量 = 毛重 ÷ 基本含量 | `calc_unit_weight` | **从未被调用**；忽略 `MEINS`/`MEHL`/`UMREZ`/`UMREN` 的单位换算；返回值无单位 |
| 检查库存是否超库位容量 | `check_capacity` | **从未被调用**；字段 `MARD-MVBELN` 不存在；且逻辑是"把库存截断成容量"——**直接篡改业务数据** |
| 在 ALV 上展示并高亮异常行 | `display_alv` + `set_cell_styles` | `display_alv` 传的是**空的局部表**；`set_cell_styles` **从未被调用**；field catalog 的 `tabname` 指向结构名 → 字段绑定不上 |

**结论：整个"重量合理性校验"的业务逻辑在这个类里根本不存在。** 类名叫 `stock_check`，实际只实现了"（半个）取数 + 一个接不通的 ALV 外壳"，Sanity Check 的判断规则（阈值、容差、告警分级）一行都没写。

### 1.3 推测的调用方

- 这个类是 `CLASS-POOL` + `PUBLIC CREATE PUBLIC`，本身**不可直接运行**（需要配套报表或事务码做入口）。源码里没有 `START-SELECTION`/报表程序，所以推测存在一个包装程序（`ZREPORT_STOCK_CHECK` 之类）调用 `zcl_stock_check->display_alv( )`。
- 因为 `display_alv` 内部做了 `CALL SCREEN 0100`，推测调用方把它当作"整屏报表"用 —— 也就是说这个类被设计成 **UI 控制器**，而不是可复用的服务层对象。这是后面第 7 章建议重构的核心矛盾点。

---

## 2. 类结构总览

### 2.1 类型定义

```abap
PUBLIC SECTION.

  TYPES: BEGIN OF ty_stock,
           matnr  TYPE mara-matnr,
           maktx  TYPE makt-maktx,
           lgort  TYPE mard-lgort,
           mstock TYPE mard-mstock,
           eina   TYPE mara-eina,
           ntgew  TYPE mara-ntgew,
         END OF ty_stock.

  TYPES ty_stock_tab TYPE STANDARD TABLE OF ty_stock WITH EMPTY KEY.
```

观察点：

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `MATNR` | `MARA-MATNR` CHAR(40) | 主键 |
| `MAKTX` | `MAKT-MAKTX` CHAR(40) | 由 `enrich_text` 后补 |
| `LGORT` | `MARD-LGORT` CHAR(4) | 库存地点 |
| `MSTOCK` | `MARD-MSTOCK` QUAN(13,3) | **仅"非限制使用库存"**，不含质检/冻结/待检 |
| `EINA` | `MARA-EINA` QUAN(13,3) | 基本含量（国际单位） |
| `NTGEW` | `MARA-NTGEW` QUAN(13,3) | 毛重，单位为**基本单位**（通常 KG） |

> 关键设计缺陷：`MSTOCK` / `EINA` / `NTGEW` 都是 `QUAN`，但结构里**没有 `MEINS`（单位）字段**。ALV 上会出现"库存数量 1000"这种没有单位的裸数字，`NTGEW` 也无法告诉用户这是 KG 还是 TON。`check_capacity` 把容量与 `MSTOCK` 直接比较，也是建立在"两者单位相同"这个未声明的假设上。

`WITH EMPTY KEY` 是另一个埋雷点：见问题 **B-1**。

### 2.2 公开/私有清单

```abap
  PUBLIC SECTION.
    METHODS constructor      IMPORTING iv_plant TYPE werks OPTIONAL.
    METHODS collect_stock    IMPORTING it_matnr TYPE mara-matnr_tab
                             RETURNING VALUE(rt_stock) TYPE ty_stock_tab
                             RAISING   cx_sy_move_cast_error.
    METHODS enrich_text      CHANGING ct_stock TYPE ty_stock_tab.
    METHODS calc_unit_weight IMPORTING is_row TYPE ty_stock
                             RETURNING VALUE(rv_uw) TYPE p DECIMALS 4.
    METHODS check_capacity   IMPORTING iv_warehouse TYPE mard-lgort
                             CHANGING  ct_stock TYPE ty_stock_tab.
    METHODS build_fieldcat   RETURNING VALUE(rt_fieldcat) TYPE lvc_t_fcat.
    METHODS display_alv.
    METHODS on_double_click  IMPORTING iv_row TYPE lvc_row
                                      iv_column TYPE lvc_col
                                      iv_data TYPE any.
    METHODS set_cell_styles  IMPORTING is_row TYPE ty_stock
                             CHANGING  ct_styling TYPE lvc_t_scol.

  PRIVATE SECTION.
    DATA ms_plant    TYPE werks.
    DATA ms_plants   TYPE werks_tab.
    DATA mo_grid     TYPE REF TO cl_gui_alv_grid.
    DATA mo_container TYPE REF TO cl_gui_custom_container.
```

### 2.3 方法职责一览

| # | 方法 | 类型 | 入参 | 出参 / 副作用 | 被谁调用 | 状态评价 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `constructor` | 公开 | `iv_plant`（**OPTIONAL**） | 写 `ms_plant` | 外部 | 参数可选但必用，矛盾 |
| 2 | `collect_stock` | 公开 | `it_matnr` | `rt_stock`（表） | **无人调用** | SQL 有 Blocker |
| 3 | `enrich_text` | 公开 | — | `ct_stock`（CHANGING） | **无人调用** | 有 Blocker |
| 4 | `calc_unit_weight` | 公开 | `is_row` | `rv_uw` | **无人调用** | 单位换算缺失 |
| 5 | `check_capacity` | 公开 | `iv_warehouse` | `ct_stock`（CHANGING） | **无人调用** | 字段 Blocker + 逻辑有害 |
| 6 | `build_fieldcat` | 公开 | — | `rt_fieldcat` | 仅 `display_alv` | `tabname` 用错 |
| 7 | `display_alv` | 公开 | — | 建 ALV + `CALL SCREEN 0100` | 外部（推测报表） | 传空表 + 无事件声明 |
| 8 | `on_double_click` | 公开 | `iv_row/iv_column/iv_data` | `MESSAGE` / `WRITE` | ALV 事件（未注册成功） | 引用未声明变量 |
| 9 | `set_cell_styles` | 公开 | `is_row` | `ct_styling`（CHANGING） | **无人调用** | 追加不清空 |

**"4 个方法公开但零调用"** 是这份代码最大的结构性信号：数据层写完了，编排层（谁按什么顺序调谁）没人写。

### 2.4 状态一览

| 属性 | 类型 | 实际使用情况 |
| --- | --- | --- |
| `ms_plant` | `WERKS` | `constructor` 写，3 处查询读；**但允许初始值** |
| `ms_plants` | `WERKS_TAB` | **完全未使用**（死属性） |
| `mo_grid` | `REF TO CL_GUI_ALV_GRID` | `display_alv` 建，事件源；从未释放 |
| `mo_container` | `REF TO CL_GUI_CUSTOM_CONTAINER` | `display_alv` 建；从未释放 |
| （缺失）`mt_stock` | — | `on_double_click` 里用了 `mt_stock`，但**属性区根本没声明** |
| （缺失）`ms_stock` | — | `on_double_click` 里用了 `ms_stock`，但**从未声明** |

也就是说：**数据被取出来之后没有地方放**。`display_alv` 用的是局部变量 `lt_stock`，`on_double_click` 想用属性 `mt_stock` —— 两个人对"数据放哪"的假设不一致，而两边都不成立。

---

## 3. 执行流程

### 3.1 设计意图的数据流（作者想画的）

```text
        ┌──────────────────────────────────────────────┐
NEW →   │ constructor(iv_plant)                         │
        └──────────────────────────────────────────────┘
                          │ ms_plant
                          ▼
        ┌──────────────────────────────────────────────┐
        │ collect_stock(it_matnr)  ──SQL──> MARD/MARA   │
        └──────────────────────────────────────────────┘
                          │ rt_stock
                          ▼
        ┌──────────────────────────────────────────────┐
        │ enrich_text(  )  ──SQL──> MAKT (ZH)          │
        └──────────────────────────────────────────────┘
                          │ ct_stock
                          ├──────────────► calc_unit_weight(  )  →  单位重量（判断是否合理）
                          ├──────────────► check_capacity(iv_warehouse) → 容量校验
                          ▼
        ┌──────────────────────────────────────────────┐
        │ set_cell_styles(  ) → lvc_t_scol              │
        └──────────────────────────────────────────────┘
                          │ styling
                          ▼
        ┌──────────────────────────────────────────────┐
        │ display_alv(  )：container → grid → fieldcat │
        │               → set_table_for_first_display   │
        │               → SET HANDLER → CALL SCREEN    │
        └──────────────────────────────────────────────┘
                          │ 双击
                          ▼
        ┌──────────────────────────────────────────────┐
        │ on_double_click(  ) → 按列给出提示/下钻       │
        └──────────────────────────────────────────────┘
```

### 3.2 实际可达的数据流（编译通过的话）

```text
        ┌──────────────────────────────────────────────┐
        │ constructor(iv_plant)  → ms_plant             │
        └──────────────────────────────────────────────┘
                          │  （没有箭头指向任何人）
                          ▼
        ┌──────────────────────────────────────────────┐
        │ display_alv(  )                               │
        │   lt_stock  ← 局部变量，初始为空              │
        │   build_fieldcat( ) → tabname = 'TY_STOCK' ✗ │
        │   set_table_for_first_display(空表 + 坏目录)   │
        │   SET HANDLER ✗（无 CLASS-EVENTS）            │
        │   CALL SCREEN 0100                            │
        └──────────────────────────────────────────────┘
                          │
        ✗ 到此为止 —— 空 ALV
```

**实际只有 `constructor → display_alv` 一条路径。** 中间 4 个业务方法、1 个样式方法、1 个事件方法全部是孤儿代码。

### 3.3 屏幕流程（如果能跑通）

```text
外部报表
  └─> constructor / NEW
  └─> display_alv
        1. CREATE OBJECT mo_container  (需要屏幕 0100 上已存在名为 'STOCK_AREA' 的自定义控件)
        2. CREATE OBJECT mo_grid
        3. set_table_for_first_display
        4. SET HANDLER on_double_click FOR mo_grid
        5. CALL SCREEN 0100    ← 屏幕切换发生在 ALV 初始化之后
                                  repaint_detlevel = 1 意味着屏幕尚未 active
```

第 5 步是关键时序风险：ALV 在 `CALL SCREEN` **之前**就创建并初始化了，而 custom container 只有在屏幕 active 之后才可用。`repaint_detlevel = 1` 正是这个顺序问题的产物，正确做法是 `2`（下一帧重绘）。

---

## 4. 取数逻辑详解

### 4.1 `collect_stock` —— 字符串 SQL 是死代码，Open SQL 是错的

```abap
METHOD collect_stock.
  DATA lv_sql TYPE string.

  lv_sql = |SELECT mard~lgort mard~mstock mara~eina mara~ntgew mara~matnr|
         && |  FROM mard INNER JOIN mara ON mara~matnr = mard~matnr|
         && | WHERE mard~werks = '{ ms_plant }'|
         && |   AND mard~lgort IN iv_warehouse_range( )|.   "← 变量根本不存在

  SELECT matnr lgort mstock eina ntgew
    FROM mard
    INTO TABLE rt_stock
    WHERE werks  = ms_plant
      AND matnr IN it_matnr.

  LOOP AT rt_stock ASSIGNING FIELD-SYMBOL(<ls>).
    <ls>-matnr = <ls>-matnr.                                  "← 自赋值
  ENDLOOP.

  IF rt_stock IS INITIAL.
    MESSAGE 'No stock records found' TYPE 'S'.
  ENDIF.
ENDMETHOD.
```

四个问题叠在一起：

**（1）`lv_sql` 从头到尾没被使用。** 它构建的是 `MARD INNER JOIN MARA` 的语句 —— 这才是作者真正想要的 SQL（`EINA`/`NTGEW` 在 `MARA` 上，必须 JOIN）。但实际执行的是下一条只查 `MARD` 的语句。所以：
- 死代码 + 逻辑漂移：真实意图（带库位范围过滤）与实现（无库位过滤）不一致；
- `AND mard~lgort IN iv_warehouse_range( )` 里的 `iv_warehouse_range` **在方法签名中不存在** —— 这是"接口被抽掉一半"的历史遗留证据：`lv_sql` 编译不过的代码被留在方法里当注释用。

**（2）`SELECT ... eina ntgew FROM mard` 引用了 `MARD` 上不存在的字段。**
`EINA`（基本含量）和 `NTGEW`（毛重）都是 `MARA` 的字段，`MARD` 只有 `MARD-WERKS / LGORT / MATNR` 以及数量/状态类字段（如 `MSTOCK`、`LFHIR` 等）。把 `EINA`/`NTGEW` 放进 `MARD` 的 SELECT 列表 → 语法检查阶段即报"字段不在数据库表 MARD 中"。**这是 Blocker。**

顺带说明映射规则：`INTO TABLE rt_stock` 目标是结构表，ABAP 按**字段名**而非顺序映射，所以 `MAKTX` 天然为空 —— 这部分设计是自洽的（等 `enrich_text` 补），但因为 `enrich_text` 没被调用，所以永远空。

**（3）`<ls>-matnr = <ls>-matnr;`** —— 自己赋值给自己，无任何效果。可能是早期版本做过 `trim`/去空格/格式化的残留。

**（4）`MESSAGE ... TYPE 'S'` 直接在取数方法里弹提示。** 问题：
- 数据方法里弹消息 = 隐式控制流，后台作业/Fiori 调用场景下消息会丢失；
- `"No stock records found"` 是零查到的**正常业务结果**，不是异常，正确处理是返回空表让 ALV 显示空，或抛自定义异常；
- 文本硬编码英文，且 `TYPE 'S'` 在 ALV 场景下会显示在状态栏但用户可能已经离开。

**（5）`RAISING cx_sy_move_cast_error` 从未 `RAISE`。** `SELECT INTO` 结构不匹配确实可能抛这个异常，所以声明本身勉强说得过去，但**整个类没有任何异常处理**（调用方拿不到失败原因），也没有自定义异常类。

### 4.2 `enrich_text` —— `MODIFY` 用在无键表上会**追加**而不是**修改**

```abap
METHOD enrich_text.
  DATA lt_text TYPE TABLE OF makt.

  SELECT matnr maktx FROM makt
    INTO TABLE lt_text
    FOR ALL ENTRIES IN ct_stock
    WHERE matnr = ct_stock-matnr
      AND spras = 'ZH'.

  LOOP AT ct_stock INTO DATA(ls_row).
    READ TABLE lt_text INTO DATA(ls_text) WITH KEY matnr = ls_row-matnr.
    ls_row-maktx = ls_text-maktx.
    MODIFY ct_stock FROM ls_row.
  ENDLOOP.
ENDMETHOD.
```

这是**本次分析里最隐蔽也最致命的一个 Bug**：

- `ty_stock_tab` 是 `WITH EMPTY KEY`（第 27 行），**没有任何键**；
- `MODIFY ct_stock FROM ls_row` 没有指定 `WITH KEY`，因此以表键匹配；无键表退化为"整行字段全等"匹配；
- `ls_row` 与 `ct_stock` 中的原行**恰好在 `MAKTX` 上不同**（原来是空的，现在填了文本）→ 匹配不上任何已有行 → ABAP 的 `MODIFY ... FROM` 在找不到匹配行时**追加**一行；
- 结果：循环 N 次 → 表变成 **2N 行**（N 行 `MAKTX` 为空 + N 行 `MAKTX` 有值），同一个物料在 ALV 上出现两次。

如果 `MAKT` 没查到中文描述（`ls_text-maktx` 为空），则 `ls_row` 与原行全等 → 触发 `MODIFY` 的"相同行不修改"分支 → 表大小不变。这解释了为什么这个 Bug **在小数据测试时可能"看起来正常"**，只有当部分物料存在中文描述时才暴露 —— 典型的"上线后数据翻倍"型故障。

其他问题：

| 问题 | 说明 |
| --- | --- |
| 性能 O(n²) | `LOOP × READ TABLE WITH KEY` 是线性查找。1000 个物料 × 1000 条 `MAKT` ≈ 100 万次比较。正确做法：`SORT lt_text BY matnr` + `READ ... BINARY SEARCH`，或直接 `SORT ct_stock BY matnr` 后用 hashed 表 |
| 无语言回退 | 硬编码 `spras = 'ZH'`。若物料无中文描述，`MAKTX` 就是空的。标准做法是回退到 `MAKT-SPRAS = mara-maktx`（物料主数据的备用语言）或 `'1'`，最后回退 `MAKT-SPRAS = 'E'` |
| 遍历时修改 | `LOOP ... INTO`（拷贝语义）+ `MODIFY` 修改同一张表 —— 当前因为是无键表才"没出事"，一旦改成有键表就会踩到"修改被遍历的表"的经典陷阱。应改为 `ASSIGNING` + 直接改字段分量 |
| `FOR ALL ENTRIES` 无判空 | 新版本（≥7.0x）对空内表不会 dump，但仍是反模式，且 **`FOR ALL ENTRIES` 产生重复行**（同物料多库存地点 → SELECT 列表重复），本例因为随后只按 `matnr` 读所以侥幸无害 |

### 4.3 `calc_unit_weight` —— 数学对，单位错

```abap
METHOD calc_unit_weight.
  DATA lv_base TYPE p DECIMALS 4.

  lv_base = is_row-eina.

  IF lv_base IS INITIAL.
    rv_uw = 0.
    RETURN.
  ENDIF.

  rv_uw = is_row-ntgew / lv_base.
ENDMETHOD.
```

设计意图：单位重量 = `NTGEW / EINA`（毛重 ÷ 基本含量）。零除保护写得不错。但：

- **`NTGEW` 的单位是 `MARA-MEHL`（基本单位，通常 KG）**，而**实际发料用的是 `MARA-MEINS`（库存单位）**。当 `MEINS <> MEHL` 时（例如库存单位是"包"、基本单位是 KG，且 `MARA-UMREZ/UMREN` 存在换算关系），正确的单位重量应当是：
  ```text
  单位重量(库存单位) = NTGEW / EINA / UMREZ * UMREN     "NTGEW/EINA 得到 KG/EIN，EIN 是基本单位含量
  ```
  仅在 `UMREZ = 1 AND UMREN = 1 AND MEINS = MEHL` 时，本实现才正确。代码既没有取 `UMREZ/UMREN/MEINS`，也没有校验。
- **返回值是裸 `p DECIMALS 4`，没有返回单位**（应返回 `ty_unit_weight` 结构：value + `MARA-MEHL`），调用方无法知道这个数是 KG/个 还是 G/包。
- **返回类型用 `p DECIMALS 4` 而不是 `QUAN`/`DEC 13,4`**：`P` 是内部定点类型，能表示的范围有限（最多 15 位有效数字），且在 ALV 上没有单位格式；`NTGEW`（QUAN 13,3）除以极小的 `EINA` 可能超出 `P` 的表示能力 → 溢出异常。
- **没有告警语义**：真正的 "sanity check" 应该返回"是否合理 + 偏差百分比"，而不是一个裸数值。零除时静默返回 `0`，把"主数据缺失"和"单位重量真的为 0"混为一谈。

### 4.4 `check_capacity` —— 字段不存在 + **会破坏业务数据**

```abap
METHOD check_capacity.
  DATA lv_slots TYPE i.

  SELECT SINGLE mard-mvbeln INTO @lv_slots
    WHERE werks = ms_plant AND lgort = iv_warehouse.

  LOOP AT ct_stock ASSIGNING FIELD-SYMBOL(<ls>).
    IF <ls>-mstock > lv_slots.
      <ls>-mstock = lv_slots.
    ENDIF.
  ENDLOOP.
ENDMETHOD.
```

**问题 1（Blocker）：`MARD-MVBELN` 不存在。** `MVBELN` 属于销售订单/交货领域字段（`VBRK`/`VBELN` 系），`MARD` 里没有这个字段。这条 `SELECT SINGLE` 在语法检查阶段就报错。库位容量应该对应 `MARD` 上的容量类字段（或库存地点自定义扩展表），**具体字段需要与 MM 顾问确认** —— 代码里也没有任何注释说明它想取哪个业务字段。

**问题 2（Blocker）：类型不匹配。** `lv_slots` 是 `TYPE i`（整数），而库位容量是带小数的数量字段。用 `i` 会截断小数，且如果真取的是 QUAN 会直接类型转换失败。

**问题 3（高危，逻辑本身有害）："检查"却修改了被检查的数据。**
- `CHANGING ct_stock` + `<ls>-mstock = lv_slots` = **把真实库存数量覆盖成库位容量**。一份"体检报告"把源数据的库存量改了，用户看不出原值是多少，之后没人能还原。这是把 UI 展示层的意图泄漏进了数据层。
- **`SELECT SINGLE` 查不到记录时 `lv_slots` 保持初始值 0**，于是 `mstock > 0` 对所有非零库存成立 → **全表库存被清零**。也就是说：库位编码写错一个字符，或该库位没有配置容量 → 整张报表变成全 0，且**没有任何提示**。这是最隐蔽的破坏性路径。

**问题 4：口径与方法签名矛盾。** `collect_stock` 取的是**整个工厂所有库存地点**的数据（无 `lgort` 过滤），而 `check_capacity` 的 `iv_warehouse` 是**单个库存地点**。即使逻辑修好，语义也是"用某个库位的容量去裁剪全厂数据"。

**问题 5：正确做法**应该是新增一个状态字段，而不是改 `MSTOCK`：

```abap
"✓ 建议：只读校验，结果写进独立字段
TYPES: BEGIN OF ty_stock,
         ...
         cap_flag TYPE char1,   " 'E' 超容量 / 'W' 接近容量 / ' ' 正常
         cap_usage TYPE p DECIMALS 4,  " 使用率 = mstock / capacity
       END OF ty_stock.
```

### 4.5 SQL 层面的性能与安全

| # | 位置 | 问题 | 影响 |
| --- | --- | --- | --- |
| 1 | `:92` `AND matnr IN it_matnr` | **空的 IN 范围会让 SQL 条件被整体丢弃**，退化成"查整个工厂所有物料的 MARD" | 大工厂可能几百万行 → dump |
| 2 | `:91-92` | `MARD` 主键是 `WERKS → LGORT → MATNR`，条件里**跳过了 `LGORT`** | DB 层难以有效走索引，全范围扫描 |
| 3 | `:109-113` | `MAKT` 未取 `SPRAS` 回退；`FOR ALL ENTRIES` 未判空 | 描述为空 + 无谓的重复行 |
| 4 | `:116` | 线性 `READ TABLE` | O(n²) |
| 5 | `:83-86` | `lv_sql` 用字符串拼接 + `'{ ms_plant }'` **未转义单引号** | 虽然 `ms_plant` 来自 `WERKS` 字段不太可能被注入，但这在代码审查中是明确的 **SQL 注入反模式**，任何复制这个模式到有 `TEXT` 参数的场景都会变成真实漏洞 |
| 6 | 全类 | 无 `SET BUFFERING` / 无 CDS 视图 / 无缓冲表优化 | 频繁刷新报表时重复读 DB |
| 7 | 全类 | 无 `AUTHORITY-CHECK` | 无权限兜底，`SU53` 场景下排查困难 |

---

## 5. ALV 显示流程

### 5.1 五步法与本实现的偏差

标准 ALV Grid 初始化五步：`创建容器 → 创建 Grid → 设置事件 → 准备 Field Catalog/Layout/Sort → set_table_for_first_display → CALL SCREEN`。本实现对照：

```abap
METHOD display_alv.
  DATA lt_stock TYPE ty_stock_tab.       "← ① 空局部表
  DATA lv_ok    TYPE abap_bool.

  CREATE OBJECT mo_container             "← ② 容器：依赖屏幕 0100 上名为 'STOCK_AREA' 的自定义控件
    EXPORTING
      container_name  = 'STOCK_AREA'
      repaint_detlevel = 1;              "← 应为 2

  CREATE OBJECT mo_grid                  "← ③ Grid
    EXPORTING
      i_container       = mo_container
      ex_initial_layout = '1'.

  mo_grid->set_table_for_first_display(  "← ④ 数据（空）+ Field Catalog（坏）
    CHANGING
      it_outtab       = lt_stock
      it_fieldcatalog = build_fieldcat( )
    EXCEPTIONS
      program_error = 1
      OTHERS        = 2 ).

  IF sy-subrc <> 0.                      "← ⑤ 异常被吞
    lv_ok = abap_false.
  ENDIF.

  SET HANDLER on_double_click FOR mo_grid. "← ⑥ 无 CLASS-EVENTS，注册不了

  CALL SCREEN 0100.
ENDMETHOD.
```

### 5.2 Field Catalog 的绑定错误（核心 Blocker）

```abap
APPEND VALUE #(
  fieldname  = 'MATNR'
  ref_field  = 'MATNR'
  tabname    = 'TY_STOCK'
  seltext_m  = 'Material'
  just_field = 'X' ) TO rt_fieldcat.
```

`LVC_FIELDNAME` 里三个属性被混用了：

| 属性 | 语义 | 本代码 | 正确做法 |
| --- | --- | --- | --- |
| `TABNAME` | **传给 ALV 的内表名**（数据容器） | `'TY_STOCK'` ← 这是**结构**名，不是数据表名 | `'LT_STOCK'`（或干脆不填，由 ALV 用 `it_outtab` 推断） |
| `REF_FIELD` | 要引用的字段名 | `'MATNR'` | 配 `REF_TABLE` 一起用 |
| `REF_TABLE` | `REF_FIELD` 所属的**结构**名 | **缺失** | `'TY_STOCK'` |

后果：`TABNAME = 'TY_STOCK'` 指向的是一个结构而非内表，ALV 在运行期无法把字段解析到数据行 → 列能显示标题但**取不到值**（或按实现细节直接 dump）。这与 5.1 中"传空表"叠加，用户看到的是**一张完全空白的 ALV**。

另外的 catalog 问题：

- `NTGEW` 的标题写死 `'Gross Weight (kg)'`，把单位钉死在 KG。若物料基本单位是 TON、或用户在变式里想换显示单位，标题就会**说谎**。正确做法：ALV 显示单位交给 `CFIELD`/`MC_DEFL` 或 CDS 视图的 `@Semantics`，标题用文本符号。
- 没有 `MC_STYLE`/`CFIELD-NO_DL`，`MSTOCK` 上的 `CFIELD = 'MSTOCK'` 是拿数量字段自己当 currency/quantity 参照字段，没有意义。
- 列文本全部**硬编码英文**，而数据描述取的是 `'ZH'` 中文 —— 语言体系不一致，且无法随 SAP 登录语言切换（应该用 `TEXT-xxx` 文本符号 + `T100`，或建 `sscrfield` 的可翻译文本）。
- `build_fieldcat( )` 每次调用都重建 5 个字段，如果后续做刷新/变式/排序会被反复调用，应做成常量或至少属性缓存。
- `NO_OUTLINE = 'X'` 只加在 `MSTOCK` 上，没有配合任何 `TREE` 布局，语义无意义。

### 5.3 事件与交互（`on_double_click`）

```abap
METHOD on_double_click.
  READ TABLE mt_stock INTO ms_stock WITH KEY matnr = iv_data.   "← 两者都未声明

  WRITE: / iv_row, iv_column, iv_data.                        "← OO 上下文中不允许

  CASE iv_column-fieldname.
    WHEN 'MSTOCK'.
      CHECK iv_row > 0.                                        "← 空转
    WHEN 'NTGEW'.
      MESSAGE 'Weight is maintained in MARA, not per stock record' TYPE 'S'.
  ENDCASE.
ENDMETHOD.
```

**五重问题：**

1. **`mt_stock` / `ms_stock` 不存在**（私有属性区只有 4 个属性，见 2.4）。→ 编译错误。
2. **`WRITE` 在全局类的 OO 方法中不允许**（`WRITE` 属于可执行程序语句）→ 语法错误。这行显然是开发者用 `SE24` 单步调试随手敲进去忘了删。
3. **事件形参不匹配**：`CL_GUI_ALV_GRID` 的 `ON_DOUBLE_CLICK` 事件参数是 `ES_ROW TYPE LVC_ROW` / `ES_COL TYPE LVC_COL` / `E_DATA TYPE ANY`。事件处理方法的形参必须与事件参数兼容，`iv_row`/`iv_column`/`iv_data` 是不被接受的命名形式。
4. **缺少事件类声明**（Blocker）：
   ```abap
   "类定义中必须有，否则 SET HANDLER ... FOR mo_grid 无法编译
   CLASS-EVENTS zcl_stock_check DEFINITION PUBLIC FOR cl_gui_alv_grid.
   ```
   这是 OO ALV 最常被忽略的强制声明。
5. **业务逻辑无效**：
   - `CHECK iv_row > 0.` 在 `iv_row` 已被使用之后做非 0 判断，`CHECK` 条件不满足会直接 `EXIT`，但这里没有任何保护价值；
   - `MESSAGE ... TYPE 'S'` 只是告诉用户"重量在 MARA 上"，**没有下钻能力**。真正的双击价值是 `SET_PARAMETER` + `CALL TRANSACTION 'MMBE'`/`'MB03'`，或 `MO_GRID->GET_CURRENT_LINE( )` 后弹出明细。
   - 没有 `iv_column-fieldname` 的 `DEFAULT` 分支，未知列直接静默返回。
   - 用 `iv_row` 直接当内表索引在 ALV 上是**错的**：ALV 排序/过滤后行号与内表行号不再一致，必须维护 `mt_index` 映射或用 `GET_CURRENT_LINE( )`。

### 5.4 样式与格式

```abap
METHOD set_cell_styles.
  APPEND VALUE #(
    fname       = 'MSTOCK'
    color       = 6
    intens      = 0
    style       = cl_gui_richtext=>strikeout
    lstyle      = cl_gui_richtext=>strikeout_col_neg
    ) TO ct_styling.
ENDMETHOD.
```

| # | 问题 | 说明 |
| --- | --- | --- |
| 1 | **从未被调用** | `display_alv` 里没有 `set_table_for_first_display( )` 后的 `set_table_for_display` + 样式注入，ALV **永远不会高亮任何行** |
| 2 | `APPEND` 前没有 `CLEAR ct_styling` | 每次刷新都会**累加** `lvc_t_scol`，长会话下 ALV 内表持续膨胀、颜色错乱 |
| 3 | `is_row` 形参未被使用 | 方法接收了行对象却不看它，对所有行给出相同样式 —— 无法实现"只标记异常行" |
| 4 | 样式语义自相矛盾 | `STYLE = strikeout`（全局删除线）与 `LSTYLE = strikeout_col_neg`（针对某种颜色变体）混用；`LSTYLE` 的语义是"在负值行使用另一种样式"，不是"给删除线指定颜色" |
| 5 | 颜色语义反了 | `COLOR = 6` 是 **正向（绿色）文字**。一般约定：**红色 = 超容量/异常**，绿色 = 正常，黄色 = 警告。这里给"疑似异常"配了绿色 |
| 6 | 没有数值格式 | `MSTOCK`/`NTGEW`/`EINA` 没有通过 `LTC_*` 或 CDS 单位语义给出显示精度与单位；`CFIELD = 'MSTOCK'` 反而会干扰 ALV 的自动格式识别 |

### 5.5 生命周期与资源释放

- `mo_container` 和 `mo_grid` 是**实例属性**，但没有对应的销毁逻辑（无 `ON DESTRUCTION`、无 `mo_grid->free( )`、无 `cl_gui_frontend_services=>collect_and_resize` 之外的清理）。
- 因为类是 `FINAL` + `CREATE PUBLIC`，任何地方 `NEW zcl_stock_check( )` 都会创建一个**独立的 ALV 控件和独立容器**。在循环里 `NEW` 或在同一个屏幕多次调用 → 控件叠加、`ACTIVE` 冲突、内存泄漏，最后 short dump。
- `repaint_detlevel = 1` 在容器尚未 active 时创建控件，会出现控件不可见/需要手动 `SET_VISIBLE` 的经典问题（正解：`2`）。
- `container_name = 'STOCK_AREA'` 要求屏幕 0100 上存在同名 **Custom Control**，而本源码里没有该屏幕的 PBO/PAI、也没有 `SCREEN 0100` 的定义，属于外部隐式依赖 —— 换屏幕或传输到新系统就会 dump。

---

## 6. 问题清单

### 6.1 汇总表

| ID | 位置 | 严重级 | 类别 | 一句话 |
| --- | --- | --- | --- | --- |
| B-1 | `:27,:115-119` | **Blocker** | 数据正确性 | 无键表上 `MODIFY ... FROM` 会**追加而非修改**，物料描述 enrich 后**数据翻倍** |
| B-2 | `:88-92` | **Blocker** | 编译/DDIC | `SELECT ... eina ntgew FROM mard` 用了 `MARD` 上不存在的字段（属于 `MARA`），缺 `INNER JOIN` |
| B-3 | `:144-145` | **Blocker** | 编译/DDIC | `SELECT SINGLE mard-mvbeln` —— `MARD` 无 `MVBELN`；且 `lv_slots TYPE i` 与数量字段类型不匹配 |
| B-4 | `:230-232` | **Blocker** | 编译 | `mt_stock` / `ms_stock` 未声明；`WRITE` 在 OO 方法中不允许 |
| B-5 | `:221` | **Blocker** | 编译/事件 | 缺少 `CLASS-EVENTS ... FOR cl_gui_alv_grid`，`SET HANDLER ... FOR mo_grid` 无法注册 |
| B-6 | `:196-215` | **Blocker** | 架构/功能 | `display_alv` 从不调用 `collect_stock`/`enrich_text`/`check_capacity`/`set_cell_styles`，ALV 数据源永远是空局部表 |
| B-7 | `:158-189` | **Blocker** | ALV | Field Catalog 的 `tabname = 'TY_STOCK'` 指向结构而非内表；`ref_field` 缺 `ref_table` |
| H-1 | `:144-151` | 高 | 逻辑/数据安全 | "检查"却把 `mstock` 覆盖为容量；`SELECT SINGLE` 未命中时 `lv_slots = 0` → **全表库存被清零且无提示** |
| H-2 | `:53-56` | 高 | 事件 | `on_double_click` 形参 `iv_row/iv_column/iv_data` 与 `ON_DOUBLE_CLICK` 的 `es_row/es_col/e_data` 不匹配 |
| H-3 | `:196,211` | 高 | ALV 生命周期 | 用局部表做 `it_outtab`，ALV 无法保持引用 → 不能 `refresh_table_display`、不能动态排序/更新 |
| H-4 | `:92` | 高 | 性能/SQL | 空 `IN` 范围会**丢弃该条件** → 退化为全厂扫描 |
| H-5 | `:91-92` | 高 | 性能/SQL | `WHERE` 缺 `LGORT`，跳过 `MARD` 主键中段 → 难以走索引 |
| H-6 | `:109-119` | 高 | 性能/正确性 | `LOOP × READ TABLE WITH KEY` = O(n²)；`spras = 'ZH'` 无回退；遍历中 `MODIFY` 同一表 |
| H-7 | `:199-202,223` | 高 | 屏幕/UI | `CALL SCREEN 0100` 硬编码 + 依赖外部 Custom Control；`repaint_detlevel = 1`；class-pool 无 PBO/PAI |
| H-8 | `:217-219` | 高 | 错误处理 | `EXCEPTIONS OTHERS = 2` 吞掉所有异常，`lv_ok` 赋值后**从未使用**，用户看不到任何错误 |
| H-9 | `:246-252` | 高 | ALV 样式 | `set_cell_styles` 从未被调用；`APPEND` 前不清空；`COLOR = 6`(绿) 与删除线语义冲突；`is_row` 未使用 |
| H-10 | `:18-25` | 高 | 业务语义 | 结构缺 `MEINS`/`MEHL`/`UMREZ`/`UMREN`/状态字段 → 无法做单位换算、无法表达"超容量"、ALV 显示裸数字 |
| M-1 | `:83-86` | 中 | 死代码/安全 | `lv_sql` 构建后从未使用；字符串拼接 SQL 且 `'{ ms_plant }'` 未转义（SQL 注入反模式）；`iv_warehouse_range` 变量不存在 |
| M-2 | `:94-96` | 中 | 死代码 | `<ls>-matnr = <ls>-matnr` 自赋值空转 |
| M-3 | `:29-30,72-76` | 中 | 接口设计 | `iv_plant` 是 `OPTIONAL` 但所有查询都依赖它；未传 → 空工厂 → 静默返回空表 |
| M-4 | `:35,98-100` | 中 | 错误处理 | `RAISING cx_sy_move_cast_error` 从未 RAISE；取数方法里弹 `MESSAGE TYPE 'S'`；无自定义异常类 |
| M-5 | `:65` | 中 | 死属性 | `ms_plants` 完全未使用 |
| M-6 | `:124-137` | 中 | 业务逻辑 | `NTGEW / EINA` 忽略 `MEINS`/`MEHL`/`UMREZ`/`UMREN`；返回裸 `p` 无单位；零除静默返回 0；无"是否合理"判定 |
| M-7 | 全类 | 中 | 业务缺失 | "weight sanity check" 的核心判定（阈值/容差/告警分级）**完全没有实现**；`calc_unit_weight` / `check_capacity` 均为孤儿方法 |
| M-8 | `:22` | 中 | 业务语义 | `MSTOCK` 仅非限制使用库存，不含质检/冻结/待检，不能代表"库存总量" |
| M-9 | 全类 | 中 | 安全 | 无 `AUTHORITY-CHECK`、无审计日志 |
| M-10 | `:13,66-67` | 中 | 设计 | `FINAL` + UI 控件实例属性 → 不可继承、不可单元测试、单例风险 |
| M-11 | 全类 | 中 | 资源 | `mo_grid`/`mo_container` 从不释放；无 `ON DESTRUCTION`；多次调用会叠加控件 |
| M-12 | `:158-189` | 中 | 可维护性 | Field Catalog 列文本硬编码英文，与数据语言 `'ZH'` 不一致；未用文本符号 `TEXT-`/`T100` |
| M-13 | `:189,182` | 中 | 格式化 | `NTGEW` 标题钉死 `(kg)`；未做显示单位换算；`CFIELD = 'MSTOCK'` 自引用无意义 |
| M-14 | 全类 | 中 | 测试 | 无 ABAP Unit、无 CDS、无数据库访问层抽象，任何改动都要手工测 |
| L-1 | `:44-46` | 低 | 签名 | `check_capacity` 单库位参数 vs `collect_stock` 全库位数据范围，接口口径不一致 |
| L-2 | `:142` | 低 | 命名 | `lv_slots`（"槽位数"）实际存的是库位容量，命名误导 |
| L-3 | `:111-113` | 低 | 规范 | `FOR ALL ENTRIES` 未做空表判断（新版无害，仍属反模式） |
| L-4 | `:183` | 低 | ALV | 单独 `NO_OUTLINE = 'X'` 但无树形布局，语义无意义 |
| L-5 | `:7-14` | 低 | 结构 | `CLASS-POOL` 形式的全局类用于 UI 展示，屏幕/UI 职责应外移到调用方 |

### 6.2 Blocker 逐条修法

**B-1：`enrich_text` 改成 `ASSIGNING` + 直接改分量，并用 hashed 表替代线性查找**

```abap
METHOD enrich_text.
  DATA lt_text TYPE HASHED TABLE OF makt WITH UNIQUE KEY matnr spras.

  IF ct_stock IS INITIAL.
    RETURN.
  ENDIF.

  SELECT matnr spras maktx FROM makt
    INTO TABLE lt_text
    FOR ALL ENTRIES IN ct_stock
    WHERE matnr = ct_stock-matnr
      AND spras IN @lv_langs.                 " 'ZH' → '1' → 'E' 由调用方或方法内决定

  LOOP AT ct_stock ASSIGNING FIELD-SYMBOL(<row>).
    READ TABLE lt_text INTO DATA(ls_text)
      WITH KEY matnr = <row>-matnr spras = 'ZH'.
    IF sy-subrc <> 0.
      READ TABLE lt_text INTO ls_text WITH KEY matnr = <row>-matnr spras = '1'.
    ENDIF.
    IF sy-subrc = 0.
      <row>-maktx = ls_text-maktx.
    ENDIF.
    "✓ 直接改分量：不做 MODIFY，永远不会追加重复行
  ENDLOOP.
ENDMETHOD.
```

**B-2 / B-3：取数语句改为真实字段 + 显式 JOIN + 库位过滤**

```abap
METHOD collect_stock.
  IF it_matnr IS INITIAL.
    RAISING.                                   " 阻断 H-4：空 range 退化为全表扫描
    RETURN.
  ENDIF.

  SELECT mard~matnr, mard~lgort, mard~mstock,
         mara~eina,  mara~ntgew, mara~meins, mara~mehl
         FROM mard INNER JOIN mara ON mara~matnr = mard~matnr
         INTO TABLE @rt_stock
         WHERE mard~werks  = @ms_plant
           AND mard~matnr IN @it_matnr
           AND mard~lgort IN @it_lgort.         " 补主键中段，见 H-5
ENDMETHOD.
```

容量校验也应换成"只读 + 状态字段"，见 4.4 的 `cap_flag` / `cap_usage` 建议类型。

**B-4 / B-5 / H-2：事件与数据容器改为属性**

```abap
CLASS zcl_stock_check DEFINITION
  PUBLIC FINAL CREATE PUBLIC.

  PUBLIC SECTION.
    CLASS-EVENTS zcl_stock_check DEFINITION PUBLIC FOR cl_gui_alv_grid.  "✓ B-5

    TYPES ty_stock_tab TYPE STANDARD TABLE OF ty_stock WITH EMPTY KEY.

    METHODS display_alv.
    METHODS on_double_click
      IMPORTING es_row TYPE lvc_row
                es_col TYPE lvc_col
                e_data TYPE any.
  PRIVATE SECTION.
    DATA mt_stock TYPE ty_stock_tab.             "✓ B-4：数据容器必须是属性
    DATA mt_index TYPE lvc_row_tab.              " 行号 → 内表行 映射，排序后仍正确
    ...
ENDCLASS.
```

```abap
METHOD on_double_click.
  READ TABLE mt_stock INDEX mt_index[ es_row-row ] INTO DATA(ls_row).
  IF sy-subrc <> 0.
    RETURN.
  ENDIF.

  CASE es_col-fieldname.
    WHEN 'MATNR'.
      SET PARAMETER ID 'MAT' FIELD ls_row-matnr.
      CALL TRANSACTION 'MB03' AND EXIT.
    WHEN 'MSTOCK'.
      SET PARAMETER ID 'MAT' FIELD ls_row-matnr.
      SET PARAMETER ID 'LGORT' FIELD ls_row-lgort.
      CALL TRANSACTION 'MMBE' AND EXIT.
    WHEN 'NTGEW'.
      MESSAGE '毛重取自 MARA-NTGEW，单位取自 MARA-MEHL' TYPE 'S'.
    WHEN OTHERS.
      RETURN.
  ENDCASE.
ENDMETHOD.
```

**B-6 / H-3：把"编排"补出来**

```abap
METHOD display_alv.
  "① 取数
  collect_stock( it_matnr = it_matnr
                 IMPORTING rt_stock = DATA(lt_raw) ).
  IF lt_raw IS INITIAL.
    MESSAGE '未查到库存记录' TYPE 'S'.
    RETURN.
  ENDIF.

  "② 补描述
  enrich_text( ct_stock = lt_raw ).

  "③ 校验（只加字段，不改 mstock）
  DATA(lt_stock) = calc_sanity( it_stock = lt_raw ).   " 建议新增的编排方法

  "④ 装 ALV
  mt_stock = lt_stock.
  PERFORM setup_alv( ).
ENDMETHOD.

METHOD setup_alv.
  CREATE OBJECT mo_grid
    EXPORTING i_container = mo_container
              ex_initial_layout = '1'.

  SET HANDLER on_double_click FOR mo_grid.

  mo_grid->set_table_for_first_display(
    EXPORTING
      is_layout   = build_layout( )
      i_save      = 'A'
    CHANGING
      it_outtab        = mt_stock              "✓ 属性：可排序/可刷新
      it_fieldcatalog  = build_fieldcat( )
      it_sort          = build_sort( )
    EXCEPTIONS
      program_error = 1
      OTHERS        = 2 ).
  IF sy-subrc <> 0.
    MESSAGE ID '00' TYPE 'E' NUMBER 1 WITH 'ALV 初始化失败' sy-subrc.
  ENDIF.

  mo_grid->register_hotspot_click( it_fieldname = VALUE #( ( fieldname = 'MATNR' )
                                                        ( fieldname = 'MSTOCK' ) ) ).

  "⑤ 索引映射，供双击回溯
  mo_grid->get_selected_rows( IMPORTING et_index = mt_index
                              EXCEPTIONS no_selection = 1 OTHERS = 2 ).
ENDMETHOD.
```

**B-7 / H-9：Field Catalog 与样式**

```abap
METHOD build_fieldcat.
  rt_fieldcat = VALUE #(
    ( fieldname = 'MATNR'  tabname = 'MT_STOCK' ref_field = 'MATNR'
      seltext_m = '物料号' just_field = 'X' )
    ( fieldname = 'MAKTX'  tabname = 'MT_STOCK' ref_field = 'MAKTX'
      seltext_m = '物料描述' )
    ( fieldname = 'LGORT'  tabname = 'MT_STOCK' ref_field = 'LGORT'
      seltext_m = '库存地点' )
    ( fieldname = 'MSTOCK' tabname = 'MT_STOCK' ref_field = 'MSTOCK'
      seltext_m = '库存数量' just_field = 'X' )
    ( fieldname = 'MEINS'  tabname = 'MT_STOCK' ref_field = 'MEINS'
      seltext_m = '单位' )
    ( fieldname = 'NTGEW'  tabname = 'MT_STOCK' ref_field = 'NTGEW'
      seltext_m = '毛重' just_field = 'X' )
    ( fieldname = 'CAPFLAG' tabname = 'MT_STOCK' ref_field = 'CAPFLAG'
      seltext_m = '容量校验' ) ).
ENDMETHOD.

METHOD set_cell_styles.
  "✓ 每次重建前必须清空
  CLEAR ct_styling.
  LOOP AT it_stock ASSIGNING FIELD-SYMBOL(<row>).
    CASE <row>-cap_flag.
      WHEN 'E'.
        APPEND VALUE #( fname = 'MSTOCK'
                        color = COLOR_NEGATIVE intens = 1 ) TO ct_styling.
      WHEN 'W'.
        APPEND VALUE #( fname = 'MSTOCK'
                        color = 6 intens = -1 ) TO ct_styling.
      WHEN OTHERS.
        " 正常行不写样式（不做无意义的全表删除线）
    ENDCASE.
  ENDLOOP.
ENDMETHOD.
```

**H-8：异常不要吞**

```abap
EXCEPTIONS
  program_error = 1
  OTHERS        = 2.

IF sy-subrc <> 0.
  MESSAGE ID '00' TYPE 'S' NUMBER 1
    WITH 'ALV 初始化失败（subrc = ' && sy-subrc && '）'.
  RETURN.
ENDIF.
```

### 6.3 其余问题的处理优先级建议

| 优先级 | 动作 | 覆盖问题 |
| --- | --- | --- |
| P0 | 修 4 个编译 Blocker，让类能通过 SE38 语法检查 | B-2、B-3、B-4、B-5 |
| P0 | 补 `display_alv` 的编排，补 `MT_STOCK` 属性 | B-1、B-6、B-7、H-2、H-3 |
| P1 | 改 `enrich_text`（hashed + `ASSIGNING`）与 `check_capacity`（只加状态字段） | B-1、H-1、H-6 |
| P1 | 补 `LGORT` 过滤、空 range 拦截、修 JOIN | H-4、H-5、M-1 |
| P1 | 实现真正的 sanity check 判定 + 单位换算 | H-10、M-6、M-7、M-8 |
| P2 | Field Catalog 用属性名 + 文本符号 + 单位字段；样式按状态驱动 | H-9、M-12、M-13、L-4 |
| P2 | 异常处理、`AUTHORITY-CHECK`、清理死代码 | H-8、M-2、M-4、M-5、M-9 |
| P3 | 屏幕与 UI 职责外移、资源释放、签名收敛 | H-7、M-10、M-11、L-1、L-2、L-5 |

---

## 7. 改进建议与目标架构

### 7.1 分层：把"取数 / 校验 / 展示"彻底分开

当前设计把三件事塞进一个 `FINAL` 全局类：`MARD/MARA` 的 SQL 逻辑、校验规则、以及带 `CALL SCREEN` 的 UI。建议拆成三层：

```text
┌───────────────────────────────────────────────────────────────┐
│ ZCL_STOCK_CHECK          （服务层，可单测、可后台调用）        │
│  · collect_stock()  → ty_stock_tab        只读 SQL            │
│  · calc_unit_weight() → ty_unit_weight    纯函数 + 单位换算   │
│  · check_sanity()   → ty_sanity_result    纯函数 + 状态字段   │
│  · 无任何 GUI 依赖，无 CALL SCREEN，异常用自定义 cx_ 类        │
└───────────────────────────────────────────────────────────────┘
                            │  数据契约 ty_stock_tab
                            ▼
┌───────────────────────────────────────────────────────────────┐
│ ZCL_STOCK_CHECK_ALV      （UI 层，UI 层可独立替换）           │
│  · build_fieldcat / build_layout / build_sort                 │
│  · create_grid( it_stock ) → ref to cl_gui_alv_grid           │
│  · CLASS-EVENTS ... FOR cl_gui_alv_grid + on_double_click     │
│  · 由调用方（报表/事务码）持有屏幕与容器生命周期                │
└───────────────────────────────────────────────────────────────┘
```

这样做的好处：

- **可单测**：服务层没有 GUI 依赖，可用 ABAP Unit 直接测 `calc_unit_weight` / `check_sanity` 的分支；
- **可复用**：后台定时作业、Fiori/ODATA、BW 数据源都能复用同一套判定规则；
- **UI 可替换**：从 Full-screen ALV 换成 SALV（对象oriented ALV）、Fiori 或 RAP 报表时，服务层零改动；
- **屏幕解耦**：`CLASS-POOL` 里不再出现 `CALL SCREEN 0100`，类不再依赖特定的 screen / custom control。

### 7.2 单位换算的正确姿势

```abap
" 单位重量（以库存单位计）
DATA lv_uw TYPE quan.
IF is_row-eina > 0 AND is_row-umre > 0.
  " NTGEW 是 MEHL(基本单位) 下的毛重；EINA 是基本单位下的每单位含量
  lv_uw = is_row-ntgew / is_row-eina * is_row-umren / is_row-umre.
ENDIF.
" 返回时同时返回单位，避免调用方误用
rs_uw = VALUE #( value = lv_uw unit = COND #( WHEN is_row-meins = is_row-mehl
                                                   THEN is_row-mehl
                                               ELSE is_row-mehl ) ).
```

更稳妥的做法是把这套逻辑放进 **CDS View + `@Semantics` 单位注解**，让 ALV/SAP Fiori/下游报表全部自动得到正确单位：

```abap
@AbapCatalog.sqlViewName: 'ZSTOCKCHK'
@EndUserText.label: '原材料库存与重量校验'
define view ZI_STOCK_CHECK
  as select from mara
    inner join   mard on mara.matnr = mard.matnr
{
  key mard.matnr,
  key mard.werks,
  mard.lgort,
  mara.maktx,
  @Semantics.amount.currencyCode: 'MARD_WERKS'
  mard.mstock,
  mara.meins,
  mara.mehl,
  mara.umre,
  mara.umren,
  mara.eina,
  mara.ntgew
}
```

### 7.3 Sanity Check 的判定规则（业务上应该长什么样）

"合理性校验"必须有**可解释的判定规则和阈值**，并把结论表达成状态字段而不是覆盖原值。建议：

| 规则 | 判定 | 状态 |
| --- | --- | --- |
| 主数据缺失 | `EINA IS INITIAL` 或 `NTGEW IS INITIAL` | `E`（必须修主数据） |
| 库存为负 | `MSTOCK < 0` | `E` |
| 超库位容量 | `MSTOCK > 容量` | `E` |
| 接近库位容量 | `MSTOCK > 容量 * 90%` | `W` |
| 单位重量偏离基准 | `ABS(实际重量 - MSTOCK * 单位重量) / 实际重量 > 容差` | `W` / `E` |
| 库存为零但重量非零 | `MSTOCK = 0 AND NTGEW > 0` | `W` |
| 库存非零但主数据为零 | `MSTOCK <> 0 AND ( EINA = 0 OR NTGEW = 0 )` | `E` |

容差（`W/E` 分界）建议做成类里的常量或可维护的配置表，不要硬编码在 `IF` 里。

### 7.4 迁移路线图

```text
阶段 1（0.5 天）—— 让它能编译
  · 修 MARD/MARA 字段、MVBELN 字段
  · 删 WRITE，补 mt_stock/ms_stock 声明
  · 补 CLASS-EVENTS，事件形参改 es_row/es_col/e_data

阶段 2（1 天）—— 让它能出数
  · display_alv 补：collect → enrich → check → setup_alv
  · MT_STOCK 改属性；tabname 改数据表名；补 ref_table
  · enrich_text 改 hashed + ASSIGNING
  · check_capacity 改状态字段，不再动 mstock

阶段 3（1 天）—— 让它像一份报告
  · field catalog 用文本符号 + MEINS 列 + 正确单位
  · set_cell_styles 接入 + CLEAR + 按状态配色
  · sort/layout/变式/hotspot + 双击下钻 MB03/MMBE

阶段 4（1~2 天）—— 让它可维护
  · 抽服务层异常类、加 AUTHORITY-CHECK
  · 补 ABAP Unit（calc_unit_weight / check_sanity / enrich_text）
  · 死代码清理：lv_sql、自赋值、ms_plants、RAISING 声明、NO_OUTLINE

阶段 5（可选）—— 让它可复用
  · 服务层 / UI 层拆分，CDS 视图 + @Semantics 单位
  · 屏幕与容器生命周期移交调用方
```

---

## 8. 验证与测试建议

**编译期**
- `SE38` → 语法检查 + 扩展程序检查（语法检查能一次抓出 B-2/B-3/B-4/B-5）；
- `SE24` 类 → "语法检查" 同样能抓到 `CLASS-EVENTS` 缺失和事件形参不匹配；
- ATC（ABAP Test Cockpit）勾选 `ALV 规范`、`OO 规范`、`SQL 规范`、`命名规范` —— 会直接指出 `it_outtab` 用局部表、`FOR ALL ENTRIES`、SQL 字符串拼接等问题。

**数据库层**
- `ST05` 跟踪 `collect_stock` / `enrich_text`，核对 `MARD` 走的是哪个索引、扫描行数；
- 在测试系统跑一次"单库位 + 单物料"的最小数据集，**重点验证 enrich 后行数是否翻倍**（B-1）——这是最容易被漏掉的回归点；
- 用 `it_matnr` 传空范围跑一次，确认是否退化成全厂扫描（H-4）；
- 故意传一个不存在的 `lgort` 给 `check_capacity`，确认 `lv_slots = 0` 是否清空全表（H-1）。

**单元测试（建议补）**

```abap
CLASS ltcl_unit_weight_test DEFINITION FINAL FOR TESTING
  DURATION SHORT RISK LEVEL HARMLESS.
  PRIVATE SECTION.
    METHODS test_zero_eina  FOR TESTING.
    METHODS test_meins_diff FOR TESTING.
ENDCLASS.

CLASS ltcl_unit_weight_test IMPLEMENTATION.
  METHOD test_zero_eina.
    DATA(ls_row) = VALUE zcl_stock_check=>ty_stock( eina = 0 ntgew = 100 ).
    cl_abap_unit_assert=>fail_if( zcl_stock_check=>new( )->calc_unit_weight( ls_row ) <> 0 ).
  ENDMETHOD.

  METHOD test_meins_diff.
    " MEINS <> MEHL 时必须走 UMREZ/UMREN 换算
    DATA(ls_row) = VALUE zcl_stock_check=>ty_stock(
                      eina = 2 ntgew = 100 umre = 2 umren = 1 meins = 'PC' mehl = 'KG' ).
    " 期望：100/2 = 50 KG/PC，一 PC 装 2 KG → 单位重量 = 50/2 = 25 KG/PC
    cl_abap_unit_assert=>fail_if( zcl_stock_check=>new( )->calc_unit_weight( ls_row ) <> 25 ).
  ENDMETHOD.
ENDCLASS.
```

**手工回归清单**
1. 空结果集 → 提示是否恰当、是否弹两次消息；
2. 单物料 + 多个库存地点 → 行数是否正确（不被 `enrich_text` 翻倍）；
3. 物料无中文描述 → `MAKTX` 是否有回退值；
4. `EINA = 0` 的物料 → 状态列是否给出 `E` 而不是"单位重量 0"；
5. 双击 `MATNR` / `MSTOCK` → 是否正确跳 `MB03` / `MMBE`，排序过滤后是否仍然跳对行；
6. 反复刷新 5 次 → `lvc_t_scol` 是否没有累积、控件是否没有叠加；
7. 后台运行（无屏幕）→ 是否不再依赖 `CALL SCREEN 0100`。

---

## 9. 新人上手路线（建议 30-60-90）

- **0-15 分钟**：读头部注释 + `CLASS-POOL` + `ty_stock` 类型 → 明白这是"某工厂原材料的库存+重量体检"工具；
- **15-30 分钟**：读 `collect_stock` → 看懂唯一的 DB 入口（并顺手确认它**根本连不上** `MARA` 字段）；
- **30-45 分钟**：读 `enrich_text` → 理解"取数 → 补描述 → 校验 → 展示"的分层意图；
- **45-60 分钟**：读 `build_fieldcat` + `display_alv` → 理解 OO ALV 的 `TABNAME` / `REF_FIELD` / `CLASS-EVENTS` 三件套；
- **接着**：只看第 6 章问题清单的 P0 项 —— **这个类的正确读法是"当作需求草稿，而不是当作可运行代码"**；
- **动手前**：先在测试系统建 CDS View（见 7.2），把取数和校验从 UI 里抽出来，再谈 ALV 美化。

---

## 附录 A：源码结构速查（行号对照）

| 行号 | 内容 | 评价 |
| --- | --- | --- |
| `:7` | `CLASS-POOL zcl_stock_check.` | 类池 + 屏幕依赖 |
| `:18-25` | `ty_stock` 结构 | 缺 MEINS/状态字段 |
| `:27` | `WITH EMPTY KEY` | B-1 根因 |
| `:29-30` | `constructor OPTIONAL` | 必用却可选 |
| `:35` | `RAISING cx_sy_move_cast_error` | 从未 RAISE |
| `:64-67` | 私有属性 4 个 | 缺 `mt_stock`；`ms_plants` 死属性 |
| `:83-86` | `lv_sql` 死代码 | M-1 |
| `:88-92` | `SELECT ... FROM mard` | B-2 / H-4 / H-5 |
| `:94-96` | 自赋值循环 | M-2 |
| `:98-100` | `MESSAGE TYPE 'S'` | M-4 |
| `:109-113` | `MAKT` 查询，`spras = 'ZH'` | H-6 |
| `:115-119` | `MODIFY` 无键表 | **B-1** |
| `:124-137` | `calc_unit_weight` | M-6 |
| `:144-145` | `SELECT SINGLE mard-mvbeln` | **B-3** / H-1 |
| `:147-151` | 覆盖 `mstock` | **H-1** |
| `:158-189` | `build_fieldcat` | **B-7** / M-12 / M-13 |
| `:199-202` | 容器 `STOCK_AREA` + `repaint_detlevel = 1` | H-7 |
| `:196,211` | 局部表 `lt_stock` 作 `it_outtab` | H-3 |
| `:212` | `it_fieldcatalog = build_fieldcat( )` | 建议先落变量便于调试 |
| `:213-219` | 异常被吞 | H-8 |
| `:221` | `SET HANDLER` | **B-5** |
| `:223` | `CALL SCREEN 0100` | H-7 / L-5 |
| `:230-232` | `mt_stock`/`ms_stock`/`WRITE` | **B-4** |
| `:234-239` | `CASE` 分支 | 空转逻辑，无下钻 |
| `:246-252` | `set_cell_styles` | H-9 |

## 附录 B：三个最容易在测试环境"漏掉"的缺陷

1. **B-1 行翻倍**：只有当部分物料**存在**中文描述时才发作。如果测试数据全部有中文描述，或者全部没有，都可能看不出来。必须构造混合数据验证。
2. **H-1 库存清零**：只有当 `check_capacity` 被调用**且**库位查不到记录时才发作。而这个方法根本没被调用 —— 所以它会在"有人把编排补上之后"才第一次爆炸，恰好是最危险的时刻。
3. **H-4 空 IN 范围**：调用方"友好地"不传物料号（想看全厂）时，SQL 条件被整体丢弃，大工厂直接全表扫描 + dump。