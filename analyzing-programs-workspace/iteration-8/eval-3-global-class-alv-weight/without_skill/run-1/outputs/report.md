# ZCL_STOCK_CHECK 全局类 Onboarding 分析报告

> 分析对象：`zcl_stock_check.clas.abap`（MM Reporting team，CLASS-POOL，256 行）
> 分析维度：业务问题 / 类结构 / 取数逻辑 / ALV 显示流程 / 问题清单与改进建议

---

## 0. 一句话结论（TL;DR）

这个类想做一个「原材料库存 + 重量合理性检查」的 ALV 报表，但**当前源码无法通过编译**：取数 SQL 查了 `MARD` 上不存在的 `EINA/NTGEW`，事件回调里引用了不存在的属性 `MT_STOCK/MS_STOCK`；即使忽略编译错误，业务语义上「单位重量 = 毛重 / EAN 编码」本身就是错的，`check_capacity` 会静默篡改真实库存量，ALV 数据用了方法内局部变量导致排序/筛选不落库。

**这意味着：你手里这份源码大概率不是系统里正在跑的那份。** 接手第一步不是读代码，而是在 SE24 里确认实际激活版本、比对 `git`/版本管理记录，并找原开发者确认线上行为。

---

## 1. 业务问题

| 维度 | 内容 |
| --- | --- |
| 业务场景 | MM 原材料（`MARD`/`MARA`）库存数量与重量的一致性体检 |
| 目标用户 | 计划员 / 物料主数据与库存报表岗（`spras = 'ZH'`，说明面向中文环境） |
| 期望产出 | 一个可排序、可下钻、按行着色的 ALV Grid，展示物料号、描述、库位、库存量、毛重，并提示「重量维护在 MARA 而非库存记录上」 |
| 隐含业务规则 | ①每个物料的毛重（`MARA-NTGEW`，kg）是**物料级**属性，不是库存记录级属性；②库存量不应超过某个「容量」上限；③物料描述需从 `MAKT` 补全 |
| 核心设计意图 | 类承担「取数 → 富化 → 派生计算 → 校验 → 展示」全链路，是典型的 **Fiori/报表式 PC 端工具类**，而非可复用 Domain Service |

**业务价值判断：** 场景本身合理（上线前/周期性数据体检，排查手工改库存、毛重未维护、单位换算错误）。但当前实现把「展示」「提示」「数据清洗」耦合在一个类里，导致它既不能被其他报表复用，也不能被单元测试覆盖。

---

## 2. 类结构

```abap
CLASS-POOL zcl_stock_check.          " ← 类池：全局类不该放在 CLASS-POOL 里
PUBLIC FINAL CREATE PUBLIC.

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

    METHODS constructor      IMPORTING iv_plant TYPE werks OPTIONAL.
    METHODS collect_stock    IMPORTING it_matnr TYPE mara-matnr_tab
                             RETURNING VALUE(rt_stock) TYPE ty_stock_tab
                             RAISING cx_sy_move_cast_error.
    METHODS enrich_text      CHANGING ct_stock TYPE ty_stock_tab.
    METHODS calc_unit_weight IMPORTING is_row TYPE ty_stock
                             RETURNING VALUE(rv_uw) TYPE p DECIMALS 4.
    METHODS check_capacity   IMPORTING iv_warehouse TYPE mard-lgort
                             CHANGING  ct_stock    TYPE ty_stock_tab.
    METHODS build_fieldcat   RETURNING VALUE(rt_fieldcat) TYPE lvc_t_fcat.
    METHODS display_alv.
    METHODS on_double_click  IMPORTING iv_row lvc_row iv_column lvc_col
                                       iv_data   any.
    METHODS set_cell_styles  IMPORTING is_row TYPE ty_stock
                             CHANGING ct_styling TYPE lvc_t_scol.

  PRIVATE SECTION.
    DATA ms_plant    TYPE werks.
    DATA ms_plants   TYPE werks_tab.      " 声明了，从未使用
    DATA mo_grid     TYPE REF TO cl_gui_alv_grid.
    DATA mo_container TYPE REF TO cl_gui_custom_container.
ENDCLASS.
```

### 2.1 方法清单与职责

| 方法 | 期望职责 | 实际状态 | 可测性 |
| --- | --- | --- | --- |
| `constructor` | 保存工厂 | 只保存单个工厂；`ms_plants` 从未填充，暗示原本想做多工厂 | ✅ |
| `collect_stock` | 按工厂 + 物料范围取库存 | **编译不过**；构造了 SQL 字符串却从不执行；范围参数丢失 | ❌ 强耦合 DB |
| `enrich_text` | 用 `MAKT` 补物料描述 | **逻辑错误**：`MODIFY ... FROM` 会污染整表 | ❌ 强耦合 DB |
| `calc_unit_weight` | 计算单位重量 | **语义错误 + 从未被调用** | ✅（修正后） |
| `check_capacity` | 容量上限校验 | **静默改写 `MSTOCK`**，破坏「检查」语义 | ❌ 强耦合 DB |
| `build_fieldcat` | 构造 ALV 字段目录 | `TABNAME='TY_STOCK'` 配置错误；列不全 | ✅ 纯逻辑 |
| `display_alv` | 组装并显示 ALV | **从未调用 `collect_stock`**；数据用局部变量；`CALL SCREEN` 位置错误 | ❌ |
| `on_double_click` | 双击下钻 | **引用不存在的属性 → 编译不过**；`WRITE` 破坏 UI | ❌ |
| `set_cell_styles` | 单元格着色 | **从未被调用**；样式常量用错 | ✅ |

**关键观察：9 个 public 方法中，有 5 个（`collect_stock` 之外的取数链、`calc_unit_weight`、`check_capacity`、`set_cell_styles`、`on_double_click` 的分支）从未被任何方法调用。** 这是一个「骨架先行、业务逻辑未接完」的半成品。

### 2.2 状态管理问题

- **无数据状态**：`display_alv` 声明的是方法内局部变量 `lt_stock`，而 `on_double_click` 却去读一个本该存在的属性 `mt_stock` —— 作者中途把状态从「类属性」改成「局部变量」但没改干净。
- **控件状态**：`mo_grid` / `mo_container` 是**类属性**。全局类在一个会话内只能 `CREATE` 一次实例，第二次调用 `display_alv` 会重置 `mo_container`，导致第一次显示的 ALV 失去容器而短错误（`OBJECT_NOT_IN_ACTIVE_MODE` / `CONTAINER_NAME_DOES_NOT_EXIST`）。控件生命周期应该属于调用方（程序/报告），不属于这个可复用的类。
- **`CALL SCREEN 0100` + `CONTAINER_NAME = 'STOCK_AREA'`**：屏幕 0100 与该自定义控件均未在本类池中提供。类池没有 flow logic 时，`CALL SCREEN` 在方法内不会真正处理屏幕流，运行必然在 `CREATE OBJECT mo_container` 处失败。

---

## 3. 取数逻辑

### 3.1 作者的意图 vs 实际代码

```abap
METHOD collect_stock.
  DATA lv_sql TYPE string.

  lv_sql = |SELECT mard~lgort mard~mstock mara~eina mara~ntgew mara~matnr|
         && |  FROM mard INNER JOIN mara ON mara~matnr = mard~matnr|
         && | WHERE mard~werks = '{ ms_plant }'|
         && |   AND mard~lgort IN iv_warehouse_range( )|.     " ← 死代码，从未执行

  SELECT matnr lgort mstock eina ntgew
    FROM mard                                                " ← EINA/NTGEW 不在 MARD 上
    INTO TABLE rt_stock                                      " ← 目标表 WITH EMPTY KEY
    WHERE werks  = ms_plant
      AND matnr IN it_matnr.                                  " ← 空区间 = 不过滤！
ENDMETHOD.
```

三点必须讲清楚：

**① `lv_sql` 是纯死代码。** `IN iv_warehouse_range( )` 写在字符串模板里，属于**字面文本**（模板里只有 `|{ }|` 和 `\n` 是特殊语法），所以**编译器不会报错**，这段 SQL 永远不会执行。库位范围筛选能力被静默丢失了 —— 这是最典型的「重构到一半」的证据。

**② 真正的 SQL 是错的。** `EINA`（EAN 条码）与 `NTGEW`（毛重）都只存在于 `MARA`，`MARD` 只有 `MSTOCK` 等库存字段。`SELECT ... FROM mard` 里列这两个字段是**编译错误**。正确写法必须 `MARD INNER JOIN MARA ON MATNR`，或读两次再按 `MATNR` 合并。

**③ `IN it_matnr` 空区间陷阱（最高危的运行时风险）。** ABAP 中 `WHERE matnr IN lt_empty` 不构成任何过滤条件，等价于「全表」。`ty_stock` 无任何工厂/库位下推限制时，这会变成 **MARD 全表扫描**（生产系统通常百万级），程序挂死或内存溢出。若 `it_matnr` 恒为初始值，则该方法 100% 触发。

**④ 无效空转循环。**

```abap
LOOP AT rt_stock ASSIGNING FIELD-SYMBOL(<ls>).
  <ls>-matnr = <ls>-matnr.        " 自赋值，编译器可能警告，实际什么也没做
ENDLOOP.
```

原本应该是在这里填 `LGORT` 或派生字段（例如单位重量），实现被清空但壳留下了。

**⑤ RETURNING 参数上做 MESSAGE。**

```abap
IF rt_stock IS INITIAL.
  MESSAGE 'No stock records found' TYPE 'S'.   " 方法里弹消息 = 越权 UI
ENDIF.
```

`collect_stock` 是一个 `RETURNING` 方法，却在替调用方决定「弹什么消息、什么消息类」。后果：该方法无法在后台、无法在 ALV 刷新回调、无法被其他报表复用时安全调用；测试时还会往屏幕弹框。正确做法是「返回空表，调用方判断并提示」。

**⑥ `RAISING cx_sy_move_cast_error` 是摆设。** 方法体内没有任何可能抛出该异常的语句，调用方（`display_alv`）也没 `EXCEPTIONS`。异常契约名存实亡，反而误导阅读者以为这里有类型转换风险。

### 3.2 描述补全 `enrich_text` —— 一个会毁掉全部数据的 Bug

```abap
DATA lt_text TYPE TABLE OF makt.                    " 全量 MAKT 结构，浪费内存

SELECT matnr maktx FROM makt
  INTO TABLE lt_text
  FOR ALL ENTRIES IN ct_stock
  WHERE matnr = ct_stock-matnr
    AND spras = 'ZH'.                               " 语言硬编码

LOOP AT ct_stock INTO DATA(ls_row).
  READ TABLE lt_text INTO DATA(ls_text) WITH KEY matnr = ls_row-matnr.
  ls_row-maktx = ls_text-maktx.                    " 未检查 sy-subrc / sy-tabix
  MODIFY ct_stock FROM ls_row.                     " ← BUG
ENDLOOP.
```

**核心缺陷：`ct_stock` 的类型是 `WITH EMPTY KEY`。** 而 `MODIFY itab FROM wa` 是**按键匹配**的。对于无键表，ABAP 规定所有行都「匹配」，于是每循环一次都会把 `ct_stock` 的**全部行**覆盖成当前这一行的内容。循环结束后，**每一行的 `MAKTX` 都等于最后一条记录的描述**。

这类 Bug 的恶劣之处：数据量越大越不容易被发现（末尾一行的描述恰好正确），截图给业务看时只有末行「看起来正常」。

次生问题：

- `READ TABLE ... WITH KEY matnr` 依赖 `MAKT` 的 DDIC 键（`MATNR` + `SPRAS`）做二分查找；一旦有人改成 HASHED 或加了 `TYPE makt-matnr_tab`，行为就会变。应显式定义 `ty_text_tab TYPE STANDARD TABLE OF ty_text WITH NON-UNIQUE SORTED KEY key_matnr COMPONENTS matnr`。
- 未检查查找结果：查不到时 `ls_text` 是未初始化的内联结构，`MAKTX` 被静默写成空串。
- `DATA(ls_row)` 是**值传递**：每轮把整行结构（`MARD-MSTOCK` 等 P 类型 + `EINA` CHAR 37）整体读写，效率低。应为 `ASSIGNING FIELD-SYMBOL`。
- `lt_text TYPE TABLE OF makt` 装载了 MAKT 的**全部字段**（上百个），而实际只用 2 个。应定义 2 字段的局部结构。

### 3.3 `calc_unit_weight` —— 语义彻底错误

```abap
DATA lv_base TYPE p DECIMALS 4.
lv_base = is_row-eina.          " EINA = EAN 条码（CHAR 37），不是基准单位！
IF lv_base IS INITIAL.
  rv_uw = 0. RETURN.
ENDIF.
rv_uw = is_row-ntgew / lv_base. " 毛重(kg) ÷ 商品条码
```

三个层次的问题，从表到里：

1. **业务层面（致命）：** `EINA` 是 EAN-13 条码，`NTGEW` 是物料毛重（kg）。`35.5 / 6901234567892 = 0.0000051` —— 这个数字没有任何业务含义。「单位重量」的正确分母应当是**基本计量单位下的数量**：要么用 `MARA-MEINS`（基本单位）+ 该库存记录换算到基本单位的数量（需 `MARD-UMREZ/UMREN` 或直接读 `MARD` 换算后字段），要么用 `MARA-NORL`（数量单位组）查单位换算表。**按 EAN 除是纯粹的误用。**
2. **类型层面：** 把 `CHAR 37` 的 EAN 隐式转换成 `P DECIMALS 4`，非数字内容会静默变成 0，长度还会被截断；紧接着的 `IS INITIAL` 只是「碰巧」把 0 挡了下来。任何以数字开头的 EAN 都会算出垃圾值。转换应当走 `CONV` 或先校验格式。
3. **契约层面：** 方法从未被调用，ALV 里也没有「单位重量」列。整个「重量检查」功能**目前是关闭的**。

### 3.4 `check_capacity` —— 一个名为「检查」实为「篡改」的方法

```abap
DATA lv_slots TYPE i.
SELECT SINGLE mstbw FROM mard-mvbeln INTO @lv_slots
  WHERE werks = ms_plant AND lgort = iv_warehouse.
LOOP AT ct_stock ASSIGNING FIELD-SYMBOL(<ls>).
  IF <ls>-mstock > lv_slots.
    <ls>-mstock = lv_slots.       " 直接覆盖真实库存量！
  ENDIF.
ENDLOOP.
```

- **语义错误：** `MARD-MVBELN`（销售订单）是销售域字段，与「库位容量」毫无关系（该字段是否真为 MARD 组件需在 SE36 确认，但无论如何都不是容量）。语义上应该用自定义容量表 / `LGPROD`（生产存储库位）/ 库位主数据扩展，或干脆去掉这个功能。
- **类型错误：** 目标是 `TYPE i`，源是 `QUAN`（带 3 位小数）。QUAN → INT 会截断，金额/数量场景下应保持 `QUAN` 类型。
- **设计错误（最严重）：** 一个「check_」开头的方法 **修改了被检查的数据**，且无返回值、无标记、无日志。用户无法区分「库存本来就低」和「我这里被截断了」。报表类代码静默改数据是审计红线 —— 一旦接上 `display_alv`，用户看到的就是**假库存**。
- **命名错误：** 形参叫 `iv_warehouse`，类型却是 `mard-lgort`（**库位**，不是仓库）。`MARD` 没有工厂级仓位概念。

### 3.5 取数性能评估

| 项 | 评价 |
| --- | --- |
| `MARD` 无库位下推 | 慢 10~100 倍，MARD 冗余度极高 |
| 物料范围可空 | 空区间 → 全表扫描 |
| 物料描述二次查询 | `FOR ALL ENTRIES` 思路正确，但应用 2 字段局部结构 + 非空/去重守卫 |
| `NTGEW`/`EINA` 取自 MARA | 需要 JOIN 或二次合并；更好的方案是 CDS View（`MM_Stock_Sum` / 自建） |
| 无 `SELECT SINGLE` 判空 | 空结果与「查不到」混为一谈 |

---

## 4. ALV 显示流程

### 4.1 期望流程 vs 实际流程

```
期望：constructor(工厂)
        ↓
      collect_stock(物料范围) → enrich_text → calc_unit_weight → check_capacity
        ↓
      build_fieldcat + set_cell_styles
        ↓
      CL_GUI_ALV_GRID + 屏幕 0100 + on_double_click
        ↓
      双击 → on_double_click 下钻

实际：constructor(工厂)
        ↓
      （空）lt_stock   ← 从未赋值的初始内表
        ↓
      build_fieldcat  ← 错误 TABNAME
        ↓
      CREATE mo_container  ← 屏幕 0100 / STOCK_AREA 不存在，此处即失败
        ↓
      set_table_for_first_display
        ↓
      SET HANDLER（注册在首次显示之后）
        ↓
      CALL SCREEN 0100  ← 类方法内无法处理屏幕流
```

### 4.2 `display_alv` 逐行剖析

```abap
DATA lt_stock TYPE ty_stock_tab.      " ❌ 数据放在方法局部变量
DATA lv_ok    TYPE abap_bool.         " ❌ 赋值后从未被读取

CREATE OBJECT mo_container EXPORTING container_name = 'STOCK_AREA'
                                  repaint_detlevel = 1.   " ❌ 无对应屏幕/控件

CREATE OBJECT mo_grid EXPORTING i_container = mo_container
                                 ex_initial_layout = '1'. " ❌ 容器无效时必然抛异常

mo_grid->set_table_for_first_display(
  CHANGING it_outtab = lt_stock it_fieldcatalog = build_fieldcat( )
  EXCEPTIONS program_error = 1 OTHERS = 2 ).

IF sy-subrc <> 0.
  lv_ok = abap_false.                 " ❌ 吞掉异常：无 MESSAGE、无日志、无返回
ENDIF.

SET HANDLER on_double_click FOR mo_grid.   " ⚠ 在首次显示后才注册
CALL SCREEN 0100.                          " ❌ 类方法内不能驱动屏幕流
```

关键问题：

**① 数据用了方法局部变量。** ALV 拿到的是 `lt_stock` 的数据引用。方法 `ENDMETHOD` 返回后，该内表虽因引用计数未立即释放，但 ALV 的排序/筛选/合计结果**无法回写**到调用方的数据表（`refresh_table_display` 需要重新传入同一内表）。用户排个序、筛一下，数据就「丢」了 —— 这是 `CL_GUI_ALV_GRID` 最经典的坑之一。正确做法是把内表提升为类属性或由调用方（报表）持有。

**② `build_fieldcat` 里 `TABNAME = 'TY_STOCK'`。** 这是把「DDIC 结构/表名」与「字段名」配对的遗留写法。数据来自 `it_outtab` 的局部内表，ALV 只需要 `FIELDNAME`；`TABNAME='TY_STOCK'` 指向的 DDIC 对象不存在，运行时会得到转换错误或字段无法解析。对单内表 ALV，正确写法是：

```abap
APPEND VALUE #( fieldname = 'MATNR'
               ref_field = 'MATNR'
               seltext_m = '物料号'
               just_field = 'X' ) TO rt_fieldcat.
```

**③ 字段目录的其它缺口：**

| 缺口 | 影响 |
| --- | --- |
| 没有 `EINA` 列 | 取了却不用（正是 unit_weight 误用的产物） |
| 没有「单位重量」列 | `calc_unit_weight` 的成果无处展示 |
| 没有 `MSTOCK` 的 `just_field`/数值格式 | 数量列左对齐，可读性差；`NTGEW` 是 QUAN，未配小数位 |
| `cfield = 'MSTOCK'` 但无 `sort` 表 | `CTEXT` 无对应排序文本，排序行为不确定 |
| `no_outline = 'X'` 只加在 MSTOCK | 视觉上莫名其妙地少一条框线 |
| 文本硬编码英文（`'Material'`） | 违反 SAP 文本规范（应用文本符号 `CC01~CCNN`），`SPRAS='ZH'` 却显示英文 |
| 无 `lvc_t_layf`（`zebra`、`totals`、`grid_title`） | ALV 无斑马纹、无合计行、无标题 |

**④ `SET HANDLER` 位置。** 应在 `CREATE OBJECT` 之后、`set_table_for_first_display` 之前注册。当前写法把事件挂在了「已经显示完」的网格上，标准做法是配合 `grid->set_event_ready` 或直接提前注册，避免首次显示期间事件丢失。

**⑤ 异常被彻底吞掉。** `EXCEPTIONS program_error = 1 OTHERS = 2` 之后只把 `lv_ok` 置 `abap_false`，然后丢掉。`lv_ok` 是死变量。正确做法：`MESSAGE lv_text TYPE 'S'`（`TYPE REF TO lvc_s_fmsg`）或 `RAISING zcx_stock_check`。

**⑥ `CALL SCREEN` 位置根本性错误。** 全局类没有 flow logic，无法「处理」屏幕；屏幕 0100 与容器 `STOCK_AREA` 也不存在。对于这类一次性报表，标准答案不是自建 ALV Grid，而是 **`cl_salv_table` + `salv_table_display`**，或干脆做成独立的 ABAP List 报表 + `REUSE_ALV_GRID_DISPLAY`（自带 flow logic、自带屏幕适配、自带工具栏/布局/变式）。当前写法相当于「用 200 行手搓一个本该 30 行解决的事」。

### 4.3 `on_double_click` —— 无法编译 + 破坏 UI

```abap
METHOD on_double_click.
  READ TABLE mt_stock INTO ms_stock WITH KEY matnr = iv_data.  " ❌ 两者均未声明
  WRITE: / iv_row, iv_column, iv_data.                        " ❌ 事件里 WRITE = 弹屏/短错误
  CASE iv_column-fieldname.
    WHEN 'MSTOCK'.
      CHECK iv_row > 0.                                        " ❌ 回调里 CHECK 失败 = 短错误
    WHEN 'NTGEW'.
      MESSAGE 'Weight is maintained in MARA, not per stock record' TYPE 'S'.
  ENDCASE.
ENDMETHOD.
```

- **编译错误：** `MT_STOCK`、`MS_STOCK` 不是类属性，`display_alv` 里只有局部 `LT_STOCK`。这行代码单独就能让整个类无法激活。
- **设计错误：** 从事件参数 `iv_data` 里拿到的是**单元格值**（`ANY`），不是行对象，却拿它当 `MATNR` 去做表键匹配；且目标表无键，`WITH KEY` 语义不成立。正确做法是把 `it_outtab` 提升为类属性，用 `READ TABLE mt_stock INDEX ...`，或直接用事件第 4 参数 `lvc_et_row_no` 拿索引。
- **`WRITE` 在 ALV 事件里是严重违规**：会覆盖/遮挡 Grid，短错误 `CONVT_...`，或者直接让 ALV 失去焦点。事件回调里只允许弹 Message、设置单元格属性、触发导航。
- **`CHECK` 在回调里失败即抛 `CX_SY_NO_CHECK`** → ALV 现场短错误，SAP 内核还会把 `CHECK` 的失败记到编辑器检查器里。
- **交互缺失：** 方法名叫 `on_double_click`，但没有任何真正的下钻。应改成 `on_double_click` → `SET PARAMETER ID matnr/matnr` + `CALL TRANSACTION mm03` 或打开 CDS View。
- **`NTGEW` 的提示文案是全类唯一「有业务味道」的交互**，说明作者清楚 `NTGEW` 来自 MARA，却又在 `calc_unit_weight` 里拿它去除以 EAN —— **前后矛盾**。

### 4.4 `set_cell_styles` —— 从未接线，样式常量也用错了

```abap
APPEND VALUE #( fname  = 'MSTOCK'
                color  = 6
                intens = 0
                style  = cl_gui_richtext=>strikeout        " ❌ 应为 CL_GUI_TABLE_STYLE
                lstyle = cl_gui_richtext=>strikeout_col_neg ) TO ct_styling.
```

- `CL_GUI_RICHTEXT` 是富文本编辑器的常量集，ALV 单元格样式应使用 **`CL_GUI_TABLE_STYLE=>BOLD/ITALIC/UNDERLINE/STRIKEOUT`**（值 1~4）；`style = 6` 不是合法样式值。
- **「删除线永远标在库存量上」** 这个 UI 设计本身不可解释（删除线通常表示失效/冻结，标在所有真实库存上会误导用户）。
- 该方法从未被 `display_alv` 调用；且 `lvc_t_scol` 需要在 `set_table_for_first_display` 的 `it_special_groups`/`refresh_table_display` 链路里下发，单纯 `APPEND` 到一个 CHANGING 内表不会有任何效果。
- 形参 `is_row` 完全未使用 → 说明它本该是「按行条件决定颜色」的逻辑（超容红、零库存灰），现在退化成了常量样式。

---

## 5. 问题清单（按严重度）

### P0 —— 阻断性，必须立即处理

| # | 位置 | 问题 | 影响 |
| --- | --- | --- | --- |
| 1 | `collect_stock:88` | `SELECT ... EINA NTGEW FROM mard`，MARD 无这些字段 | **编译失败**，类无法激活 |
| 2 | `on_double_click:230` | `mt_stock` / `ms_stock` 未声明 | **编译失败** |
| 3 | `collect_stock:92` | `matnr IN it_matnr`，`it_matnr` 为空时不过滤 | 全表扫描 → 挂死/短错误 |
| 4 | `check_capacity:149` | `<ls>-mstock = lv_slots` 静默覆盖真实库存 | **数据失真**，审计风险 |
| 5 | `enrich_text:118` | `MODIFY ... FROM` 作用于 `WITH EMPTY KEY` 表 | **所有行的描述被覆盖成最后一行的** |
| 6 | `display_alv:199/223` | 屏幕 0100 与容器 `STOCK_AREA` 不存在 + 类方法内 `CALL SCREEN` | 运行必然短错误 |
| 7 | `calc_unit_weight:135` | 毛重 ÷ EAN 编码 | **业务数据完全错误**（若被接线） |

### P1 —— 正确性 / 可维护性

| # | 位置 | 问题 |
| --- | --- | --- |
| 8 | `collect_stock:81-86` | `lv_sql` 死代码；库位范围筛选能力静默丢失（模板内 `iv_warehouse_range( )` 是字面文本，故不报错） |
| 9 | `display_alv:211` | `it_outtab` 用方法局部内表，排序/筛选结果不回写 |
| 10 | `build_fieldcat` 全程 | `tabname = 'TY_STOCK'` 对局部内表无效；ALV 字段目录运行期解析失败 |
| 11 | `display_alv:99` | 空结果在 `RETURNING` 方法里弹 Message，越权 UI |
| 12 | `collect_stock:35` | `RAISING cx_sy_move_cast_error` 无任何抛出点，契约名存实亡 |
| 13 | `display_alv:217` | 异常仅置 `lv_ok`（且是死变量）后丢弃，无提示无日志 |
| 14 | `on_double_click:232` | 回调里 `WRITE` 覆盖 ALV |
| 15 | `on_double_click:236` | 回调里 `CHECK` → `CX_SY_NO_CHECK` 短错误 |
| 16 | `check_capacity:144` | `MARD-MVBELN`（销售订单）与容量无关；`QUAN → INT` 截断 |
| 17 | `calc_unit_weight:128` | `CHAR(37)` → `P DECIMALS 4` 隐式转换，非数字静默归 0 |
| 18 | `set_cell_styles:250` | `CL_GUI_RICHTEXT` 常量用于 ALV 样式；`style = 6` 非法值 |
| 19 | 类池 + `CREATE PUBLIC` | 全局类不应放在 `CLASS-POOL`；单例属性无法支撑多次显示 |
| 20 | 全局 | 无单元测试类；`build_fieldcat` / `calc_unit_weight` 是纯逻辑，本该可测 |

### P2 —— 规范 / 体验

- 21 文本硬编码英文（`seltext_m`、所有 `MESSAGE`），未用文本符号 `CC01~CCNN`；`SPRAS='ZH'` 也应参数化为 `sy-langu`
- 22 无 `zebra` / `totals` / 标题 / 工具栏 / 布局变式；无 `hotspot_click`（`MATNR` 可点击跳 MM03）
- 23 `ms_plants` 声明后从未使用；`constructor` 只接单工厂但命名暗示支持多工厂
- 24 `WITH EMPTY KEY` 使 ALV 无法回写、`READ TABLE`/`MODIFY` 语义失效、排序性能差
- 25 `it_matnr TYPE mara-matnr_tab` 依赖外部 DDIC 表类型（可靠性存疑），应在本类定义 `ty_matnr_tab`
- 26 `calc_unit_weight`、`set_cell_styles`、`check_capacity` 全为死代码；`EINA` 取了不展示
- 27 变量命名撒谎：`iv_warehouse` 实为库位（lgort）；`check_capacity` 实为赋值；`collect_stock` 实为弹消息
- 28 无 `IF sy-batch` 保护：批处理下 `CREATE OBJECT` 控件必短错误
- 29 `FOR ALL ENTRIES` 未防空/未去重；未检查 `READ TABLE` 的 `sy-tabix`
- 30 无 CDS 视图 / 无 `SELECT SINGLE` 判空，取数逻辑全散在类里，无法被其他报表复用

---

## 6. 改进建议与目标架构

### 6.1 分层（把 9 个 public 方法拆成三层）

```
ZCL_STOCK_CHECK              " Facade：只暴露一个入口，保持对外 API 兼容
  └─ ZCL_STOCK_CHECK_QUERY  " 取数层：CDS View 或 SELECT，RETURNING + RAISING
  └─ ZCL_STOCK_CHECK_CALC  " 计算/校验层：纯函数，无 DB 访问，可单元测试
  └─ ZUI_STOCK_CHECK_ALV   " 展示层：ALV 字段目录/样式/事件，独立于取数
```

### 6.2 取数层：用 CDS 替掉拼接的 SELECT

```abap
" 取数层：一次 JOIN，语义清晰，可被 SQL 客户端直接验证
SELECT mard~matnr, mard~lgort, mard~mstock, mara~eina, mara~ntgew
  FROM mard INNER JOIN mara ON mara~matnr = mard~matnr
  WHERE mard~werks  = @ms_plant
    AND mard~lgort IN @it_lgort_range        " 真正的范围下推
    AND mard~matnr IN @it_matnr              " ← 必须先判空
  INTO TABLE @DATA(lt_stock).
```

配套守卫：

```abap
IF it_matnr IS INITIAL OR ms_plant IS INITIAL.
  RAISE EXCEPTION TYPE zcx_stock_check
    EXPORTING textid = zcx_stock_check=>no_selection.
ENDIF.
```

> 若范围条件来自屏幕（F4 多选），更推荐 **CDS View + `RANGE` 类型参数**，让 ABAP 引擎做范围下推。

### 6.3 计算层：把「单位重量」算对

```abap
METHOD calc_unit_weight.
  " NTGEW：物料毛重(kg)。分母必须是基本单位数量，不是 EAN。
  DATA(lv_qty_base) = COND #( WHEN is_row-umrez IS INITIAL THEN is_row-mstock
                             ELSE is_row-mstock * is_row-umrez / is_row-umren ).

  IF lv_qty_base IS INITIAL.
    rv_uw = 0.
    RETURN.
  ENDIF.

  rv_uw = is_row-ntgew / lv_qty_base.   " kg / 基本单位数量
ENDMETHOD.
```

- 在 `ty_stock` 中补 `umrez` / `umren`（来自 `MARD` 或换算子查询），使换算过程**显式、可测**。
- 若业务其实想问「每件毛重」，那答案应该是**直接读 `MARA-NTGEW` 并展示**，而不是算除法 —— 建议先跟需求方对齐，再决定这个方法是否还需要存在。
- 计算列加 ALV 单元格类 `lvc_actual`（`ztext = 'OK/WARN'`）或用 `set_cell_styles` 输出颜色，让「合理性检查」真的可视。

### 6.4 校验层：绝不静默改数据

```abap
" 原设计：check_capacity 直接改 MSTOCK
" 改设计：返回校验结论，数据保持只读

TYPES: BEGIN OF ty_capacity_issue,
         matnr   TYPE mara-matnr,
         lgort   TYPE mard-lgort,
         mstock  TYPE mard-mstock,
         capacity TYPE quan,          " QUAN，不是 INT
         msgty   TYPE c1,
         msgid   TYPE symsgid,
       END OF ty_capacity_issue.

METHOD check_capacity
  IMPORTING iv_lgort TYPE mard-lgort
  RETURNING VALUE(rt_issue) TYPE ty_capacity_t
  RAISING   zcx_stock_check.
```

容量数据源用真实业务对象（库位主数据扩展 / `LGPROD` 生产库位 / 自建 `ZSTOCK_CAPACITY`），并在 ALV 里加一列展示上限与差额，让差异**可见**而不是被吞掉。

### 6.5 富化层：修掉 MODIFY 污染

```abap
LOOP AT ct_stock ASSIGNING FIELD-SYMBOL(<ls>).
  READ TABLE lt_text ASSIGNING FIELD-SYMBOL(<ls_t>)
    WITH KEY matnr = <ls>-matnr.
  IF sy-subrc = 0.
    <ls>-maktx = <ls_t>-maktx.
  ELSE.
    <ls>-maktx = TEXT-000.   " 保持空或占位，别静默覆盖
  ENDIF.
ENDLOOP.
```

同时：
- 把 `ty_stock_tab` 改为 `WITH NON-UNIQUE SORTED KEY key_matnr_lgort COMPONENTS matnr lgort`（去掉 `EMPTY KEY`）。
- `lt_text` 用 2 字段局部结构 + `FOR ALL ENTRIES` 前判空。
- `SPRAS` 取 `sy-langu`，或作为构造参数传入。

### 6.6 展示层：ALV 正确接线

```abap
METHOD display_alv.
  DATA(lt_stock) = collect_stock( it_matnr = it_matnr_sel ).   " 真正取数
  enrich_text( CHANGING ct_stock = lt_stock ).

  set_cell_styles( CHANGING ct_styling = lt_scol )              " 真正接线

  DATA(lt_sort) = VALUE #( ( fieldname = 'MATNR' up = 1 ) ).
  DATA(lt_layf) = VALUE #( zebra    = abap_true
                          grid_title = '原材料库存重量体检' ).

  mo_grid->set_table_for_first_display(
    EXPORTING i_save       = 'A'
              i_default_layout = 'X'
    CHANGING  it_outtab     = lt_stock        " ← 必须是调用方持有的内表
              it_fieldcatalog = build_fieldcat( )
              it_sort        = lt_sort
              it_exclude     = lt_excl
    CHANGING  it_layout     = lt_layf
    EXCEPTIONS program_error = 1 OTHERS = 2 ).
  IF sy-subrc <> 0.
    MESSAGE lv_why TYPE 'S' ORLE-ERRORS IN PROGRAM.   " 别再吞异常
  ENDIF.

  SET HANDLER on_double_click FOR mo_grid.   " 首次显示之前注册
ENDMETHOD.
```

补充建议：
- `display_alv` 接收内表作为参数而非内部声明：`METHOD display_alv IMPORTING it_stock TYPE ty_stock_tab`。
- 屏幕/容器不归这个类管：类只负责 `set_*_display`，`CALL SCREEN` 放在独立的报表程序里。
- 更激进的选择：**这个场景直接用 `cl_salv_table` + `salv_table_display`**，`build_fieldcat` 全部删掉，能砍掉 120 行代码并自带工具栏/布局/导出。

### 6.7 可测试性

给纯逻辑方法补 `LTCL` 单元测试（可用 `FOR UNIT TESTING` 排除 DB 依赖后测）：

- `calc_unit_weight`：`EINA` 为空 / `UMREZ=0` / 正常换算 三组
- `build_fieldcat`：列数、`fieldname` 齐全、无 `tabname`、文本符号非空
- `enrich_text`：空表、单行、重复 `MATNR`、查不到描述 四组（能立刻抓到 P0-5）

---

## 7. 接手行动清单

1. **先确认线上真实版本**：SE24 查看 `ZCL_STOCK_CHECK` 激活版本 / `SU3` 历史记录，与本文件比对。当前文件编译不过，大概率不是线上版本。
2. **补齐流程逻辑**：`STOCK_AREA` 容器所在屏幕 0100 的 PBO/PAI，类池 flow logic 是否存在。
3. **与需求方对齐三件事**：①「单位重量」的真实业务定义；②「容量上限」的数据来源；③超出上限时应**报错**还是**仅提示**（当前是静默改数据）。
4. **修 P0（7 项）**：编译错误 ×2、空区间守卫、富化 MODIFY 污染、`check_capacity` 语义重写、ALV 屏幕/容器、`calc_unit_weight` 分母换成基本单位数量。
5. **补 P1（异常契约 + 死代码清理）**：定义 `ZCX_STOCK_CHECK`，删除 `ms_plants`、`lv_ok`、`lv_sql` 死代码与未使用方法。
6. **补 `LTCL`**：至少覆盖 `calc_unit_weight` / `enrich_text` / `build_fieldcat`。
7. **性能复核**：上线前用 `ST05` 抓取数耗时，确认 `MARD` 走主索引 `MARD-WERKS` 或改用 CDS。

---

## 8. 一句话给未来维护者

> 这个类的问题不是「写得丑」，而是**每一层都停在了半途**：SQL 拼了一半没执行、JOIN 写进了字符串没落到 `SELECT`、字段目录写了一半没接线、双击回调写了分支没实现下钻、单位重量算了一个 EAN 除法、`check_capacity` 把检查写成了赋值。修复顺序应该是：**先让它编译 → 再让它取到数 → 再让它显示对 → 最后才谈性能与规范**。