# ZCL_STOCK_CHECK 全局类 Onboarding 分析报告

> 被分析对象：`evals/zcl_stock_check.clas.abap`（256 行，class pool + 全局类）
> 目标读者：接手这个类的 MM 报表开发 / 新人
> 分析视角：业务意图 · 类结构 · 取数 · ALV 显示 · 风险与改造建议

---

## 0. TL;DR（先记住这 5 件事）

1. **这个类当前状态是"语法就过不去"**：至少有 4 处硬编译错误（未声明属性 `mt_stock` / `ms_stock`、方法里写 `WRITE`、从 `mard-mvbeln` 取字段、只查 `mard` 却要 `mara` 的字段）。它大概率是**从未成功 SE24 激活**、或激活后又被改坏的历史遗留物。
2. **取数与显示彻底断链**：`display_alv` 里没有调用 `collect_stock` / `enrich_text` / `calc_unit_weight` / `check_capacity` 中的任何一个，`lt_stock` 是空的；5 个"业务方法"是孤儿。**没有编排入口（run/main）**。
3. **`collect_stock` 里的 `lv_sql` 是死代码**，OpenSQL 字符串拼好后从未 `EXECUTE IMMEDIATE`；而且拼接内容本身是坏的（`IN iv_warehouse_range( )` 不是合法 OpenSQL 语法），如果哪天被人"顺手接上"会直接 SQL 语法报错 + 有注入风险。
4. **语义层面算错**：`mara-eina` 是"采购计量单位"（3 字符单位码），代码却拿它当除数算单位重量；`mard-mstock` 只是**受限库存**，不含非受限/质检/在途，口径也漏。
5. **ALV 用的是 20 年前的写法**：`CREATE OBJECT` + 自定义 Container + `CALL SCREEN 0100`，依赖 class pool 隐式生成屏幕；而 `set_cell_styles` / `on_double_click` 都写了却没接上。要么 dump、要么白屏。

---

## 1. 它想解决什么业务问题

从头部注释和字段语义反推（`zcl_stock_check.clas.abap:1-6`）：

```abap
*& Global class: stock / weight sanity check for raw materials.
*& Owned by: MM Reporting team.
```

业务意图是一个**原材料库存自查（sanity check）**工具：

| 意图 | 对应代码 |
|---|---|
| 给定工厂（`iv_plant`）和一批物料号，列出每个物料在各库存地点的库存量 | `collect_stock` |
| 顺带带上物料描述（中文），方便业务人员肉眼核对 | `enrich_text` |
| 算单位重量（净重/采购单位），识别"重量异常" | `calc_unit_weight` |
| 拿库存地点的容量做上限校验，标出超出部分 | `check_capacity` |
| 用 ALV 网格展示 + 双击下钻 | `display_alv` / `on_double_click` |

也就是说：一个 **MM 报表侧的临时排查工具**，不是生产过账逻辑。这一点很重要——它决定了改造目标是"能跑、别改数、别拖库"，而不是"重构业务模型"。

**Owner 是 MM Reporting team**，所以任何"顺手改成能写数据"的提议都应直接拒绝。

---

## 2. 类骨架与契约

### 2.1 池 / 类声明

```abap
CLASS-POOL zcl_stock_check.          " :7
PUBLIC
FINAL                              " :13
CREATE PUBLIC .                    " :14
```

- `CLASS-POOL` 而不是普通 `CLASS`：这是"报告型全局类"的写法，存在的唯一理由通常是需要 `CALL SCREEN`。本类也确实用了 `CALL SCREEN 0100`（:223）。
- `FINAL` 加在了 **pool** 上（表示这个池不能被用作父类），而不是加在 class 上。真正的类并没有 `FINAL`，可以被随意继承。
- 没有文档注释、没有 `##NO_TEXT`、没有单元测试类、`create_public` 意味着任何程序都能 `NEW` 出来。

> **判断**：class pool + 屏幕 + `WRITE` 的组合，是 ABAP OO 官方明确劝退的"半 OOP 半报表"写法。ALV 应该用 `mo_grid->display_grid( )` + `set_docking( )` 全屏显示；如果确实要占屏，则应该另建一个普通 Dynpro 报表来包一层。

### 2.2 数据结构

```abap
TYPES: BEGIN OF ty_stock,
         matnr  TYPE mara-matnr,
         maktx  TYPE makt-maktx,
         lgort  TYPE mard-lgort,
         mstock TYPE mard-mstock,
         eina   TYPE mara-eina,     " ← 采购计量单位（单位码！）
         ntgew  TYPE mara-ntgew,    " ← 净重 / 基本计量单位
       END OF ty_stock.

TYPES ty_stock_tab TYPE STANDARD TABLE OF ty_stock WITH EMPTY KEY.   " :27
```

优点：
- `WITH EMPTY KEY` 用对了（纯输出表，不做查找）。
- 字段都指向真 DDIC 类型，没有自造类型。

问题：
- **没有"容量/超限/单位重量"这三个计算结果的字段**。也就是说 `calc_unit_weight` 和 `check_capacity` 的结果**无处存放**——它们只能靠"改写源字段"来体现，这就直接引入了第 6 节 P1-2 那个"把真实库存量改成容量值"的数据事故。
- 字段集合不完整：缺 `werks`（只靠 `ms_plant` 隐含）、缺 `maktx` 的语言标识、缺 `insstock`/`mstock_unrest`（见 §3.5）。

### 2.3 属性清单

```abap
DATA ms_plant    TYPE werks.                          " :64
DATA ms_plants   TYPE werks_tab.                      " :65
DATA mo_grid     TYPE REF TO cl_gui_alv_grid.         " :66
DATA mo_container TYPE REF TO cl_gui_custom_container." :67
```

| 属性 | 是否被使用 | 问题 |
|---|---|---|
| `ms_plant` | 是，`collect_stock` / `check_capacity` 都用它 | 没有做任何 `t001w` 有效性校验，没有默认成 `sy-Plantid` |
| `ms_plants` | **完全没被用过** | 名字是复数，构造器只接一个工厂 → 死属性，误导后来者 |
| `mo_grid` | 是，`set_table_for_first_display` / `SET HANDLER` | 没有 `flush`、没有销毁/重建逻辑 |
| `mo_container` | 是 | 依赖不存在的屏幕控件，见 §4 |
| （缺失）`mt_stock` | `on_double_click:230` 在用 | **不存在** → 编译错误 |
| （缺失）`ms_stock` | `on_double_click:230` 在用 | **不存在** → 编译错误 |

### 2.4 方法清单

| # | 方法（行号） | 类型 | 期望职责 | 实际状况 |
|---|---|---|---|---|
| 1 | `constructor` (:72) | 实例 | 保存工厂 | 仅一行赋值，无校验、无默认 |
| 2 | `collect_stock` (:79) | 实例 | 查 MARD 库存 | 死 SQL 字符串 + **从 mard 取 mara 字段** + 空转循环 + 副作用 MESSAGE |
| 3 | `enrich_text` (:105) | 实例 | 补中文描述 | 逻辑大体对，但 O(n²) + `DATA()` 声明位置陷阱 + 语言硬编码 |
| 4 | `calc_unit_weight` (:124) | 实例 | 单位重量 | **语义错误**（拿单位码当除数） |
| 5 | `check_capacity` (:140) | 实例 | 容量上限校验 | **SQL 完全错误** + **直接覆盖真实库存量** |
| 6 | `build_fieldcat` (:156) | 实例 | 构造字段目录 | 结构名可疑，列不全，标签与数据矛盾 |
| 7 | `display_alv` (:194) | 实例 | 显示 ALV | 未串联任何取数；旧式 Container + `CALL SCREEN`；错误被吞 |
| 8 | `on_double_click` (:228) | 实例 | 双击事件 | 引用不存在属性 + `WRITE` 禁用 + 无下钻 |
| 9 | `set_cell_styles` (:244) | 实例 | 单元格着色 | 从未被调用；`is_row` 入参未使用 |

**一句话**：9 个方法里，只有 `enrich_text` 和 `build_fieldcat` 的逻辑骨架是可用的；其余 7 个有语法错误、语义错误或死代码。

---

## 3. 取数逻辑逐段拆解

### 3.1 `collect_stock` —— 三处硬伤

```abap
lv_sql = |SELECT mard~lgort mard~mstock mara~eina mara~ntgew mara~matnr|
       && |  FROM mard INNER JOIN mara ON mara~matnr = mard~matnr|
       && | WHERE mard~werks = '{ ms_plant }'|
       && |   AND mard~lgort IN iv_warehouse_range( )|.   " :83-86

SELECT matnr lgort mstock eina ntgew                     " :88-92
  FROM mard
  INTO TABLE rt_stock
  WHERE werks  = ms_plant
    AND matnr IN it_matnr.
```

**问题 A — `lv_sql` 是死代码，且本身是坏的。**
拼出来的字符串从没被 `EXECUTE IMMEDIATE` 使用；`IN iv_warehouse_range( )` 不是 OpenSQL 语法（OpenSQL 里没有 `()` 这种"宏占位"），所以这是一段"看起来合理但永远不能执行"的 SQL。更危险的是它示范了"字符串拼 SQL + 直接内插 `ms_plant`"的写法——哪天有人改成动态 `lgort` 范围，这就是一条注入通道，而且 `ms_plant` 没做任何转义（`''` 双写单引号）。

**问题 B — 字段与表不匹配（编译期 SQL 错误）。**
`eina` 和 `ntgew` 都是 **MARA** 的字段，`mard` 里没有。所以实际执行的那条 `SELECT ... FROM mard` 会报 `ST02/SQL` 之类的错误（unknown field），在 SE38 里能提前发现（syntax check 会抓），运行时才发现就是 dump。
顺带一提：`mard` 的键是 `matnr + werks + lgort`，如果真要连 MARA，应该写：

```abap
SELECT mard~matnr mara~maktx  mara~maktx  mara~mara~lgort ...
```
更标准的写法（也更推荐）：

```abap
SELECT mara~matnr, mara~ntgew, mard~lgort, mard~mstock
  FROM mara INNER JOIN mard ON mard~matnr = mara~matnr
  WHERE mard~werks = @ms_plant
    AND mara~matnr IN @it_matnr
    AND mard~lgort IN @lt_lgort
  INTO TABLE @DATA(lt_raw).
```

**问题 C — 死循环 + 副作用消息。**

```abap
LOOP AT rt_stock ASSIGNING FIELD-SYMBOL(<ls>).
  <ls>-matnr = <ls>-matnr.        " :95  ← 自赋值，什么都没干
ENDLOOP.

IF rt_stock IS INITIAL.
  MESSAGE 'No stock records found' TYPE 'S'.   " :99  ← 数据层不该弹窗
ENDLOOP.
```

- 自赋值循环唯一的"作用"是让编译器/ABAP 对象里出现内联字段符号，属于纯粹的噪音。
- 一个"取数方法"里弹 `TYPE 'S'` 消息：调用方无法控制，批处理里会直接变成消息写入后台日志或终止报表，单元测试里没法断言。
- `RAISING cx_sy_move_cast_error`（:35）声明了但**从未 RAISE**，调用方也从不 CATCH → 死异常，建议删掉或换成真实异常。

**问题 D — `it_matnr` 为空没有早退。** `IN @it_matnr` 传空内表会返回空集（行为正确但白跑一次），且此时还会弹一句误导性的 'No stock records found'。

### 3.2 `enrich_text` —— 逻辑对，风格危险

```abap
LOOP AT ct_stock INTO DATA(ls_row).                          " :115
  READ TABLE lt_text INTO DATA(ls_text) WITH KEY matnr = ls_row-matnr.
  ls_row-maktx = ls_text-maktx.                              " :117
  MODIFY ct_stock FROM ls_row.                               " :118
ENDLOOP.
```

- **最重要的坑：`DATA(ls_text)` 在 LOOP 体内声明，生命周期覆盖整个循环，不会每次迭代重置。** `READ TABLE` 没命中时 `ls_text` 保留**上一行**的内容，于是"某物料没有 ZH 描述"时，会**串行继承上一个物料的描述**。这是典型的"脏数据渗透"，报表上会看到完全错误的物料描述，而且非常难查。
- `MODIFY ct_stock FROM ls_row` 对标准表默认按**整行**做 key 匹配，O(n²)，且只有在整行完全一致时才命中（第 115 行 `LOOP AT ... INTO` 保证了这一点，所以"能工作"是靠运气 + 全表扫描）。
- `READ TABLE ... WITH KEY matnr` 在标准表上同样是线性查找，整体 O(n²)。
- 语言硬编码 `spras = 'ZH'`（:113），没有 `sy-langu`、没有 `spras = '1'`（补充语言）兜底。系统登录语言是 EN 时，描述列会整列空白。
- `lt_text TYPE TABLE OF makt` 把 MAKT **整张结构**都取回来（含 Maktx 之外的 20 多个字段），内存和网络上都是浪费。

正确写法：

```abap
LOOP AT ct_stock ASSIGNING FIELD-SYMBOL(<row>).
  IF <row>-maktx IS INITIAL.
    READ TABLE lt_text ASSIGNING FIELD-SYMBOL(<text>)
      WITH TABLE KEY matnr = <row>-matnr.
    IF sy-subrc = 0.
      <row>-maktx = <text>-maktx.
    ENDIF.
  ENDIF.
ENDLOOP.
```
并且 `lt_text` 应该是一个瘦结构：`TYPES ty_makt TYPE TABLE OF ty_text WITH NON-UNIQUE KEY matnr`（或直接 `SORTED ... WITH UNIQUE KEY` 换 O(log n) 读）。

### 3.3 `calc_unit_weight` —— 单位算错了

```abap
DATA lv_base TYPE p DECIMALS 4.
lv_base = is_row-eina.                     " :128
IF lv_base IS INITIAL.
  rv_uw = 0.
  RETURN.
ENDIF.
rv_uw = is_row-ntgew / lv_base.            " :135
```

**`mara-eina` 是"采购计量单位"，3 位字符型单位码（如 `KG` / `PC` / `M`），不是数量。** 用它当除数：

- 运行时不是 dump 就是恒为 0 / 无意义的数（ABAP 里把 3 字符转成数值，几乎必然得到 0 或转换错误）；
- 就算它恰好能转成数字，单位语义也是错的。

**正确的"单位重量"有两个口径**，需要先跟业务确认：

| 口径 | 正确算法 |
|---|---|
| 净重 / 基本单位 | **`mara-ntgew` 本身就是这个值**，不需要除，直接用 |
| 净重 / 采购单位 | 用 MARAM：`maram-einn`（每个采购单位的数量）配合 `mtart` 过滤：<br>`weight_per_pur_unit = ntgew * einn` |

```abap
" 单位重量 = 每个采购单位含多少个基本单位
SELECT m~matnr, m~ntgew, am~einn
  FROM mara AS m
  INNER JOIN maram AS am ON am~matnr = m~matnr
  WHERE m~matnr IN @it_matnr
    AND am~mtart = 'LE'              " 采购单位
  INTO TABLE @DATA(lt_uom).
```
若还要处理不同单位换算，必须走 `MATERIAL_UNIT_CONVERSION`（`CL_MATERIAL_UNIT_CONVERSION`），不能自己除。

其他小问题：`p DECIMALS 4` 会把权重截成 4 位小数，做汇总时误差累积；返回值没有任何 `UNIT` 说明。

### 3.4 `check_capacity` —— 危险等级最高

```abap
DATA lv_slots TYPE i.

SELECT SINGLE mstbw FROM mard-mvbeln INTO @lv_slots   " :144
  WHERE werks = ms_plant AND lgort = iv_warehouse.

LOOP AT ct_stock ASSIGNING FIELD-SYMBOL(<ls>).
  IF <ls>-mstock > lv_slots.
    <ls>-mstock = lv_slots.                            " :149  ← 改写真实库存量
  ENDLOOP.
```

三处叠加问题：

1. **`mard-mvbeln` 不是 MARD 的字段**（`MVBELN` 属于 `MKAP/MVBE/MATP`）。而且 `MSTBW` 是 **MARC**（最大库存量）的字段，不是 MARD。这条 SQL 连语法检查都过不了。
2. **量纲错配**：`MSTBW` 是 `QUAN`（带 3 位小数的定点数），目标 `lv_slots TYPE i` → 小数被截断。
3. **`SELECT SINGLE` 查不到时（sy-subrc = 4）`lv_slots` 保持 0**，然后 `mstock > 0` 全部成立 → **把每一行的库存量全部改成 0**。而 `mstock` 是"真实库存事实"。

这一段是典型的**只读报表里写坏源数据**。一个"sanity check"工具把被检查的数据改掉，属于严重设计错误：调用方无法知道结果已被篡改，后续任何基于它的判断都建立在脏数据上。

正确做法：**只读判，不改数**。

```abap
TYPES ty_check TYPE TABLE OF ty_check_line WITH EMPTY KEY.
ty_check_line = VALUE #( werks lgort stock( ) capacity( ) over_by( ) is_over( ) )

" 或者保持 ty_stock 不变，另开一个结果内表
TYPES: BEGIN OF ty_over,
         matnr TYPE mara-matnr,
         lgort TYPE mard-lgort,
         over_by TYPE mard-mstock,
       END OF ty_over.
```
把 `over_by` 单独返回给调用方，ALV 里用 `lvc_t_scol` 标红，而不是覆盖 `mstock`。

另外 `iv_warehouse` 只查了一个地点，却把容量套到**所有行**（包括其他 LGORT 的行）——逻辑不成立。

### 3.5 取数口径层面的三个"业务坑"

即使语法全部修好，数据仍然是错的：

| 坑 | 说明 |
|---|---|
| `mard-mstock` 只是**受限库存** | 未受限在 `marc-mstock`，质检在 `marc-insstock`，在途/转储在 `mard-mbwid` 等。"总库存"不等于 `mard-mstock`。S/4HANA 上应改用 CDS/API：`API_MATERIAL_STOCK_SRV`、`I_SAPAPI_STOCK_SRV` 或 `MATERIAL_STOCK_SRV`，一次拿全库存类别。 |
| `FOR ALL ENTRIES` 的两个前提 | `ct_stock` 里若有重复物料号，结果表会出现重复行（这里靠 `READ` 取第一条掩盖了）；`ct_stock` 为空时 ABAP 会跳过执行（不报错，但也没提示）。应先去重（`SORT ... DELETE DUP`）或改为直接 `WHERE matnr IN (SELECT ...)`。 |
| 索引与包大小 | `mard` 上按 `werks` + `matnr` 过滤，字段目录里应检查索引是否存在；MM 报表常用 ST05 / SQL 跟踪确认。若 `it_matnr` 元素很多（>1000），建议分批或改用 CDS 视图聚合，避免大 IN 列表。 |

---

## 4. ALV 显示流程

### 4.1 代码实际做的事

```abap
DATA lt_stock TYPE ty_stock_tab.                          " :196  ← 空的
DATA lv_ok    TYPE abap_bool.

CREATE OBJECT mo_container                                " :199
  EXPORTING container_name = 'STOCK_AREA' repaint_detlevel = 1.

CREATE OBJECT mo_grid                                     " :204
  EXPORTING i_container = mo_container ex_initial_layout = '1'.

mo_grid->set_table_for_first_display(                     " :209
  CHANGING it_outtab = lt_stock it_fieldcatalog = build_fieldcat( )
  EXCEPTIONS program_error = 1 OTHERS = 2 ).

IF sy-subrc <> 0.
  lv_ok = abap_false.                                     " :218  ← 算完就丢
ENDIF.

SET HANDLER on_double_click FOR mo_grid.                  " :221
CALL SCREEN 0100.                                         " :223
```

### 4.2 断链与缺陷

| # | 问题 | 后果 |
|---|---|---|
| A | **没有编排**：`display_alv` 从不调用 `collect_stock` | 表格源表 `lt_stock` 恒空 → 即使一切正常，ALV 也是空白列表 |
| B | **屏幕不存在 / 控件不存在**：`CALL SCREEN 0100` 依赖 class pool 隐式生成的 0100，而名为 `STOCK_AREA` 的控件从未在任何 Dynpro 上定义；且 class pool 里没有 PBO 模块去 `display_grid` | `CREATE_OBJECT cl_gui_custom_container` 抛异常 → dump，或屏幕空白无控件 |
| C | **没有 `display_grid( )`**：ALV 靠 PBO 才会显示，这里没有 PBO | 屏幕上什么都不画 |
| D | **`it_outtab` 传方法内局部变量** | ALV 控件持有的是局部变量引用；换屏/重建后引用语义脆弱，且外部无法再访问这份数据做筛选、导出、下钻 |
| E | **异常被吞**：`program_error = 1 OTHERS = 2` 之后只把 `lv_ok` 置 `abap_false`，既不 `MESSAGE` 也不 `LOG`，`lv_ok` 之后没被读 | 出错时用户只看到"什么都没有"，排查成本极高 |
| F | **旧语法**：`CREATE OBJECT`（应 `NEW`）、`ex_initial_layout = '1'`（应 `set_layout`） | 代码评审会被打回；`CREATE OBJECT` 与 OO 新规范冲突 |
| G | **生命周期无管理**：`mo_container` / `mo_grid` 是实例属性，离开屏幕时既不 `destroy` 也不重置；二次调用 `display_alv` 会 `CREATE OBJECT` 一个同名 Container | 控件残留 / "Control already exists" 短 dump；后台运行时 `CREATE OBJECT cl_gui_...` 直接 dump（**没有 background 保护**） |
| H | **`SET HANDLER` 位置**：`SET HANDLER` 放在 `set_table_for_first_display` 之后是对的，但放在 `CALL SCREEN` 之前意味着一旦 `set_table_for_first_display` 失败仍会注册事件 | 小问题，但与 E 叠加会让失败难以定位 |

**推荐的最小正确形态**（不依赖任何屏幕）：

```abap
METHOD display_alv.
  DATA(lt_stock) = collect_stock( it_matnr = iv_matnr ).      " 编排从这里开始
  enrich_text( CHANGING ct_stock = lt_stock ).

  CREATE OBJECT mo_grid
    EXPORTING i_container = get_main_container( )            " 或 set_docking
    EXCEPTIONS program_error = 1 OTHERS = 2.
  IF sy-subrc <> 0.
    MESSAGE ID '00' TYPE 'S' NUMBER 001.                     " 必须报出来
    RETURN.
  ENDIF.

  mo_grid->set_layout( VALUE #( grid_title = '原材料库存自查' ) ).
  mo_grid->set_table_for_first_display(
    CHANGING it_fieldcatalog = build_fieldcat( )
              it_outtab       = lt_stock
              it_s_table      = lt_stock ).                  " ← 排序/筛选的关键
  SET HANDLER on_double_click FOR mo_grid.
  mo_grid->display_grid( ).                                  " ← 真正显示
ENDMETHOD.
```

### 4.3 `build_fieldcat` 的问题

```abap
APPEND VALUE #( fieldname = 'MATNR' ref_field = 'MATNR'
                tabname = 'TY_STOCK' seltext_m = 'Material'
                just_field = 'X' ) TO rt_fieldcat.          " :158-163
```

- **`tabname = 'TY_STOCK'` 是最可疑的一处**。字段目录要引用数据结构名，而传给 `set_table_for_first_display` 的是**方法内局部变量** `lt_stock`，ALV 侧能解析到的结构名来自 ABAP 类型（形如 `ZCL_STOCK_CHECK=>TY_STOCK` / 生成名），不是裸的 `'TY_STOCK'`。这类"看起来能跑、字段列不出来/列空"的问题在 ALV 里非常常见。
  正解两种：① 把结构提到一个**全局可见的 DDIC 结构/TYPE 池结构**，让 `tabname` 与 `it_outtab` 的结构名严格一致；② 用 `ref_field` + `ref_tabname` 成对给出；③ 或者干脆不设 `tabname`，让 ALV 用 `it_outtab` 推断。
- **`ref_field` 与 `tabname` 混用但缺 `ref_tabname`**，自引用字段的解析依据不明确。
- **列不全**：`EINA` 没进 ALV；`calc_unit_weight` 的结果没有列；`check_capacity` 的超限结果没有列。也就是说三个"业务方法"在 UI 上一个都看不到。
- **标签与数据矛盾**：`NTGEW` 标签写的是 `'Gross Weight (kg)'`（毛重），而 `NTGEW` 是**净重**且**每基本计量单位**；`MSTOCK` 是受限库存却标签写 `'Stock Qty'`。业务人员按标签理解会直接判断错。
- **格式处理缺失**：`MSTOCK` 有 `no_outline` 但没有 `no_zero`；`NTGEW` 没有小数位控制；`MATNR` 用 `just_field`（右对齐）不如 `just = 'L'`；`LGORT` 建议配 F4 帮助。
- **语言混搭**：字段标签全英文，而 `enrich_text` 硬编码取中文描述 → 一张"中文描述 + 英文列名"的表，风格不统一。
- **`set_cell_styles` 从未被 `build_fieldcat`/`display_alv` 引用**（`set_cell_styles` 需要在 `set_table_for_first_display` 之后通过 `set_table_for_first_display` 之外的 `mo_grid->...`/在 layout 里挂 style callback，或用 `cl_salv` 的 `style_formats`）。死方法。

---

## 5. 事件与样式

```abap
METHOD on_double_click.
  READ TABLE mt_stock INTO ms_stock WITH KEY matnr = iv_data.   " :230  ← 两者都不存在
  WRITE: / iv_row, iv_column, iv_data.                        " :232  ← 类里禁止
  CASE iv_column-fieldname.
    WHEN 'MSTOCK'.  CHECK iv_row > 0.                          " :235-236 ← 无意义
    WHEN 'NTGEW'.   MESSAGE '...' TYPE 'S'.
  ENDCASE.
ENDMETHOD.
```

- **编译不过**：`mt_stock` / `ms_stock` 未声明（:64-67 只有 4 个属性）。
- **`WRITE` 在全局类方法里是非法的**（列表型语句仅允许在 Dynpro 的 PBO/PAI 或报告中）。
- `iv_data` 声明为 `any`，却直接当 `matnr` 用：`WITH KEY matnr = iv_data` 会做隐式转换，类型不匹配时可能抛 `CX_SY_CONVERSION_NO_DATA`，而事件处理器里抛异常 = 用户看到短 dump。
- `WHEN 'MSTOCK'` 用字符串比 `fieldname`，但**用户在 ALV 上排序/隐藏列之后 `iv_column-fieldname` 依然稳定**，所以可以接受；更好的写法是 `WHEN FIELD-SYMBOL(<mstock>)` 或比较 `iv_column-fieldname = 'MSTOCK'`。
- `CHECK iv_row > 0.` —— 后面没有任何东西，是断头逻辑。
- **名叫 `on_double_click` 却没有任何下钻**：业务预期大概率是跳 `MMBE` / `MB23`。真要跳，必须检查 `S_TCODE`（`AUTHORITY-CHECK`）并用 `CALL TRANSACTION ... AND PARAMETERS`，否则 `S_TCODE_BLOCK` 用户点一下就 dump。

`set_cell_styles`（:244-253）：

```abap
APPEND VALUE #( fname = 'MSTOCK' color = 6 intens = 0
                style = cl_gui_richtext=>strikeout
                lstyle = cl_gui_richtext=>strikeout_col_neg ) TO ct_styling.
```

- 常量用 `cl_gui_richtext`（SAPscript 富文本常量），在 ALV 场景应使用 `lvc_style`（`cl_abap_richtext=>strikeout` 等）或 `lvc_styles_*`；当前写法依赖隐式兼容，很脆。
- `is_row` 入参没用 → 所有行样式一样，无法"只在超限/为零时标红"。
- 对数据列用删除线表示"超限"是糟糕的 UX（用户会以为数据已作废）。应改为背景色 + 图标/单独一列文本。
- 这个方法从没有被 ALV 调用过（见 §4.2）。

---

## 6. 问题清单（按优先级）

### P0 — 阻断（不修就编译/运行不过）

| ID | 问题 | 位置 | 建议 |
|---|---|---|---|
| P0-1 | `mt_stock` / `ms_stock` 未声明即使用 | :230 | 在属性里加 `mt_stock TYPE ty_stock_tab`，并在 `display_alv` 里**赋值**（目前没人给 `mt_stock` 赋过值，所以不能只加声明） |
| P0-2 | 全局类方法里使用 `WRITE` | :232 | 换成 `MESSAGE` 或删掉 |
| P0-3 | `SELECT SINGLE ... FROM mard-mvbeln` 字段不存在 | :144 | 改为 `marc-marsch`（允许库存量）/ `marc-mstbw`（最大库存），并明确语义 |
| P0-4 | `SELECT ... eina ntgew FROM mard` 字段不在 MARD | :88 | `INNER JOIN mara`，或拆成两条 SELECT |
| P0-5 | `CALL SCREEN 0100` + `container_name = 'STOCK_AREA'` 无对应屏幕/控件 | :199-223 | 改用 `mo_grid->display_grid( )` + `set_docking( )`，删掉自定义 Container 和 `CALL SCREEN` |

### P1 — 数据正确性（能跑但结论错）

| ID | 问题 | 位置 | 建议 |
|---|---|---|---|
| P1-1 | `mstock` 被容量值覆盖；查不到容量时全表清零 | :144-151 | 只读判：新增 `over_by` / `is_over` 结果，不改源字段 |
| P1-2 | `lv_sql` 死代码 + 字符串拼 SQL（注入 + 语法坏） | :81-86 | 整段删除，改用带 host variable 的 OpenSQL/CDS |
| P1-3 | `DATA(ls_text)` 跨迭代不重置 → 描述串行污染 | :116-117 | 改 `ASSIGNING` + `IF sy-subrc = 0` |
| P1-4 | `calc_unit_weight` 拿 `eina`（单位码）当除数 | :128-135 | 口径先确认；`ntgew` 本身即净重/基本单位；采购单位口径用 MARAM `einn` |
| P1-5 | 库存口径只取 `mard-mstock`（受限库存） | :88-92 | 换 CDS/API，或明确标注"仅受限库存" |
| P1-6 | `tabname = 'TY_STOCK'` 与实际结构名不一致风险 | :158+ | 结构提到全局可见处并与 `it_outtab` 严格对齐 |
| P1-7 | `enrich_text` 硬编码 `spras = 'ZH'`，无兜底 | :113 | `spras IN ( @sy-langu, 'ZH', '1' )` + 按优先级回退 |
| P1-8 | 空 `it_matnr` 时弹误导性 'No stock records found' | :98-100 | 早退并由调用方决定提示方式 |
| P1-9 | ALV 出错被静默吞掉 | :213-219 | `MESSAGE` + 记日志 |

### P2 — 可维护性 / 规范 / 性能

| ID | 问题 | 位置 |
|---|---|---|
| P2-1 | 无编排入口（5 个取数方法全是孤儿） | 全局 |
| P2-2 | `ms_plants` 死属性、`FINAL` 加在 pool 上 | :13, :65 |
| P2-3 | `constructor` 无工厂有效性校验、无 `sy-Plantid` 兜底 | :72-76 |
| P2-4 | `CREATE OBJECT` / `ex_initial_layout` 等旧式写法 | :199-207 |
| P2-5 | `RAISING cx_sy_move_cast_error` 死异常 | :35 |
| P2-6 | 自赋值空循环 `:95`、无意义 `CHECK :236` | :94-96, :236 |
| P2-7 | `FOR ALL ENTRIES` 未去重、`TABLE OF makt` 取全结构 | :107-113 |
| P2-8 | O(n²) 模式三处（`MODIFY FROM`、`READ ... WITH KEY`、`FOR ALL ENTRIES` 未去重） | :109-119 |
| P2-9 | 硬编码文本（`'ZH'`、英文标签、`MESSAGE` 字面量）无消息类 | :99, :113, :162-189, :238 |
| P2-10 | 无后台/无 GUI 环境保护（批处理必 dump） | :199 |
| P2-11 | 无 `AUTHORITY-CHECK`（工厂/物料级数据未做 S_TCODE / SAPLIST 校验） | :200-206 |
| P2-12 | 无单元测试、无文档注释、无异常契约 | 全局 |
| P2-13 | `set_cell_styles` 死方法 + 删除线 UX 误导 | :244-253 |

---

## 7. 改造路线（建议顺序）

**第 1 步：让它能激活（半天）**
1. 加 `mt_stock` 属性，`display_alv` 里真实编排：`collect_stock → enrich_text → check_capacity(不覆盖) → 填结果列 → ALV`。
2. 删 `WRITE`；删 `lv_sql` 死代码；`SELECT` 改 `INNER JOIN mara` + host variables。
3. `check_capacity` 改成只读判，容量查询改 `marc` 真实字段，并 `CHECK sy-subrc` 区分"没查到"和"容量为 0"。
4. ALV 去掉 Container + `CALL SCREEN`，改 `display_grid()`；异常必须 `MESSAGE` 出来。

**第 2 步：让它说真话（1 天）**
5. 统一库存口径（CDS/API），明确"总库存"的定义并写在注释里。
6. 确认单位重量口径，重写 `calc_unit_weight`；如果最终结论是"直接用 ntgew"，就**删掉这个方法**，别留误导性代码。
7. `enrich_text` 修描述污染 + 语言兜底 + 去重 + 瘦结构。
8. `tabname` / `ref_tabname` 与 `it_outtab` 结构严格对齐；补齐列（EINA、单位重量、超限量）；修 `Gross/Net` 标签。

**第 3 步：让它能被复用（可选，1 天）**
9. 抽接口 `zif_stock_check` 便于 mock；把 `it_matnr` / 库存地点范围做成方法参数而不是隐含全局。
10. 补一组 ABAP Unit 测试（至少覆盖：空结果、无 ZH 描述、容量查不到、库存为 0/负数）。
11. 双击改成受权限保护的 `MMBE`/`MB23` 下钻，或直接删掉这个事件。

---

## 8. 上线前自查清单

- [ ] SE38 激活无错；SE24 类激活通过；ATC / Code Inspector 干净。
- [ ] 用 ST05/SQL 跟踪确认走了索引，`it_matnr` 为 1000+ 时无超时。
- [ ] 手工构造 4 组数据验证：① 空物料号 ② 物料无中文描述 ③ 库存地点无容量配置 ④ 库存为 0/负数。
- [ ] 后台 `BTC` 或 `STRUST` 下无调用路径；若有，用 `cl_gui_frontend_services=>is_gui_available` 做前端检测。
- [ ] 确认报表**不会**修改任何源数据（`check_capacity` 已改为只读判）。
- [ ] 权限：用无 S_TCODE 的业务用户验证下钻按钮不 dump。

---

## 9. 速查索引（文件:行）

| 主题 | 位置 |
|---|---|
| 类声明 / 池 | :7-14 |
| 类型定义 | :18-27 |
| 属性 | :64-67 |
| `collect_stock` 死 SQL | :81-86 |
| `collect_stock` 字段错表 | :88-92 |
| 空转循环 | :94-96 |
| 副作用 MESSAGE / 死异常 | :35, :98-100 |
| 描述污染（`DATA()` 在 LOOP 内） | :115-119 |
| 单位重量语义错误 | :124-137 |
| 容量覆盖真实库存 | :140-153 |
| 字段目录 `tabname` | :158-190 |
| ALV 空表 / 吞异常 | :194-219 |
| Container + `CALL SCREEN` | :199-223 |
| 双击事件的编译错误 | :228-241 |
| 死样式方法 | :244-253 |

---

*报告基于静态阅读该 `.abap` 源文件得出；所有"编译错误/字段不存在"类判断均依据 ABAP DDIC 字段归属，可直接在 SE38 语法检查中复核。*