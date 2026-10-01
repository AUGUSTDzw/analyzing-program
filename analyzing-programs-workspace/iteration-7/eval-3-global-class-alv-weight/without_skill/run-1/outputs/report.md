# ZCL_STOCK_CHECK 全局类分析报告（Onboarding）

> 分析对象：`evals/zcl_stock_check.clas.abap`（256 行，`CLASS-POOL` 全局类，`PUBLIC FINAL CREATE PUBLIC`）
> 归属团队：MM Reporting
> 分析视角：业务意图 → 类结构 → 取数 → ALV 显示 → 问题清单 → 改造建议

---

## 一、结论先行（TL;DR）

这个类试图做一件事：**按工厂抓取原材料的库存记录，补上物料描述，按仓库容量做"合理性"裁剪，然后用 `CL_GUI_ALV_GRID` 展示，并支持双击交互**。

但当前代码**无法编译通过，也无法运行**。核心结论：

| 维度 | 状态 |
|---|---|
| 编译 | ❌ 至少 3 处硬错误（未声明变量、类型不兼容、疑似不存在的 DDIC 类型） |
| 运行 | ❌ 即便编译过，取数结果恒为空、ALV 数据源恒为空、屏幕 0100 不存在 |
| 业务正确性 | ❌ `calc_unit_weight` 公式在业务上无意义（用 EAN 号当除数） |
| 数据安全 | ❌ `check_capacity` 直接覆盖真实库存数量 |
| 可维护性 | ⚠️ 8 个 public 方法中有 4 个是死代码；逻辑层与显示层耦合 |
| 总体判断 | **这是一个"半成品草稿"级别的程序，不能作为可交付模块使用** |

---

## 二、业务问题：这个类想解决什么

从注释和命名推断的真实需求：

> MM  Reporting 团队需要一张**原材料库存快查表**，用户输入物料号范围 + 工厂（+ 库位），
> 快速看到「物料号 / 描述 / 库位 / 库存数量 / 毛重」，用于**盘点准备**和**库存合理性抽查**。
> 其中"合理性"体现在两处：
> 1. 单位重量检查 —— 判断物料的净重记录是否可信（`calc_unit_weight`）；
> 2. 库位容量检查 —— 库存数量不应超过库位/仓位容量上限（`check_capacity`）。
> 展示层希望用户双击某单元格能进一步追溯。

**必须向业务确认的三个前提假设**（代码里完全体现不出来）：

1. `mara-eina` 是 **EAN 条码号（13 位字符）**，不是"基本数量/计量基数"。用它当除数算单位重量，说明作者可能误把 `eina` 当成了 `UMREN` / `MENGE`。**这个公式几乎肯定是错的。**
2. `check_capacity` 的语义到底是"标记超容"还是"把库存截断到容量"？当前实现是后者（**覆盖**），这会让报表显示的数字不再是真实库存，对账场景下是严重问题。
3. 输出结构里**没有计量单位字段**（`msehi`），但同时显示数量（QUAN）和重量（重量单位在 MARA-`GEWEI` 里，也不在结构中）。**没有单位的报表在业务上是不成立的。**

---

## 三、类结构与方法清单

### 3.1 类型定义

```abap
PUBLIC SECTION.

  TYPES: BEGIN OF ty_stock,
           matnr  TYPE mara-matnr,     " 物料号 CHAR 40
           maktx  TYPE makt-maktx,     " 物料描述 CHAR 40
           lgort  TYPE mard-lgort,     " 库存地点 CHAR 4
           mstock TYPE mard-mstock,    " 库存数量 QUAN 13,3
           eina   TYPE mara-eina,      " EAN 条码号 CHAR 13
           ntgew  TYPE mara-ntgew,     " 净重 QUAN 13,3
         END OF ty_stock.

  TYPES ty_stock_tab TYPE STANDARD TABLE OF ty_stock WITH EMPTY KEY.
```

要点：
- `WITH EMPTY KEY` —— 这是一张**纯行结构内表，没有可用键**。这是后面 `MODIFY ... FROM` 报错的根因（见 §6.2）。
- 缺少：`msehi`（基本计量单位）、`brgew`/`gewei`（毛重 + 重量单位）、一个自定义的"超容标记"字段。

### 3.2 属性（Attributes）

| 属性 | 类型 | 用途 | 评价 |
|---|---|---|---|
| `ms_plant` | `werks` | 工厂 | ✅ 唯一真正被使用的属性 |
| `ms_plants` | `werks_tab` | 多工厂 | ❌ **死属性**，全类无任何读写 |
| `mo_grid` | `REF TO cl_gui_alv_grid` | ALV 控件 | 命名不合规（`mo_` 惯例指全局类实例，控件应 `ms_`） |
| `mo_container` | `REF TO cl_gui_custom_container` | ALV 容器 | 同上；且**类池里无法建屏幕**，容器无处可挂（见 §6.3） |

### 3.3 方法清单与"实际是否被调用"

> 这是本次分析最重要的发现之一：**8 个 public 方法里，只有 3 个被调用，4 个是死代码。**

| 方法 | 职责 | 被谁调用 | 状态 |
|---|---|---|---|
| `constructor` | 保存工厂 | 调用方 | ✅ 正常 |
| `collect_stock` | 从 MARD 取库存 | **无人调用** | ⚠️ 死代码（应在 `display_alv` 里） |
| `enrich_text` | 从 MAKT 取中文描述 | **无人调用** | ⚠️ 死代码 |
| `calc_unit_weight` | 算单位重量 | **无人调用** | ❌ 死代码 + 公式错误 |
| `check_capacity` | 库位容量裁剪 | **无人调用** | ❌ 死代码 + 破坏数据 |
| `build_fieldcat` | 构 ALV 列目录 | `display_alv` | ✅ 唯一被用的逻辑方法 |
| `display_alv` | 显示 ALV | 外部调用 | ⚠️ 内部取数链路断裂 |
| `on_double_click` | 双击事件处理 | 事件绑定 | ❌ 内部变量未声明 |
| `set_cell_styles` | 设置单元格样式 | **无人调用** | ❌ 死代码（应传给 ALV） |

**实际调用链**（执行时）：

```
外部程序 → constructor
         → display_alv ──> build_fieldcat()
                      ──> ALV 显示（空表）
                      ──> SET HANDLER on_double_click
         （双击）  ──> on_double_click
```

**设计上应该的调用链**：

```
外部程序 → constructor(iv_plant, it_matnr)
         → collect_stock()          ← 取库存
         → enrich_text()            ← 补描述
         → check_capacity()         ← 超容标记（不改原值）
         → build_fieldcat()
         → display_alv( mt_stock )  ← 传数据进来
```

---

## 四、取数逻辑分析

### 4.1 `collect_stock` —— 拼了一个 SQL 却执行了另一个

```abap
  METHOD collect_stock.

    DATA lv_sql TYPE string.

    lv_sql = |SELECT mard~lgort mard~mstock mara~eina mara~ntgew mara~matnr|
           && |  FROM mard INNER JOIN mara ON mara~matnr = mard~matnr|
           && | WHERE mard~werks = '{ ms_plant }'|
           && |   AND mard~lgort IN iv_warehouse_range( )|.

    SELECT matnr lgort mstock eina ntgew
      FROM mard
      INTO TABLE rt_stock
      WHERE werks  = ms_plant
        AND matnr IN it_matnr.

    LOOP AT rt_stock ASSIGNING FIELD-SYMBOL(<ls>).
      <ls>-matnr = <ls>-matnr.
    ENDLOOP.

    IF rt_stock IS INITIAL.
      MESSAGE 'No stock records found' TYPE 'S'.
    ENDIF.

  ENDMETHOD.
```

逐点问题：

1. **`lv_sql` 是彻底的死字符串**（构造后从未使用）。它包含未转义的字符串拼接 `'{ ms_plant }'`，一旦有人"顺手"改成动态 SQL，就是标准 SQL 注入漏洞。同时它引用了**签名里根本不存在的** `iv_warehouse_range` —— 说明作者从别的程序复制过来没改。
2. **真正的 SELECT 与拼串意图不一致**：字符串里写了 `INNER JOIN mara` 取 `eina`/`ntgew`；真语句却只 `FROM mard` 却选了 `eina`、`ntgew`。
   ⚠️ **`MARD` 上不存在 `EINA` 和 `NTGEW`（这两个字段在 `MARA` 上）**。这条语句在 ABAP 打开 SQL 里不可能成立 —— 要么编译期报错，要么运行时 SQL 检查失败后 dump。请务必在 SE38 里先编译确认。
3. **`it_matnr` 为空 = 全工厂全物料**。`matnr IN it_matnr` 在内表为空时不会产生结果限制，等价于"导出该工厂所有库存记录"。这是**报表类最经典的越权读取事故**：用户没选物料就按了执行，几百万行全进内存。
4. **完全没有库位过滤**：作者明明想按库位过滤（死字符串里有 `lgort IN ...`），真语句里没有 `lgort` 条件；而 `check_capacity` 又是按单个 `lgort` 传的 —— **过滤意图与实现完全脱节**。
5. **无 `PACKAGE SIZE` / `UP TO n ROWS`**：大工厂全量拉取，无分页、无流式处理。
6. **`<ls>-matnr = <ls>-matnr` 自赋值**：纯废码。而且 `rt_stock` 是 RETURNING 参数（方法内已是本地副本），用 `ASSIGNING` 毫无意义。
7. **在取数方法里 `MESSAGE ... TYPE 'S'`**：一个可复用的全局类，在数据层弹成功消息，等于把 GUI 依赖泄漏进业务逻辑。而且"没查到数据"是正常业务结果，不是需要弹窗的成功消息。
8. **签名承诺 `RAISING cx_sy_move_cast_error`，方法体里没有任何 `CONV` / `CAST`** —— 永远不会抛异常，属于过度声明。
9. `it_matnr TYPE mara-matnr_tab` —— **标准 DDIC 里是否存在 `MARA-MATNR_TAB` 这个表类型需要确认**（SAP 一般只生成结构，不为表生成 `_TAB` 表类型）。若不存在则是编译错误；若存在也建议改用 `RANGES matnr TYPE mara-matnr` 以便同时支持"单值/范围/排除"。

### 4.2 `enrich_text` —— FOR ALL ENTRIES 与 MODIFY 双双出错

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
```

问题：

1. **缺少空表守卫**。`FOR ALL ENTRIES IN ct_stock` 在 `ct_stock` 为空时，读取的 `ct_stock-matnr` 是未初始化的（无 space），行为未定义，最坏情况 dump。这是所有 FAE 代码都必须加的一行：
   ```abap
   IF ct_stock IS INITIAL.
     RETURN.
   ENDIF.
   ```
2. **`MODIFY ct_stock FROM ls_row` 在 `WITH EMPTY KEY` 的表上不成立**。`MODIFY itab FROM wa` 依赖表的主键；`ty_stock_tab` 是 `WITH EMPTY KEY`，这条语句无法按业务键定位行 —— 必须改为字段符号直接改：
   ```abap
   LOOP AT ct_stock ASSIGNING FIELD-SYMBOL(<ls>).
     READ TABLE lt_text INTO DATA(ls_text) WITH TABLE KEY matnr = <ls>-matnr.
     IF sy-subrc = 0.
       <ls>-maktx = ls_text-maktx.
     ENDIF.
   ENDLOOP.
   ```
3. **`READ TABLE ... WITH KEY matnr =` 是线性全表扫描**。`lt_text TYPE TABLE OF makt` 是标准表（键 `mandt matnr maktx`），按 `matnr` 查要走全表，复杂度 O(n²)。应改成 `SORTED TABLE ... WITH UNIQUE KEY matnr`（注意：`makt` 主键含 `maktx`，同一物料多语言描述会重复，需先按 `spras` 过滤再 `SORT`）。
4. **语言硬编码 `'ZH'`，无回退**。中文描述缺失的物料会得到空白（`READ` 失败时 `ls_text-maktx` 为初始值，且未判 `sy-subrc`）。应回退到 `spras = sy-langu` 或 `'1'`。
5. **整行拷进拷出**：每行都做一次 `LOOP INTO` + `MODIFY FROM`（整结构拷贝），上万行时代价明显。
6. **每行触发 `READ` 无批量优化**：更好的做法是直接用 `SELECT ... FOR ALL ENTRIES` 后按 `matnr` 排序 + 二分查找，或干脆用 `JOIN` 在一次 SQL 里取完（见 §7 建议）。

### 4.3 `calc_unit_weight` —— 公式在业务上无意义

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

1. **`lv_base = is_row-eina` 是类型不兼容的赋值**。`mara-eina` 是 **CHAR 13**，目标是 `TYPE p DECIMALS 4`（packed 数值）。ABAP 中字符→packed 的隐式转换**不被允许**（会报类型不兼容的编译错误），必须显式 `CONV p( )` / `CONV i` 且要处理 `EINA` 前导零与非数字字符。
2. **业务逻辑错误**：EAN 是全球商品编码，不携带任何重量语义。`ntgew / eina` 得到的数值没有物理意义。
   - 若意图是"单位重量"，应使用 **`MARA-BRGEW / MARA-BWESB`**（毛重 / 毛重基本单位）或 `NTGEW / UMREZ`（净重 / 基本单位换算），并**同时输出重量单位 `MARA-GEWEI`**。
3. **结果连结构都放不进去**：`ty_stock` 里根本没有"单位重量"字段，`calc_unit_weight` 也无人调用。正确做法是把它做成列目录里的一个计算字段（`form` / ALV 计算列）或加入结构体。
4. `IF lv_base IS INITIAL` 对 packed 类型判断的是全零，逻辑本身没错，但结合上面的类型问题毫无意义。

### 4.4 `check_capacity` —— 直接覆盖真实库存（最高危）

```abap
  METHOD check_capacity.

    DATA lv_slots TYPE i.

    SELECT SINGLE mstbw FROM mard-mvbeln INTO @lv_slots
      WHERE werks = ms_plant AND lgort = iv_warehouse.

    LOOP AT ct_stock ASSIGNING FIELD-SYMBOL(<ls>).
      IF <ls>-mstock > lv_slots.
        <ls>-mstock = lv_slots.
      ENDIF.
    ENDLOOP.

  ENDMETHOD.
```

1. **⚠️ `MARD-MVBELN` 不是有效字段**（`MVBELN` 是销售订单字段，`MSTBW` 也不在 `MARD` 上；"仓位容量"在标准表里通常来自 `LAGG` 或自定义的仓位容量表）。这条 SELECT 会失败。同时别名 `mstbw` 与实际字段 `mvbeln` 不一致，说明又是复制粘贴未改。**需与业务确认"库位容量"到底存在哪里。**
2. **⚠️ 把 `lv_slots` 定义为 `TYPE i`**：`MARD` 上的数量字段是 QUAN（带 3 位小数），赋给整数会**直接截断/溢出**，且与 `<ls>-mstock`（QUAN）比较会触发类型转换。必须用 `TYPE mard-mstock`（或 `QUAN`）。
3. **⚠️⚠️ 最严重：把 `mstock` 直接改成容量值。** 这是**静默篡改库存数量**——用户看到的"库存"不再是真实库存，而是一个被截断的上限值，且没有任何标记说明它被改过。盘点/对账类报表这样做是**数据可信度事故**。
   正确做法：**不修改 `mstock`**，改为增加一个标记字段（如 `over_cap TYPE abap_bool`）或一个"超容量"列，由 ALV 用颜色/图标呈现。
4. **`SELECT SINGLE` 取到的"容量"对整张表所有行生效**：同一个库位下不同物料共享同一个上限值，这个上限的业务含义本身也可疑（是仓位最大存放量？货架数？），需要确认。
5. 未判 `sy-subrc`：`SELECT SINGLE` 未命中时 `lv_slots` 为 0 → 循环会把**所有行库存都置为 0**。这是最恶劣的失败模式：**查询失败 = 全表显示 0 库存**。
6. 死代码：无人调用。

---

## 五、ALV 显示流程分析

### 5.1 `build_fieldcat` 的问题

```abap
    APPEND VALUE #(
      fieldname  = 'MATNR'
      ref_field  = 'MATNR'
      tabname    = 'TY_STOCK'
      seltext_m  = 'Material'
      just_field = 'X' ) TO rt_fieldcat.
    ...
    APPEND VALUE #(
      fieldname  = 'MSTOCK'
      ref_field  = 'MSTOCK'
      tabname    = 'TY_STOCK'
      seltext_m  = 'Stock Qty'
      cfield     = 'MSTOCK'
      no_outline = 'X' ) TO rt_fieldcat.
```

| 问题 | 说明 |
|---|---|
| `tabname = 'TY_STOCK'` 硬编码 | 类中的 **local type** 在运行时类型池（RTPool）里按 `TY_STOCK` 是找不到对应 DDIC 结构的。ALV 需要 `it_fieldcatalog` 的 `tabname` 能在 DDIC 中解析，或依赖调用上下文。**对内表 `set_table_for_first_display` 应省略 `tabname`，让 ALV 从 `it_outtab` 动态推导**；若确实需要，请改用 **TDDIC 里的持久结构**（`TYPES ty_stock TYPE zst_stock`，并 `STRUCTURE` 到 DDIC 结构） |
| `ref_field = <自身>` | `REF_FIELD` 用于 `it_outtab` 中字段是**数据引用**的场景；普通平面结构应留空。这里自引用毫无意义 |
| `just_field = 'X'` 在 CHAR 字段上 | CHAR 没有小数点，`JUST_FIELD` 无效果；`just_field` 与 `just` 混用，`just_field` 实际已废弃 |
| `no_outline = 'X'` 单独出现 | `NO_OUTLINE` 的标准配对是 `DO_SUM = 'X' AND NO_OUTLINE = 'X'`（计入总计但不进小计）。单独写 `NO_OUTLINE` 无任何效果 —— 说明作者**本想加合计却漏了 `do_sum`** |
| `cfield = 'MSTOCK'` 无 `ccfield` | 币种/数量参照字段不完整。且结构里**没有计量单位字段**，ALV 只能显示裸数字 |
| 缺 `MSTOCK` 的 `just` | QUAN 字段应 `just = 'X'`（保留 3 位小数），否则显示成整数，库存量看似"对不上" |
| 列缺失 | `EINA` 在结构里但没进目录；`calc_unit_weight` 的结果列根本没有 |
| 缺 `hotspot` | `MATNR` 若要支持双击跳转 MM03/MB23，必须 `key` / `hotspot = 'X'` |
| 文案 | 只给 `SELTEXT_M`（中/短文本里的 M=中? 实为 medium），无 `scrtext_s/l`、无 tooltip、无 `icon_*`/`emphasize`；文案硬编码英文，而数据取的是 `ZH` 描述，语言不一致 |
| 目录结构 | 直接往标准表 `APPEND`，无排序、无分组列、无合计行 —— ALV 里 `sort`/`subtotal` 无法生效 |

### 5.2 `display_alv` 的四重断裂

```abap
  METHOD display_alv.

    DATA lt_stock TYPE ty_stock_tab.
    DATA lv_ok    TYPE abap_bool.

    CREATE OBJECT mo_container
      EXPORTING
        container_name = 'STOCK_AREA'
        repaint_detlevel = 1.

    CREATE OBJECT mo_grid
      EXPORTING
        i_container = mo_container
        ex_initial_layout = '1'.

    mo_grid->set_table_for_first_display(
      CHANGING
        it_outtab        = lt_stock
        it_fieldcatalog  = build_fieldcat( )
      EXCEPTIONS
        program_error = 1
        OTHERS        = 2 ).

    IF sy-subrc <> 0.
      lv_ok = abap_false.
    ENDIF.

    SET HANDLER on_double_click FOR mo_grid.

    CALL SCREEN 0100.
```

1. **⚠️ `lt_stock` 声明后从未被填充**。`collect_stock` / `enrich_text` / `check_capacity` 一个都没调用 → ALV **永远显示空表**。这是"取数链路"与"显示链路"完全断裂。
2. **⚠️ 用了 `it_outtab` 而非 `et_outtab`**：`it_outtab` 传入的是**方法内的局部变量**。ALV 会持有它的数据引用，方法返回后该数据失去语义（虽有引用保活，但用户无法再刷新/排序回写）。正确做法是把数据表做成**类属性** `mt_stock`，用 `et_outtab = mt_stock`。
3. **⚠️ `CALL SCREEN 0100` 在类池里必然失败**。**Global Class Pool 不能包含屏幕**（无 PBO 模块、无 screen 编号）。要么 dump，要么找不到屏幕。ALV 控件还必须在**屏幕显示之后的 PBO** 中创建，否则 `CL_GUI_CUSTOM_CONTAINER` 找不到容器。
   正确架构：ALV 的**屏幕与控件生命周期放在调用方报表程序**（或做成一个独立的**全局 ABAP 对象类型为 Screen/Executable program 的报告**），本类只负责数据，ALV 通过传入的 container 挂载 —— 即 `cl_salv` 风格，或由报表负责 `CALL SCREEN`。
4. **容器名 `'STOCK_AREA'` 硬编码**：本类只能被"恰好有一个名为 `STOCK_AREA` 的自定义控件"（`CL_GUI_CUSTOM_CONTAINER`，需 SE91 中 `ACTIVE` + 已激活）的程序调用。这个隐式契约没有任何文档。
5. **`lv_ok` 设置后从未使用**：`IF sy-subrc <> 0. lv_ok = abap_false. ENDIF.` 之后没有任何分支，**异常被完全吞掉**。应 `MESSAGE id sy-msgid TYPE sy-msgty NUMBER sy-msgno` 或 `RAISE EXCEPTION`。另外 `EXCEPTIONS program_error = 1 OTHERS = 2` 中 `OTHERS` 排在最后是对的，但后面没用 `sy-subrc` 的具体值区分。
6. **`CREATE OBJECT` 无 `EXCEPTIONS`**：容器名不存在时抛 `dynamic_internal_error` / `program_error`（短 dump）。
7. **`SET HANDLER ... FOR mo_grid.` 语法可疑**：正确写法是
   ```abap
   SET HANDLER on_double_click FOR mo_grid
                 DISABLE-INTERRUPTS.
   ```
   或用 `mo_grid->set_event_handler( EXPANDING name = cl_gui_alv_grid=>event_double_click )`。同时**建议注册 `EVENT_DOUBLE_CLICK`**：
   ```abap
   mo_grid->register_event( EXPANDING name = cl_gui_alv_grid=>event_double_click ).
   ```
8. **`ex_initial_layout = '1'`** 但从未设置 `i_save_layout`：如果没有名为 `1` 的 ALV 变式，用户每次都看不到自定义布局。应配 `i_save_layout = 'X'` + `i_default_layout = 'X'` + `is_layout = ls_layout`（或用 Layout 选择按钮）。
9. **没有回调命令**（`i_callback_fcode` / `set_user_command`）：没有 `BACK`、没有导出 Excel、没有任何按钮。报表只能靠 ALV 工具栏图标，功能残缺。
10. **`display_alv` 无入参**：无法传入物料范围/库位/输出数据表，外部只能通过 `constructor(iv_plant)` 传一个工厂 —— **`it_matnr` 根本没有对外入口**，外部根本无法触发取数。API 设计不闭环。

### 5.3 `on_double_click` —— 编译错误 + 调试残留

```abap
  METHOD on_double_click.

    READ TABLE mt_stock INTO ms_stock WITH KEY matnr = iv_data.

    WRITE: / iv_row, iv_column, iv_data.

    CASE iv_column-fieldname.
      WHEN 'MSTOCK'.
        CHECK iv_row > 0.
      WHEN 'NTGEW'.
        MESSAGE 'Weight is maintained in MARA, not per stock record' TYPE 'S'.
    ENDCASE.
```

1. **⚠️ 编译错误：`mt_stock` 与 `ms_stock` 都不存在**。类里没有任何地方声明这两个变量。这是**必现的语法错误**，类根本激活不了。（`ms_plant` / `ms_plants` 是唯一存在的 `ms_*`。）
2. **`WRITE: /` 是调试残留**，应删除。在 ALV 场景下 `WRITE` 写到基本列表，屏幕返回后即丢失，用户根本看不到。
3. **`CASE` 分支什么也没做**：
   - `WHEN 'MSTOCK'. CHECK iv_row > 0.` 只是一个无副作用的空判断；
   - `WHEN 'NTGEW'` 弹一条信息 —— 这不是"交互"，是"提示语"。
   真正有价值的双击行为应该是：跳 MM03（物料主数据）/ MB23（库存清单）/ MMBE（库存概览）。
4. **`iv_data TYPE any` 用于取键很脆弱**：它是单元格的显示值（ALV 内部多为 CHAR），若列有 `key` 建议用 `mo_grid->get_selected_rows` / `event_data` 中的行信息，或直接从 `mt_stock` 取。
5. 未 `CHECK iv_row > 0` 在方法开头，事件参数无效时会越界。
6. 应同时支持 `F4` 帮助 / `hotspot` 单击跳转。

### 5.4 `set_cell_styles` —— 从未使用 + 常量用错命名空间

```abap
    APPEND VALUE #(
      fname       = 'MSTOCK'
      color       = 6
      intens      = 0
      style       = cl_gui_richtext=>strikeout
      lstyle      = cl_gui_richtext=>strikeout_col_neg
      ) TO ct_styling.
```

1. **无人调用**，也没有把它传给 `set_table_for_first_display` 的 `IT_SCOL` → 样式完全不生效。
2. **常量用错类**：ALV 的 `LVC_T_SCOL-STYLE` 属于 `LVC_STYLE4`，对应常量类是 **`cl_gui_alv_styles`**（`=>strikeout` / `=>negated` / `=>fixed` 等），而不是 `cl_gui_richtext`。ALV 不解析 RichText 的样式常量，取值可能编译不过、也可能静默渲染成不可预期的样式。
3. **`color = 6` 是魔法数字**：应使用 `cl_gui_alv_colors=>...`（`col_positive` / `col_negative` / `col_normal` / `col_group`），而不是裸数字。
4. **无条件给整列加删除线**且**没有任何图例**：用户无法判断删除线代表"被冻结/超容/已作废"。ALV 报表的视觉语义必须有说明。
5. `CT_STYLING` 命名可以，但既然要按"行"区分（只有超容行才高亮），更合适的做法是按 `nrow` 生成动态样式，并配合 `it_scol` 传入。

---

## 六、问题清单（按严重度分级）

### P0 —— 阻断激活 / 必现 Dump

| # | 位置 | 问题 |
|---|---|---|
| 1 | `on_double_click:230` | `mt_stock`、`ms_stock` 未声明 → **编译错误** |
| 2 | `collect_stock:88-92` | 只 `FROM mard` 却选 `eina`/`ntgew`（MARA 字段）→ SQL 不成立 |
| 3 | `check_capacity:144` | `mard-mvbeln` 不是有效字段；且未判 `sy-subrc` → 未命中即把全表库存置 0 |
| 4 | `enrich_text:118` | `MODIFY ct_stock FROM ls_row` 用在 `WITH EMPTY KEY` 表上 → 无法定位行（编译/运行错误） |
| 5 | `calc_unit_weight:128` | `CHAR`(eina) 赋给 `TYPE p` → 类型不兼容（编译错误） |
| 6 | `display_alv:223` | `CALL SCREEN 0100` —— **类池中不存在屏幕 0100** → dump |
| 7 | `display_alv:199-202` | 容器 `'STOCK_AREA'` 不存在时 `CREATE OBJECT` 短 dump（无 EXCEPTIONS） |

### P1 —— 业务正确性 / 数据可信度

| # | 位置 | 问题 |
|---|---|---|
| 8 | `check_capacity:147-151` | **静默覆盖真实库存数量**，用户看到的不是真值 |
| 9 | `calc_unit_weight:135` | `ntgew / eina`（净重 ÷ EAN 号）业务上无意义 |
| 10 | `collect_stock:92` | `it_matnr` 为空 → **导出该工厂全量库存**，无任何提示 |
| 11 | `enrich_text:109-113` | FAE 前无空表守卫 → 空表时行为未定义/dump |
| 12 | 全局 | 输出结构**无计量单位 / 重量单位**字段 → 报表数值不可解读 |
| 13 | `collect_stock:88` | 真 SELECT **无库位过滤**，与 `check_capacity(iv_warehouse)` 及死字符串里的意图脱节 |
| 14 | `enrich_text:113` | 语言硬编码 `'ZH'` 且无回退 → 描述空白 |
| 15 | `set_cell_styles` | 删除线样式**无图例**，语义不可知 |

### P2 —— 性能 / 可维护性

| # | 问题 |
|---|---|
| 16 | `enrich_text:115-119` 每行一次 `READ TABLE ... WITH KEY matnr`（非键字段）→ O(n²)；且整行拷进拷出 |
| 17 | `build_fieldcat` 的 `tabname = 'TY_STOCK'` 硬编码 local type → ALV 字段目录解析风险 |
| 18 | `ref_field` 自引用、`just_field` 无效、`no_outline` 缺 `do_sum`、`cfield` 缺 `ccfield` → 目录属性失效 |
| 19 | `display_alv` 用 `it_outtab` 传局部表 → 无法回写/刷新 |
| 20 | `display_alv` 吞掉异常（`lv_ok` 未使用） |
| 21 | 无 `PACKAGE SIZE`、无行数上限 → 大结果集内存风险 |
| 22 | **8 个方法中 4 个是死代码**（`collect_stock`/`enrich_text`/`calc_unit_weight`/`check_capacity`/`set_cell_styles`） |
| 23 | 属性 `ms_plants` 未使用 |
| 24 | `RAISING cx_sy_move_cast_error` 永不抛出；`iv_warehouse_range` 不存在于签名 |
| 25 | 无专用异常类、无单元测试、无 `ALLOWED`/`DETERMINISTIC`、无工厂方法 |
| 26 | 死 SQL 字符串含未转义拼接 → 未来的 SQL 注入隐患 |
| 27 | 命名规范：`mo_grid`/`mo_container` 应为 `ms_grid`/`ms_container`；`lv_ok` 未用；`WRITE:` 残留 |
| 28 | 取数/计算/展示三层揉在一个 `FINAL` 全局类中，违反单一职责；`FINAL` 也无法被继承扩展 |

---

## 七、改进建议与改造路线

### 7.1 目标架构（分离三层）

```
[调用方报表 ZCL_STOCK_CHECK_MAIN]        ← 屏幕 0100 + STOCK_AREA 容器 + ALV 控件生命周期
        │  传 container / 传 it_matnr
        ▼
[ZCL_STOCK_CHECK  (逻辑层，可留全局类)]   ← 取数 + 关联 + 计算，不碰任何 GUI API
        │  返回结构化结果 + 计算结果
        ▼
[ZCL_STOCK_CHECK_PRES (展示层，可选)]    ← build_fieldcat + 事件处理（依赖 LVC）
```

关键原则：**逻辑层禁止出现 `MESSAGE` / `WRITE` / `CALL SCREEN` / 控件引用**，需要反馈就抛自定义异常。

### 7.2 分步改造（建议顺序）

**Step 1 —— 先让它能编译（P0 全部清零）**

```abap
" 1) 定义专用异常类，替代过度的 cx_sy_move_cast_error
CLASS zcx_stock_check DEFINITION PUBLIC INHERITING FROM cx_static_check FINAL.
  PUBLIC SECTION.
    METHODS constructor IMPORTING iv_text TYPE string OPTIONAL.
  PRIVATE SECTION.
    DATA mv_text TYPE string.
ENDCLASS.

" 2) 修正取数：JOIN 取 MAKTX，字段归属正确
METHOD collect_stock.
  IF it_matnr IS INITIAL.
    RAISING EXCEPTION zcx_stock_check
      EXPORTING iv_text = `必须至少输入一个物料号。`.
  ENDIF.

  SELECT m~matnr m~lgort m~mstock a~maktx a~eina a~ntgew
         a~brgew a~gewei a~msehi
    FROM mard AS m
    INNER JOIN mara AS a ON a~matnr = m~matnr
    LEFT OUTER JOIN makt AS t ON t~matnr = a~matnr AND t~spras = @lv_spras
    INTO TABLE @DATA(lt_stock)
    WHERE m~werks  = @ms_plant
      AND m~lgort IN @it_lgort
      AND m~matnr IN @it_matnr
    PACKAGE SIZE 5000.
ENDPACKAGE.   " 需要内表声明在方法外/属性，或去掉 PACKAGE
```

```abap
" 3) 关联改用 SORTED TABLE + ASSIGNING，去掉 O(n^2) 与非法 MODIFY
METHOD enrich_text.
  IF ct_stock IS INITIAL.
    RETURN.
  ENDIF.

  SORT lt_text BY matnr.
  LOOP AT ct_stock ASSIGNING FIELD-SYMBOL(<ls>).
    READ TABLE lt_text INTO DATA(ls_text) WITH TABLE KEY matnr = <ls>-matnr.
    IF sy-subrc = 0.
      <ls>-maktx = ls_text-maktx.
    ENDIF.
  ENDLOOP.
ENDMETHOD.
```

**Step 2 —— 修业务逻辑（P1）**

- **加计量单位字段**：`msehi TYPE mara-msehi`、`gewei TYPE mara-gewei`、`brgew`，数量/重量列必须带单位。
- **`check_capacity` 改为标记而非覆盖**：
  ```abap
  " 结构中新增 over_cap TYPE abap_bool，不再动 mstock
  IF <ls>-mstock > ls_cap.
    <ls>-over_cap = abap_true.
  ENDIF.
  ```
  先与业务确认"容量"数据来源（标准表没有可靠的库位容量字段，通常是 `LAGG`+自定义配置表）。
- **单位重量公式纠正**：用 `brgew / bwbes`（毛重 / 毛重基本单位）或 `ntgew / umrez`，并同时输出 `gewei`。
- **空输入守卫**：所有对外方法先校验必填参数；`it_matnr` 空则报错。
- **`lv_slots` 改成 `TYPE mard-mstock`**，并判 `sy-subrc`（未命中 → 不做任何裁剪，报错）。

**Step 3 —— ALV 正确化（P2）**

```abap
METHOD display_alv.
  DATA(lo_grid) = me->ms_grid.
  ...
  FIELD-SYMBOLS <lt_stock> TYPE ty_stock_tab.

  LOOP AT mt_stock ASSIGNING <lt_stock>.
    me->set_cell_styles( is_row = <lt_stock> CHANGING ct_styling = lt_scol )
      ...   " 或整表统一生成
  ENDLOOP.

  lo_grid->set_table_for_first_display(
    EXPORTING
      i_save_layout = 'X'
      i_default_layout = 'X'
      is_layout      = ls_layout
      i_callback_fcode = 'BACK'
    CHANGING
      et_outtab       = mt_stock          " ← 关键：et_outtab + 类属性
      it_fieldcatalog = build_fieldcat( )
      it_scol         = lt_scol
    EXCEPTIONS program_error = 1 OTHERS = 2 ).

  IF sy-subrc <> 0.
    MESSAGE id sy-msgid TYPE 'E' NUMBER sy-msgno.
  ENDIF.

  lo_grid->register_event( EXPANDING name = cl_gui_alv_grid=>event_double_click ).
  lo_grid->set_event_handler( EXPANDING name = cl_gui_alv_grid=>event_double_click
                                       handler = me->on_double_click ).
ENDMETHOD.
```

`build_fieldcat` 简化（去掉 `tabname`/`ref_field`）：

```abap
APPEND VALUE #(
  fieldname = 'MATNR'
  reptext   = '物料'
  key       = 'X'
  hotspot    = 'X'                    " ← 支持双击跳转
  icon_text = 'X'
  just      = 'X' ) TO rt_fieldcat.

APPEND VALUE #(
  fieldname  = 'MSTOCK'
  reptext    = '库存数量'
  cfield     = 'MSTOCK'
  prcurrency = 'X'
  ref_field  = 'MSEHI'                " ← 单位列（若有）
  just       = 'X'
  do_sum     = 'X'
  no_outline = 'X' ) TO rt_fieldcat.  " ← 合计：与 do_sum 配对
```

**Step 4 —— 补齐功能与工程化**

- 双击 → `CALL TRANSACTION 'MM03'` / `'MB23'` 携带 `matnr`，`SET PARAMETER ID 'MAT' FIELD ...`。
- 增加 `BACK` / 导出 Excel / `F4` 帮助按钮。
- 把 `collect_stock` 等的 `MESSAGE` 全部移除，改为抛 `zcx_stock_check`。
- 删除所有死代码与 `WRITE:` 调试残留。
- 补单元测试（用 `cl_abap_unit_test`，覆盖空输入、无结果、单位换算、超容标记）。
- 若是长期演进对象，考虑**拆成 `ZCL_STOCK_CHECK`（逻辑）+ `ZCL_STOCK_CHECK_PRES`（展示）** 两块，并去掉 `FINAL` 以便扩展（`FINAL` 全局类在测试替身与扩展场景下很不友好）。

### 7.3 最小可运行的 ALV 骨架（参考写法）

供对比参考 —— 正确的"报表程序 + 全局类"分工：

```abap
" ZCL_STOCK_CHECK —— 只做数据，不碰 GUI
CLASS zcl_stock_check DEFINITION PUBLIC FINAL CREATE PUBLIC.
  PUBLIC SECTION.
    TYPES ty_stock_tab TYPE STANDARD TABLE OF ty_stock WITH EMPTY KEY.
    METHODS constructor IMPORTING iv_plant TYPE werks.
    METHODS collect_stock
      IMPORTING it_matnr TYPE mara-matnr_tab
      RETURNING VALUE(rt_stock) TYPE ty_stock_tab
      RAISING zcx_stock_check.
ENDCLASS.

" ZCL_STOCK_CHECK_MAIN —— 屏幕 0100 + STOCK_AREA + 控件
REPORT zcl_stock_check_main.
DATA gt_stock TYPE zcl_stock_check=>ty_stock_tab.

START-OF-SELECTION.
  " 选择屏幕取值 → 调用类取数 → 存 gt_stock

PBO 0100.
  IF gr_grid IS INITIAL.
    CREATE OBJECT gr_container:
      EXPORTING container_name = 'STOCK_AREA' repaint_detlevel = 1
      EXCEPTIONS dynamic_internal_error = 1
                 program_error        = 1
                 others               = 2.
    CREATE OBJECT gr_grid:
      EXPORTING i_container = gr_container ex_initial_layout = '1'.
    SET HANDLER on_double_click FOR gr_grid.
  ENDIF.

MODULE ...
ENDMODULE.  " set_table_for_first_display( et_outtab = gt_stock )
```

---

## 八、Onboarding 速记（给新人的 6 句话）

1. 这个类**当前无法激活**，编译错误至少 3 处，`mt_stock` / `ms_stock` 是最明显的一处。
2. 它的**取数链路和显示链路是断开的**：`collect_stock` / `enrich_text` / `check_capacity` 都没有被调用，ALV 的数据源是一个永远为空的局部变量。
3. 最有业务价值的发现是：**`ntgew / eina` 的公式不对**（EAN 不是数量基数），以及 **`check_capacity` 会把真实库存改写成容量值**——后者会让这份报表不能用于对账。
4. **全局类池不能有屏幕**，`CALL SCREEN 0100` 必须移交给调用方报表程序；容器名 `STOCK_AREA` 是隐式契约。
5. 字段目录里 `tabname = 'TY_STOCK'`（local type）、`ref_field` 自引用、`no_outline` 单独出现，都是无效写法，需要精简。
6. **34% 的方法是死代码**（8 个 public 里 5 个没人调），接手后第一步应该做的是：删除死代码 + 拆分"逻辑/展示"两层，而不是继续在现有结构上加功能。

---

*报告基于静态代码阅读得出；所有标注"需确认"的结论（`mara-matnr_tab`、`mard-mvbeln`、屏幕 0100、容器 `STOCK_AREA`、容量数据来源）请在 SE38 / SE11 / SE91 中实机验证后再定稿。*