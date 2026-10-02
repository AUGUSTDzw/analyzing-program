# ZSLAV_PO_LIST 代码分析报告

> 目标程序：`zsalv_po_list.abap`（192 行，REPORT + 全局数据 + 两个局部类）
> 评审重点：取数、聚合（totals）、事件绑定、下钻弹窗
> 结论强度说明：文中标注 ✅ / ⚠️ / ❌ 表示"这段写得对不对"；标注 **[需验证]** 的判断需要在目标系统用 SE11/SE38 复核字段是否存在。

---

## 0. 结论速览

| 维度 | 判定 | 一句话理由 |
|---|---|---|
| 能否编译 | ❌ | 至少 4 处硬错误：SELECT-OPTIONS 引用未声明变量、私有属性外部赋值、`mt_data` 是单行却当表用、字段名疑似笔误 |
| 取数 | ❌ | 两次查 EKKO（第一次的结果根本用不上）、内部表字段与 select list 位置错位、空选择会拉全表、`waers = 'EUR'` 写死业务规则 |
| 聚合 | ⚠️ | `add_aggregation` API 用法本身正确，但**语义**错：NETWR 无币种参照列、数量列无单位却也可加总、异常被静默吞掉 |
| 事件绑定 | ⚠️→❌ | 生命周期写法正确（关键优点），但 `link_click` **永远不会触发**、私有属性被外部赋值（编译错）、`mv_show` 是死字段、忽略 `column` |
| 下钻弹窗 | ❌ | `lo_popup` 未初始化就 `display( )`（dump 风险）、`EKPO` 查出 `POSNR = '00000'` 表头条、`gt_item` 全局复用、`row` 当行号用不严谨 |

**总体判断：四块里"聚合"和"事件绑定"的框架选型是对的（`cl_salv_aggregations` + `SET HANDLER FOR lo_events` + 全局 handler 保活），但实现细节几乎每块都有一个会出事的问题。这个程序当前跑不起来；即使把编译错误补掉，空选择 + 位置错位 + 弹窗未初始化检查仍会在生产上炸。**

---

## 1. 前置：这份程序现在编译不过（4 处硬错误）

### 1.1 `SELECT-OPTIONS` 引用了尚未声明的字段

```abap
DATA gt_po   TYPE STANDARD TABLE OF ty_po WITH EMPTY KEY.   " 52
DATA go_report   TYPE REF TO lcl_handler.                    " 55
SELECT-OPTIONS s_ebeln FOR gs_key-ebeln.                    " 57
DATA gs_key TYPE ty_po.                                      " 58  ← 太晚了
```

ABAP 里 `SELECT-OPTIONS ... FOR <data object>` 要求被引用的数据对象**先声明**。这里 `gs_key` 在第 58 行才声明，第 57 行就拿它做参照，属于语法错误。

```abap
DATA gs_key TYPE ty_po.
SELECT-OPTIONS s_ebeln FOR gs_key-ebeln.
```

顺带：`s_ebeln` 建在 `ebeln`（NUMC 10）上没加 `NO_INTERVALS` / `NO_SIGN`，用户能填区间和正负号；配合第 2 节的空选择问题，风险会放大。

### 1.2 私有属性被外部赋值

```abap
CLASS lcl_event_handler DEFINITION FINAL.
  PRIVATE SECTION.
    DATA mv_show TYPE REF TO cl_salv_table.   " 35-36
ENDCLASS.

...
CREATE OBJECT go_handler.
go_handler->mv_show = lo_alv.                  " 137  ← 语法错误
```

ABAP **没有 friend 机制**，`lcl_handler->display_alv` 里访问 `lcl_event_handler` 的 private 组件会直接编译失败。`mv_show` 除了这条赋值之外**全程序再无任何引用**，也就是说修掉这个错误之后，唯一的影响是"少一个死字段"。最小改法是**直接删掉 `mv_show` 和第 137 行**；如果真要保留一个保活引用，就放到 public 并加 setter。

### 1.3 `mt_data` 是单行结构，却被当表用（三重错误）

```abap
DATA mt_data TYPE ty_po.                            " 48  单行，不是表
...
SELECT ebeln lifnr bedat waers netwr kumvw AS menge
  FROM ekko
  INTO TABLE mt_data            " 76  ← INTO TABLE 要求内表
  WHERE ebeln IN s_ebeln.

LOOP AT mt_data INTO DATA(ls_row).   " 79  ← LOOP AT 要求内表
  ...
  MODIFY mt_data FROM ls_row.        " 81  ← 修改的是单行结构，不是表行
```

`mt_data TYPE ty_po` 应该是 `TYPE STANDARD TABLE OF ty_po WITH EMPTY KEY`。但即使改对，这段代码也**应该整体删掉**（见 2.1）。

### 1.4 字段名疑似笔误 **[需验证]**

```abap
SELECT ... kumvw AS menge FROM ekko ...
```

EKKO 的总数量字段是 `KUMQW`（`kumvw` 看起来是字母顺序打反的笔误）。请在 SE11 打开 EKKO 确认；若确实不存在，Open SQL 会在编译/激活时报"字段未找到"。

另外 `ty_po` 里 `menge TYPE ekko-kumqw` 定义是对的，**别名 `kumvw AS menge` 是错的**——说明作者知道正确字段名，只是写 SQL 时敲错了。

### 1.5 顺带：`ekko-ebeln_txt` **[需验证]**

`ebeln_t TYPE ekko-ebeln_txt` 需要确认 EKKO 是否真有这个组件（PO 的"文本"字段通常在 `EKPO-TEXT1` 或 `MAKT`）。而且即使存在，赋的值是：

```abap
ls_row-ebeln_t = |Order { ls_row-ebeln }|.   " 80
```

这只是把主键换个前缀再打一遍，**信息量为零**。这一列要么删掉，要么改成真正有业务含义的内容（比如供应商名称 `maktx`）。

---

## 2. 取数（`get_data`）：问题最多的一块 ❌

### 2.1 同一份数据查了两次，第一次的结果被完全丢弃

```abap
SELECT ebeln lifnr bedat waers netwr kumvw AS menge
  FROM ekko INTO TABLE mt_data WHERE ebeln IN s_ebeln.      " 第一次
LOOP AT mt_data INTO DATA(ls_row).
  ls_row-ebeln_t = |Order { ls_row-ebeln }|.
  MODIFY mt_data FROM ls_row.
ENDLOOP.

SELECT ebeln bedat waers netwr
  INTO TABLE @gt_po
  FROM ekko
  WHERE ebeln IN s_ebeln AND waers = 'EUR'.                   " 第二次
```

两次都是全量读 EKKO、WHERE 条件几乎相同。**ALV 最终绑定的是 `gt_po`**，`mt_data` 算完 `ebeln_t` 就被扔了。等于白白多打一次 DB、还多一个坏掉的内表。正确做法是只查一次，一次查全，一次填长文本。

### 2.2 内部表结构与 select list 位置错位（最隐蔽的一个）

```abap
TYPES: BEGIN OF ty_po,          " 字段顺序：
         ebeln   TYPE ekko-ebeln,     -- 1
         lifnr   TYPE ekko-lifnr,     -- 2
         bedat   TYPE ekko-bedat,     -- 3
         waers   TYPE ekko-waers,     -- 4
         netwr   TYPE ekko-netwr,     -- 5
         menge   TYPE ekko-kumqw,     -- 6
         ebeln_t TYPE ekko-ebeln_txt, -- 7
       END OF ty_po.

SELECT ebeln bedat waers netwr INTO TABLE @gt_po FROM ekko ...   " 只有 4 个
```

**Open SQL 对已声明内表的 `INTO TABLE` 是按位置（select list 顺序 ↔ 结构分量定义顺序）映射的**，不是按字段名。所以实际落位是：

| select list | 落到哪个分量 | 结果 |
|---|---|---|
| `ebeln` | `ebeln` | ✅ 碰巧正确 |
| `bedat` | **`lifnr`** | ❌ 把日期塞进供应商号 |
| `waers` | **`bedat`** | ❌ CHAR3 → DATS，类型不可转换，会 dump 或写垃圾 |
| `netwr` | **`waers`** | ❌ CURR → CHAR3，同上 |
| — | `menge` / `ebeln_t` | ❌ 保持初始值，列全空 |

所以**不只"少了两列"，而是从第 2 个字段开始整体错位**。修法是让 select list 与结构顺序严格一致、并补全所有分量：

```abap
SELECT ebeln, lifnr, bedat, waers, netwr, kumqw AS menge
  FROM ekko
  INTO TABLE @gt_po
  WHERE ebeln IN s_ebeln
    AND waers = @lv_waers.

LOOP AT gt_po ASSIGNING FIELD-SYMBOL(<po>).
  <po>-ebeln_t = ...
ENDLOOP.
```

这条"位置对齐"是**长期维护陷阱**：以后谁在 `ty_po` 中间插一个字段，或者给 SELECT 加一列，值会静默错位，编译和运行都不报错。务必在结构上写注释固定这个约定，或者干脆只在内联 `SELECT ... INTO TABLE @DATA(...)` 处声明，字段顺序由 SELECT 自己决定。

### 2.3 空选择 → 全表拉取（生产事故级）

```abap
SELECT-OPTIONS s_ebeln FOR gs_key-ebeln.     " 57
INITIALIZATION.
  gs_key-ebeln = '0000000001'.               " 61  硬编码一张示例 PO
```

- 用户把选择屏清空 → `s_ebeln` 为空内表 → `WHERE ebeln IN s_ebeln` 变成**无条件** → 全量 EKKO 进全屏 ALV → dump。
- `INITIALIZATION` 里又硬编码了 `'0000000001'`，结果正常使用时用户看到的**永远只是一张采购订单**，而这个"默认只看一张单"的行为完全没在任何地方说明。

```abap
IF s_ebeln[] IS INITIAL.
  MESSAGE '请输入采购订单号（支持区间）' TYPE 'S'.
  LEAVE LIST-PROCESSING.
ENDIF.
```

建议同时设成 `OBLIGATORY` 或给个日期区间默认，并把 `INITIALIZATION` 里的硬编码去掉（改到 `AT SELECTION-SCREEN OUTPUT` 里给默认值，或干脆留空）。

### 2.4 `waers = 'EUR'` 是个隐形业务规则

```abap
WHERE ebeln IN s_ebeln
  AND waers = 'EUR'.      " 88
```

这个过滤条件：不在任何注释里、不在选择屏上、不在 ALV 标题里。用户看到的是"采购订单总览 + 合计金额"，实际是"只看欧元单"。更糟的是它和第 3 节的"合计"耦合：正因为这里把币种压成了单一，NETWR 的 total 才**恰好**能相加——一旦有人把 `'EUR'` 改成注释掉或参数化，合计金额就变成**不同币种直接相加的废数**，且不会有任何报错。

正确做法：币种做成选择项（`RANGES`/参数），或者至少把"合计仅含 XX 币种"写进 `set_header_text` / 页脚。

### 2.5 `WITH EMPTY KEY` 用错了地方

```abap
DATA gt_po   TYPE STANDARD TABLE OF ty_po WITH EMPTY KEY.    " 52
```

`gt_po` 里 `ebeln` 是 EKKO 的主键，天然唯一，应该用 `WITH UNIQUE KEY ebeln`。有了 key 才能在事件里用 `READ TABLE gt_po WITH KEY ebeln = ...` 做 O(1) 定位（见第 4 节）。`WITH EMPTY KEY` 只能按位置 `INDEX` 读，恰好是当前出问题的读法。

### 2.6 `WRITE` 调试残留

```abap
WRITE: / 'loaded', lines( gt_po ).    " 90
```

生产代码里的调试输出，显示在 ALV 之前，且和 ALV 实际行数无关（用户筛选后它不会变）。删掉，换成 `IF gt_po IS INITIAL. MESSAGE '无数据' TYPE 'S'. ENDIF.`

### 2.7 其他

- **无授权检查**。采购订单读取通常需要 `EKO*` / 采购单显示类对象，全表拉取尤其危险。
- 转义风格不统一：第 85 行写 `INTO TABLE @gt_po`（带 escape），第 76/151 行不带。统一都带。
- `mt_data` 走 LOOP + 单行 MODIFY 是 O(n) 逐行改，量大时不如直接 `ASSIGNING` 改，更不如别查第二遍。

---

## 3. 聚合（`add_aggregation`）：API 对，语义错 ⚠️

```abap
lo_aggr = lo_alv->get_aggregations( ).
TRY.
    lo_aggr->add_aggregation(
      EXPORTING  columnname  = 'NETWR'
                 aggregation = if_salv_c_aggregation=>total ).
  CATCH cx_salv_data_error.
  CATCH cx_salv_not_found.
ENDTRY.
```

### 3.1 写对的部分 ✅

- `get_aggregations( )` 拿对象、`add_aggregation( )` 加 total、列名大小写与 `ty_po` 分量名一致（`NETWR`）、`if_salv_c_aggregation=>total` 常量用对了。
- 一行 `NETWR` 就是一张 PO 的表头净价，**不是明细行**，所以"每行 = 一条记录"的前提下，total 确实等于"所有订单净额之和"，这个粒度是对的。
- 异常类型也覆盖到了：列不存在抛 `cx_salv_not_found`，列不可聚合抛 `cx_salv_data_error`。

### 3.2 语义问题

**(a) 金额列没有币种参照。** `WAERS` 在结构里存在，但代码从没把它显示出来，也没告诉 NETWR 用它做参照：

```abap
lo_col ?= lo_cols->get_column( 'NETWR' ).
lo_col->set_cell_type( if_salv_c_cell_type=>numeric ).      " 134
```

正确写法应该加币种参照与表头说明，否则总额那一行的"总计"是个没有货币的裸数字：

```abap
lo_col->set_currency( 'WAERS' ).
lo_aggr->add_aggregation(
  EXPORTING  columnname     = 'NETWR'
             aggregation    = if_salv_c_aggregation=>total
             header_text    = 'Total (document currency)' ).
```

**(b) 数量列不设单位，却被当成可加字段。** `MENGE` 映射到 `EKKO-KUMQW`（总数量），而 `ty_po` **没有任何单位字段**（没有 `meins`/`umrenz`）。两个后果：
- `lo_col->set_unit( '...' )` 没法用（找不到承载单位的列）；
- 就算你把 `MENGE` 也加成 total，不同计量单位相加是无意义的数字。

要么给结构补单位字段，要么**不要汇总数量**，只汇总金额（推荐后者，最省事且不出错）。

**(c) CATCH 把失败吃掉了。** `CATCH ... ENDTRY` 里**没有任何处理**（没有 MESSAGE、没有日志）。如果将来有人把 `NETWR` 改成 `BEDAT`（DATS）并去加 total，会抛 `cx_salv_data_error`，程序**静默继续，用户看不到任何总计**——一个"看起来正常其实算错了"的报表，比直接 dump 更危险。最少也该：

```abap
CATCH cx_salv_data_error cx_salv_not_found.
  MESSAGE '金额合计不可用，请检查列类型' TYPE 'S'.
```

或者干脆不 TRY（让它早期失败），因为这个 total 是报表的核心输出，静默降级不可接受。

**(d) 只在异常路径上生效的顺序问题。** `add_aggregation` 在 `get_columns( )` 之前调用（第 113 行 vs 第 130 行）没问题，但聚合对象一旦创建，列不存在时 `cx_salv_not_found` 只会在**激活时**才可靠暴露。这里因为 `NETWR` 确实存在，碰巧没事。

**(e) 合计行的语义没有落到界面上。** `set_default( abap_true )` + `set_save_restriction( restrict_none )` 允许用户保存变式，用户完全可以把"合计"相关的显示改掉而无人知晓。建议配 `set_header_text` / 页脚把"合计口径（仅 EUR、仅表头净价）"写死。

### 3.3 布局部分 ✅ 但可以更好

```abap
lo_layout->set_key( VALUE #( report = sy-repid ) ).                              -- ✅
lo_layout->set_default( abap_true ).                                              -- ✅
lo_layout->set_save_restriction( if_salv_c_layout=>restrict_none ).               -- ⚠️
lo_disp->set_striped_pattern( abap_true ).                                        -- ✅
```

`restrict_none` 允许用户在用户 profile 里存任意变式（含变 Aggregate）。报表类程序通常用 `restrict_standard` 更稳（保留标准 aggregate、禁止被覆盖）。另外**没有任何列被 `set_key( abap_true )`**——`EBELN` 是天然主键列，标记成 key 列后排序、导出、变式都会稳定得多，顺带解决 4.4 的一半问题。

---

## 4. 事件绑定（`SET HANDLER`）：生命周期写对了，其余有坑 ⚠️

```abap
CREATE OBJECT go_handler.
go_handler->mv_show = lo_alv.                                     " 137  ❌ 私有属性
lo_events = lo_alv->get_event( ).
SET HANDLER go_handler->on_double_click FOR lo_events.            " 139
SET HANDLER go_handler->on_link_click   FOR lo_events.            " 140
lo_alv->display( ).
```

### 4.1 写对的关键点 ✅（这是本程序最好的一处）

`lo_events` 是方法内的局部变量，但它指向的是 `lo_alv` **内部持有的事件对象**。`SET HANDLER ... FOR <事件对象>` 是注册到这个对象上的，只要 `lo_alv` 活着，注册就活着；而 `lo_alv` 又被 `display( )` 挂到了屏幕上。

同时 handler 对象 `go_handler` 是**全局引用**，所以即使 `display_alv` 返回、局部变量全部失效，ABAP 对象也不会被 GC 掉，回调不会变成野引用。这是事件绑定里最容易踩的一个坑，这个程序避开了。**前提是 `go_handler` 必须保持全局**——如果哪天有人"优化"成 `display_alv` 的局部变量，事件会静默失效或直接 dump。值得加一行注释锁死这个约定。

### 4.2 `on_link_click` 永远不会触发 ❌

```abap
lo_col->set_cell_type( if_salv_c_cell_type=>numeric ).    " 134  NETWR
```

**`link_click` 只会由"以链接/热点形式渲染的单元格"触发**，也就是说必须先有列被设成 `link_text` / `hotspot`：

```abap
lo_col ?= lo_cols->get_column( 'EBELN' ).
lo_col->set_cell_type( if_salv_c_cell_type=>link_text ).
```

当前程序里**没有任何一列被设成链接或热点**（只有 `NETWR` 被设成 `numeric`），所以 `on_link_click` 是一个纯死代码处理器：

```abap
METHOD on_link_click.
  READ TABLE gt_po INTO DATA(ls_po) INDEX row.
  WRITE: / 'clicked', ls_po-ebeln, column.    " 188
ENDMETHOD.
```

顺带两个细节：
- `column` 是**技术列 ID（整数）**，不是字段名。`WRITE` 出来对用户毫无意义，也无法据此判断"点的是哪一列"。
- 这里**没有检查 `sy-subrc`**，读失败后 `ls_po` 保持未初始化，`WRITE` 会输出乱码/空值；下一行 `column` 照打。

### 4.3 `on_double_click` 忽略了 `column`

```abap
METHOD on_double_click.
  IMPORTING row column.    -- column 声明了但完全没用
```

后果：用户在**任意单元格**上双击都会触发下钻——双击金额、双击日期、甚至双击空白区域右侧，都会弹出一个"订单明细"。而报错行（`row` 越界）时只 `RETURN`，体验不明确。至少应该：

```abap
IF column <> <EBELN 列的 ID> THEN RETURN. ENDIF.
```

更好的做法是**把入口收窄**（见下），而不是去比较技术 ID：把 `EBELN` 设成 link 类型，让 `link_click` 成为唯一的下钻入口，`double_click` 直接不注册。

### 4.4 `row` 当"行号"用，不严谨 ⚠️

```abap
READ TABLE gt_po INTO DATA(ls_po) INDEX row.   " 165 / 187
```

`row` 是 `salv_row_id`，即 ALV 数据集里的**行标识**，不是"表格里的物理第 N 行"。ALV 是在自己的数据层排序/筛选的，**你传给 `CHANGING t_table` 的 `gt_po` 不会跟着重新排序**。所以：

- 用户在 ALV 上点一下表头排序 → 显示顺序变了 → `row` 与 `gt_po` 的物理行号**不再对应** → 弹出的是**另一张订单的明细**。
- 用户加筛选/模式匹配 → 同样错位。
- 而且这种错位**不报错**，属于"看起来完全正常但结果是错的"型缺陷，是本报表最贵的一个坑。

正确解法是建一张 rowid → 主键的映射表，在交给 ALV 之前填好（rowid 在排序/筛选下是稳定的，跟着行走）：

```abap
DATA gt_rowkey TYPE HASHED TABLE OF key WITH UNIQUE KEY rowid.
DATA key  TYPE ebeln.
DATA rowid TYPE salv_row_id.

LOOP AT gt_po INTO DATA(<po>).
  rowid = sy-tabix.
  gt_rowkey[ rowid ] = <po>-ebeln.
ENDLOOP.
```

事件里：

```abap
READ TABLE gt_rowkey INTO DATA(lv_ebeln) WITH TABLE KEY rowid = row.
IF sy-subrc <> 0. RETURN. ENDIF.
go_report->show_items( iv_ebeln = lv_ebeln ).
```

如果不想维护映射表，退而求其次的两种办法：给 `gt_po` 加 `WITH UNIQUE KEY ebeln` 然后用主键找（但你只有 rowid，还是绕回映射表），或者**自己排序 `gt_po` 并禁用 ALV 排序**（`lo_layout->set_sort( abap_false )`）——代价是牺牲交互。

### 4.5 缺少的事件

- 没有 `user_command` / `standard_command`：标准工具栏只有导出/保存，没有任何业务功能键（比如"查看订单"、"选定标记行"）。
- 没有 `on_refresh`：如果将来做了刷新，handler 里的 rowid 映射会失效。
- `CREATE OBJECT go_handler` 在 `display_alv` 里（136 行）。当前流程只调用一次所以没事，但**若 `display_alv` 被调用两次，旧 handler 仍被事件对象持有**，会出现双份注册（一次点击触发两次下钻）且旧对象泄漏。handler 应该移到 `START-OF-SELECTION` 创建，或改成有引用计数。

### 4.6 类的划分问题

`lcl_event_handler` 定义在 `lcl_handler` **之前**，但反向调用 `go_report->show_items( )`（170 行）。两个类互相知道对方，事件类还持有了一个 ALV 引用（却没用）。而 `lcl_handler` 的 `mt_data` 是个**永远不会被 ALV 使用的**私有内表（ALV 绑的是全局 `gt_po`）——"我以为类是数据所有者、其实数据在全局"的半吊子封装。

建议二选一：
- **务实方案（改动小）**：接受"报表全局 + 一个工具类"的风格，删掉 `mv_show`、把 `mt_data` 全删、handler 里通过 `get_data( )`/`show_items( )` 这类 public 方法访问数据。
- **干净方案**：数据表作为构造参数传进事件 handler，事件类只负责"拿到行 → 取到 key → 回调显示"，不持有 ALV 引用，也不直接操作报表对象。

---

## 5. 下钻弹窗（`show_items` + `on_double_click`）：❌

### 5.1 流程梳理

```
双击 ALV
  → on_double_click(row, column)
      → READ TABLE gt_po INDEX row          (错位风险，见 4.4)
      → go_report->show_items( ebeln )        (gt_item 全局，查询 EKPO)
      → cl_salv_table=>factory( t_table = gt_item )
      → lo_popup->display( )
```

整体骨架是标准的"主 ALV + 弹出子 ALV"，方向没问题。问题都在实现细节。

### 5.2 `lo_popup` 可能未初始化 → dump ❌

```abap
DATA lo_popup TYPE REF TO cl_salv_table.
TRY.
    cl_salv_table=>factory(
      EXPORTING list_display = if_salv_c_bool_sap=>false
      IMPORTING r_salv_table  = lo_popup
      CHANGING  t_table       = gt_item ).
    CATCH cx_salv_msg.        " 177  ← 空的
  ENDTRY.

lo_popup->display( ).         " 180  ← 无条件解引用
```

`CATCH` 之后**没有 `RETURN`**，接着就无条件 `lo_popup->display( )`。一旦 factory 抛 `cx_salv_msg`，`lo_popup` 保持初始引用 → **`CX_SY_REF_IS_INITIAL` 短转储**。

对比 `display_alv` 第 105-111 行，同样的模式但 CATCH 里**有** `RETURN`——说明作者知道要 return，只是复制粘贴时漏了。这也是最典型的"异常吞掉 + 缺卫语句"组合。

```abap
CATCH cx_salv_msg.
  MESSAGE '明细无法显示' TYPE 'S'.
  RETURN.
```

### 5.3 弹窗数据源用了全局 `gt_item` ❌

```abap
DATA gt_item TYPE STANDARD TABLE OF ty_item WITH EMPTY KEY.   " 53 全局

METHOD show_items.
  SELECT ebeln posnr matnr menge netwr
    FROM ekpo INTO TABLE gt_item WHERE ebeln = iv_ebeln.     " 149-152
ENDMETHOD.
```

后果：每次双击都**覆盖同一张全局表**。弹窗 A 和弹窗 B 共享同一个数据源——用户开两个弹窗、或者给弹窗加了排序/筛选后再双击另一行，两个弹窗的内容会互相污染。对比主 ALV 用的是 `CHANGING t_table = gt_po`（全局）、`show_items` 也是全局，一眼看不出"这里的表是每次现造的"。

正确做法：`show_items` **返回**数据，而不是往全局里塞：

```abap
METHOD show_items
  RETURNING VALUE(rt_item) TYPE ty_item_t.
  SELECT ebeln, posnr, matnr, menge, netwr
    FROM ekpo
    INTO TABLE @rt_item
    WHERE ebeln  = @iv_ebeln
      AND posnr <> '00000'
      AND elik  <> 'X'.
ENDMETHOD.
```

调用方用局部变量 `DATA(lt_item) = go_report->show_items( ... )`，弹窗的数据生命周期就跟这次点击绑定，不再有交叉污染。

### 5.4 查 EKPO 缺两个必备过滤条件 ❌

```abap
SELECT ebeln posnr matnr menge netwr FROM ekpo
  INTO TABLE gt_item WHERE ebeln = iv_ebeln.
```

SAP 的采购订单项目表里，**每一张 PO 都在 `EKPO` 存了一条 `POSNR = '00000'` 的表头条目**（用于存放抬头级信息）。现在这个查询没有排除它，于是：

- 每张订单的明细列表**顶部都多出一行"项目 00000"**，数量/金额通常是 0 或垃圾值；
- 行数、`lines( )` 统计、任何按明细求和的逻辑**全部虚高一条**；
- 用户会直接把它当成数据错误报过来。

同时**没有排除已删除行**：SAP 用 `EKPO-ELIK = 'X'` 标记删除/作废的项目，不排除的话会把作废项目当有效明细展示。

```abap
WHERE ebeln  = @iv_ebeln
  AND posnr <> '00000'      " 排除表头条
  AND elik  <> 'X'          " 排除删除项
```

这是本报表**业务层面最容易被用户投诉**的一个点，且它和"聚合"直接相关：如果后续给弹窗加合计，这一行假数据会直接污染金额。

### 5.5 弹窗本身的功能缺失

- **没有合计**。主 ALV 加了 total，弹窗没有。采购员点进去看 20 行明细，金额得自己加。
- **`MENGE` 没有单位**。`EKPO-MENGE` 是 QUAN，标准做法要带 `EKPO-MEINS`（或其转换单位字段），否则 3 PCS 和 3 KG 并排显示、还可能被误加总。`ty_item` 里根本没有单位字段。
- **`NETWR` 没有币种**。明细金额同样要 `set_currency( 'WAERS' )`（`EKPO-WAERS` 或直接继承抬头币种），弹窗里也没有。
- **弹窗无法关闭/刷新**。`lo_popup` 是方法内局部变量，`display( )` 后就丢了引用——屏幕上的弹窗靠 SAP GUI 存活没问题，但程序**再也拿不到它的句柄**，既不能 `close( )`，也不能在数据变化后 `refresh( )`。想要交互就得：

```abap
DATA gv_popup TYPE REF TO cl_salv_table.     " 全局
... gv_popup = ...; gv_popup->display( ).
```

- **没有空结果处理**。`show_items` 没查到数据（订单无项目、全部被 ELIK 排除）时，弹窗是一个空 ALV，用户一脸茫然。`IF gt_item IS INITIAL. MESSAGE '无明细' TYPE 'S'. ENDIF.`

### 5.6 `go_report` 未做有效性检查

```abap
go_report->show_items( iv_ebeln = ls_po-ebeln ).   " 170
```

`go_report` 在 `START-OF-SELECTION` 里创建，而事件只可能在 `display( )` 之后触发，所以当前流程下不会为空。但**事件类依赖一个全局单例、且不做校验**，任何"ALV 复用/提前触发"的改动都会变成空引用 dump。加一行 `IF go_report IS INITIAL. RETURN. ENDIF.` 成本极低。

---

## 6. 其余代码质量观察

| 位置 | 问题 | 建议 |
|---|---|---|
| 16-17 行 | `ebeln_t` 只是把主键加前缀，信息量为零 | 删掉，或改填供应商名 / 订单类型文本 |
| 15-16 行 | `MENGE` 类型是 `kumqw`（数量）但名字像数量单位 | 重命名为 `kumqw` 或 `gesmenge`，避免误用 |
| 52-53 行 | `WITH EMPTY KEY` 用在主键表上 | `gt_po` 用 `WITH UNIQUE KEY ebeln` |
| 61 行 | `INITIALIZATION` 里硬编码示例 PO 号 | 去掉，改用选择屏默认或留空 |
| 90 行 | `WRITE` 调试输出 | 删；空结果用 `MESSAGE` |
| 122-125 行 | `set_key( sy-repid )` 但没有 `set_key( )` 列 | 给 `EBELN` 列加 `set_key( abap_true )` |
| 123 行 | `VALUE #( report = sy-repid )` 每次生成新变式键 | 可用常量/程序名常量，风格问题 |
| 74/85/149 行 | 转义风格 `@` 不统一 | 统一带 `@` |
| 全程序 | 无授权检查 | 补 `AUTHORITY-CHECK` |
| 全程序 | 无 `AT SELECTION-SCREEN` 校验 | 校验数字、限制区间个数 |

---

## 7. 修改优先级

**P0（不修就跑不了 / 会 dump）**
1. `DATA gs_key` 移到 `SELECT-OPTIONS` 之前（1.1）
2. 删掉 `mv_show` 及 `go_handler->mv_show = lo_alv`（1.2）
3. 删除 `mt_data` 与第一次 SELECT + LOOP（1.3、2.1）
4. `kumvw` → `kumqw` **[需验证]**（1.4）
5. `CATCH cx_salv_msg` 后补 `RETURN`（5.2）
6. 选择屏空值检查（2.3）
7. select list 与 `ty_po` 顺序对齐并补全字段（2.2）

**P1（会给出错误结果）**
8. rowid → EBELN 映射表，替换 `READ TABLE ... INDEX row`（4.4）
9. `EKPO` 排除 `posnr = '00000'` 与 `elik = 'X'`（5.4）
10. `gt_item` 改为方法返回值（5.3）
11. `NETWR` 设 `set_currency( 'WAERS' )`（3.2a）
12. 聚合异常不要静默吞（3.2c）

**P2（体验 / 可维护性）**
13. `EBELN` 设成 link/hotspot 列，删掉永不触发的 `on_link_click`，或补上 `set_cell_type( link_text )`（4.2）
14. `double_click` 检查 `column`（4.3）
15. `EBELN` 列 `set_key( abap_true )`（3.3）
16. 弹窗加合计、补 `MEINS`/`WAERS`、空结果提示（5.5）
17. 删调试 `WRITE`、加授权检查、抽掉硬编码 EUR 或写进页脚（2.4、2.6、2.7）
18. 统一 `@` 转义风格、补注释锁定"handler 必须全局"这一隐含约定

---

## 8. 参考骨架（P0 修完后的形态）

```abap
REPORT zsalv_po_list.

TYPES: BEGIN OF ty_po,
         ebeln TYPE ekko-ebeln,
         lifnr TYPE ekko-lifnr,
         bedat TYPE ekko-bedat,
         waers TYPE ekko-waers,
         netwr TYPE ekko-netwr,
         ktz   TYPE ekko-kumqw,
       END OF ty_po,
       ty_po_t TYPE STANDARD TABLE OF ty_po WITH UNIQUE KEY ebeln.

TYPES: BEGIN OF ty_item,
         ebeln TYPE ekpo-ebeln,
         posnr TYPE ekpo-posnr,
         matnr TYPE ekpo-matnr,
         menge TYPE ekpo-menge,
         meins TYPE ekpo-meins,
         netwr TYPE ekpo-netwr,
         waers TYPE ekpo-waers,
       END OF ty_item,
       ty_item_t TYPE STANDARD TABLE OF ty_item WITH EMPTY KEY.

CLASS lcl_app DEFINITION FINAL.
  PUBLIC SECTION.
    METHODS constructor.
    METHODS run.
  PRIVATE SECTION.
    DATA mt_po    TYPE ty_po_t.
    DATA ms_key   TYPE ty_po.
    METHODS get_data RETURNING VALUE(rt) TYPE ty_po_t.
    METHODS build_alv( it_po TYPE ty_po_t ).
ENDCLASS.

CLASS lcl_evt DEFINITION FINAL.
  PUBLIC SECTION.
    METHODS on_link
      FOR EVENT link_click OF cl_salv_events_table
      IMPORTING row column.
  PRIVATE SECTION.
    DATA mo_app  TYPE REF TO lcl_app.
    METHODS on_link DOUBLE CLICK 重构后唯一入口
ENDCLASS.

DATA gv_po     TYPE ty_po_t.
DATA gv_rowkey TYPE HASHED TABLE OF ty_po WITH UNIQUE KEY rowid ebeln.
DATA gv_popup  TYPE REF TO cl_salv_table.
DATA go_app    TYPE REF TO lcl_app.

SELECT-OPTIONS s_ebeln FOR ms_key-ebeln.

INITIALIZATION.
  s_ebeln-low = '0000000001'.   " 仍建议去掉

START-OF-SELECTION.
  IF s_ebeln[] IS INITIAL.
    MESSAGE '请输入采购订单号' TYPE 'S'.
    LEAVE LIST-PROCESSING.
  ENDIF.

  gv_po = go_app->get_data( ).
  IF gv_po IS INITIAL.
    MESSAGE '未找到数据' TYPE 'S'.
  ENDIF.

  go_app->build_alv( gv_po ).
```

关键点：`rowid` 映射表在 `build_alv` 里、`display( )` 之前填好；`link_click` 是唯一下钻入口；弹窗数据由方法返回；所有 CATCH 都带处理 + `RETURN`；`EKPO` 排除 `00000` 与 `ELIK`。

---

## 9. 自测清单

改完以后，逐条在 SE38 + ALV 里验证：

1. 选择屏留空直接执行 → 应给出提示，**不能** dump。
2. 输入一张**欧元**订单、一张**美元**订单 → 确认 `waers` 列显示、金额列带币种、合计口径与页脚一致。
3. 在 ALV 上点 `BEDAT` 表头排序 → 双击第一行 → **必须弹出那一行的订单明细**（这是验证 4.4 的关键用例）。
4. 在 ALV 上加筛选/模式匹配 → 再次双击 → 明细对应正确。
5. 双击一行有 20 个项目的订单 → 明细**没有 `00000` 这一行**。
6. 双击一张项目全部作废（`ELIK = 'X'`）的订单 → 提示"无明细"而不是空白 ALV。
7. 连续双击 3 个不同订单 → 三个弹窗内容互不干扰（验证 5.3）。
8. 人为把 NETWR 改成非数值列再激活 → 聚合失败时必须有提示，不许静默（验证 3.2c）。
9. `EBELN` 列显示为链接样式（蓝色带下划线），双击非链接列**不**触发下钻。
10. 保存一个 ALV 变式 → 重进程序 → 布局正确恢复，且合计行仍在。

---

**一句话总结**：事件绑定的"保活"思路和聚合的 API 选择都走对了路，但取数层有一个会静默错位的位置映射问题、有一个空选择全表拉取的 dump 风险、有一个写死的币种业务规则；下钻层有一个必现的未初始化引用和一个 SAP 特有的 `POSNR = '00000'` 假数据；而整份程序目前**编译都过不去**。先修 P0 的 7 条，再谈体验。
