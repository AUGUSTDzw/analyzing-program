# ZSALV_PO_LIST 分析报告

> 结论先给：**这份程序目前编译不过**（3 处硬错误），而且即使修掉语法，`get_data` / `display_alv` / `on_double_click` 三块都存在"能跑但结果错"的逻辑缺陷。四块的判断：
>
> | 板块 | 判断 |
> |---|---|
> | 取数 | ❌ 两次重复 SELECT + 字段名拼错 + 静默无效的 MODIFY + 过滤条件与选择屏不一致 |
> | 聚合 | ⚠️ API 调用本身写对了、异常也兜住了，但加在了一份"被裁剪过且只留 EUR"的数据上，且金额按 numeric 显示 |
> | 事件绑定 | ❌ 访问 private 属性（编译错误）+ 绑了永远不会触发的 link_click |
> | 下钻弹窗 | ❌ 用 `INDEX row` 反查底表（排序后必然错行）+ 弹窗引用可能未绑定仍被解引用 |

---

## 1. 程序概览

| 项目 | 内容 |
|---|---|
| 类型 | 传统 `REPORT`（非 OO ALV 调用点，无 Function Pool） |
| 数据源 | `EKKO`（采购订单抬头）× 1，`EKPO`（订单项目）× 1 |
| 展示 | 主 ALV：`CL_SALV_TABLE` 全屏网格 + `NETWR` 合计 |
| 交互 | 双击行 → 下钻到订单项目 ALV |
| 结构 | `lcl_handler`（取数 + 展示 + 下钻查询）、`lcl_event_handler`（ALV 事件回调）、2 个全局内表 + 3 个全局引用 |

执行流：

```
INITIALIZATION  →  gs_key-ebeln 硬编码
START-OF-SELECTION → get_data (EKKO ×2) → display_alv (工厂 + 聚合 + 布局 + 列 + 事件)
                                        ↓
                          用户双击 / 点击链接
                                        ↓
                        lcl_event_handler → show_items (EKPO) → 弹窗 ALV
```

骨架（工厂、事件对象、`SET HANDLER`、`WITH EMPTY KEY` 内表）的**写法方向是对的**，说明作者知道 SALV 的基本套路；问题都出在细节和一致性上。

---

## 2. 取数（`get_data`）—— ❌

### 2.1 两次结构不同的 SELECT，其中一次是死代码

```abap
  SELECT ebeln lifnr bedat waers netwr kumvw AS menge
    FROM ekko INTO TABLE mt_data
    WHERE ebeln IN s_ebeln.

  LOOP AT mt_data INTO DATA(ls_row).
    ls_row-ebeln_t = |Order { ls_row-ebeln }|.
    MODIFY mt_data FROM ls_row.
  ENDLOOP.

  SELECT ebeln bedat waers netwr
    INTO TABLE @gt_po
    FROM ekko
    WHERE ebeln IN s_ebeln
      AND waers = 'EUR'.
```

问题：

1. **同一个逻辑对象被查了两遍**，字段列表还不一致。`mt_data` 有 `LIFNR`、`MENGE`、`EBELN_T`，但**从未被展示**——`display_alv` 传的是 `gt_po`，而 `gt_po` 里没有供应商、没有数量、没有描述。一个叫"采购订单总览"的报表不显示供应商，这是需求缺口。
2. **`mt_data` 这个命名是错的**：类型是 `ty_po`（行类型）不是表类型，`mt_` 前缀误导后来人。
3. **`WHERE` 条件不一致**：选择屏只给了 `EBELN`，代码却私自加了 `waers = 'EUR'`。用户在选择屏选一堆美元订单 → ALV 空白，而且**没有任何提示**（没有 `MESSAGE`、没有 `sy-subrc` 检查）。这是典型的"报表静默少数据"，排查成本极高。
4. `WRITE: / 'loaded', lines( gt_po ).` —— 调试残留，会在列表头上留一行输出。上生产前必须删。

### 2.2 `kumvw` 字段不存在 —— 硬错误

```abap
    SELECT ebeln lifnr bedat waers netwr kumvw AS menge
```

`EKKO` 上的字段是 **`KUMQW`**（Total Quantity），不是 `KUMVW`。这个 `AS menge` 只是别名，无法掩盖字段名错误：OpenSQL 的字段清单在运行时才校验，运行到这条 SELECT 会 **SQL 错误 short dump**（`Field KUMVW not known in table EKKO`）。

顺带：`ty_po` 里写的是 `menge TYPE ekko-kumqw`，别名和源字段已经对不上，属于同一处笔误的两面。

### 2.3 `MODIFY mt_data FROM ls_row` 是无效操作 —— 静默不生效

```abap
  LOOP AT mt_data INTO DATA(ls_row).
    ls_row-ebeln_t = |Order { ls_row-ebeln }|.
    MODIFY mt_data FROM ls_row.      " ← 永远匹配不到
  ENDLOOP.
```

`mt_data` 是 `TYPE ty_po`（标准内表，**没有主键**，也没建二级键）。对无键内表，`MODIFY ... FROM wa` 不带 key 指定时按**整行**匹配。而此时：

- 表里那一行的 `ebeln_t` 是初始值（空）
- `ls_row-ebeln_t` 刚被赋成 `Order 0000000001`

整行不相等 → **一条都匹配不上**，`ebeln_t` 永远填不进去，而且**不报任何错**。附带 O(n²)。

正确写法（任选）：

```abap
  LOOP AT mt_data ASSIGNING FIELD-SYMBOL(<row>).
    <row>-ebeln_t = |Order { <row>-ebeln }|.
  ENDLOOP.
```

或者 `MODIFY mt_data FROM ls_row INDEX sy-tabix.`

### 2.4 其他取数风险

- `INITIALIZATION. gs_key-ebeln = '0000000001'` —— 硬编码测试订单号，会覆盖 Layout 里存的选择屏默认值，生产环境必须删除。
- `SELECT-OPTIONS s_ebeln` 没有 `AT SELECTION-SCREEN` 校验（空选择 → 全表扫描；范围过大 → 内存/超时）。
- `EKKO` 无 `MANDT` 之外的任何组织限制，也**没有 `AUTHORITY-CHECK`**，等于全量放行采购订单数据。

---

## 3. 聚合（`add_aggregation`）—— ⚠️ API 对，数据错

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

**对的部分**（值得肯定）：

- 先 `get_aggregations( )` 取对象，再 `add_aggregation( )`，没有 `CREATE OBJECT` 的野路子。
- `CATCH cx_salv_data_error` + `cx_salv_not_found` 兜住了"列不存在 / 列类型不支持聚合"的场景（这两个异常都继承自 `cx_salv_error`，**不是** `cx_salv_msg`，这里类型选对了）。

**错的部分**：

1. **被聚合的数据集是残缺的**。合计算在 `gt_po` 上，而 `gt_po` 被 `waers = 'EUR'` 悄悄过滤过。用户看到的"总金额"≠他选择屏条件的总金额，而且界面**没有任何 currency 说明**——一个 `NETWR` 合计数字摆在那里，用户无从知道它是 EUR 口径。
2. **多币种混算的经典坑被"硬编码过滤"掩盖了**。正确做法是：要么用 `CL_SALV_TABLE` 之外的方式按币种分组、要么在列上加 `WAERS` 展示并明确限定币种，而不是在 `WHERE` 里偷偷加条件。
3. **金额列按 `numeric` 显示**：

```abap
    lo_col ?= lo_cols->get_column( 'NETWR' ).
    lo_col->set_cell_type( if_salv_c_cell_type=>numeric ).
```

`NETWR` 是 `CURR`（2 位小数、14,2）。`numeric` 会把金额按纯数值格式化，**丢掉小数位和千分位**，合计行同样受影响。应改为 `if_salv_c_cell_type=>currency`（并保证 `WAERS` 列在数据里，通常设为隐藏列供格式化参考）。

4. **异常被静默吞掉**。`CATCH` 里什么都不做，`NETWR` 若因类型问题聚合失败，用户只会看到"没有合计"，却不知道是程序放弃了。可以 `MESSAGE` 或至少 `WRITE` 一行诊断。

---

## 4. 事件绑定（`display_alv`）—— ❌

```abap
    CREATE OBJECT go_handler.
    go_handler->mv_show = lo_alv.          " ← 编译错误
    lo_events = lo_alv->get_event( ).
    SET HANDLER go_handler->on_double_click FOR lo_events.
    SET HANDLER go_handler->on_link_click   FOR lo_events.
```

### 4.1 `go_handler->mv_show = lo_alv` 编译不过

```abap
CLASS lcl_event_handler DEFINITION FINAL.
  PUBLIC SECTION.
    METHODS on_double_click FOR EVENT double_click OF cl_salv_events_table
      IMPORTING row column.
    METHODS on_link_click   FOR EVENT link_click   OF cl_salv_events_table
      IMPORTING row column.
  PRIVATE SECTION.
    DATA mv_show TYPE REF TO cl_salv_table.   " ← private
ENDCLASS.
```

从 `lcl_handler`（外部类）赋值 `go_handler->mv_show`，而 `mv_show` 在 **PRIVATE SECTION**。全局类的属性可见性由编译器强约束，外部访问 private 属性是**编译期错误**。

而且退一步讲：**这个属性即使能访问也毫无用处**——`on_double_click` / `on_link_click` 里一次都没用到 `mv_show`。它看起来是想"持有一份主 ALV 引用"，但真正的需求（拿到显示行 → 行数据）用错了工具。

如果确实要持有引用，正确写法是：

```abap
CLASS lcl_event_handler DEFINITION FINAL.
  PUBLIC SECTION.
    METHODS on_double_click FOR EVENT double_click OF cl_salv_events_table
      IMPORTING row column.
  PRIVATE SECTION.
    DATA mo_source_alv TYPE REF TO cl_salv_table.
  PUBLIC SECTION.                                  " ← 或者干脆不暴露，改为 CONSTRUCTOR 注入
    METHODS constructor IMPORTING iv_alv TYPE REF TO cl_salv_table.
ENDCLASS.
```

### 4.2 `on_link_click` 是一个永远不会触发的死处理器

`link_click` 事件**只有当单元格的 cell type 是 `link` 时才会触发**。而代码里只设置了：

```abap
    lo_col ?= lo_cols->get_column( 'EBELN' ).
    lo_col->set_long_text( 'Purchase Order' ).        " 只是长文本，不是链接
    lo_col ?= lo_cols->get_column( 'NETWR' ).
    lo_col->set_cell_type( if_salv_c_cell_type=>numeric ).
```

没有任何 `set_cell_type( if_salv_c_cell_type=>link )`。所以 `on_link_click` 是个纯粹的死分支。这里暴露出**交互设计没想清楚**：注释说"双击下钻"，代码又挂了 link_click，两者意图冲突。要么删掉 link_click，要么改成"点订单号链接下钻"（并设置 hyperlink），只留一种入口。

### 4.3 其他

- `lo_cols->get_column( 'EBELN' )` **不在 TRY 里**。列名拼错或结构改了会抛 `CX_SALV_NOT_FOUND` → dump。`?=` 只能防"引用为空"，**不能吞异常**，必须配 `IF lo_col IS BOUND` 或 TRY。
- `lo_alv` 是 `display_alv` 的局部变量，`display( )` 返回后就出栈。`SET HANDLER` 挂在 ALV 自有的事件对象上（生命周期与 ALV 一致），所以**不会**提前释放；但如果要跨事件回调拿到主 ALV，靠的就是那个写不出来的 `mv_show`。当前状态下事件回调只能摸全局内表，属于强耦合。
- `CREATE OBJECT go_handler` 放在 `display_alv` 里，若该方法被重复调用（用户返回后再执行）会泄漏一个 handler。建议提到 `INITIALIZATION` 或用 `CREATE OBJECT ... AREA HANDLE` 之外的显式管理。

---

## 5. 下钻弹窗（`on_double_click` / `show_items`）—— ❌

```abap
  METHOD on_double_click.
    DATA lo_popup TYPE REF TO cl_salv_table.

    READ TABLE gt_po INTO DATA(ls_po) INDEX row.
    IF sy-subrc <> 0.
      RETURN.
    ENDIF.

    go_report->show_items( iv_ebeln = ls_po-ebeln ).

    TRY.
        cl_salv_table=>factory(
          EXPORTING list_display = if_salv_c_bool_sap=>false
          IMPORTING r_salv_table  = lo_popup
          CHANGING  t_table       = gt_item ).
      CATCH cx_salv_msg.
    ENDTRY.

    lo_popup->display( ).
  ENDMETHOD.
```

### 5.1 致命：`INDEX row` 反查底表，排序后必然错行

`double_click` 事件传入的 `row` 是**当前屏幕上第几行**，而 SALV 的排序是在 ALV 内部完成的，**不会重排传入的 `gt_po`**。用户点一下 `NETWR` 表头排序，屏幕上第 3 行和 `gt_po` 第 3 行就是两笔完全不同的订单——下钻会打开**错误的采购订单**，而且没有任何报错。

更糟的是这段代码明确打开了布局保存：

```abap
    lo_layout->set_key( VALUE #( report = sy-repid ) ).
    lo_layout->set_default( abap_true ).
    lo_layout->set_save_restriction( if_salv_c_layout=>restrict_none ).
```

`restrict_none` 意味着用户可以存下带**排序 + 列过滤 + 隐藏列**的变式。变量一存，`INDEX row` 的错行就从"偶尔"变成"每次"。

**修法（三选一）**：

```abap
" a) 最省事：传入前自己排序，并禁止用户再排序 —— 显示顺序 == 物理顺序
    SORT gt_po BY ebeln.
    lo_layout->set_sort_restriction( if_salv_c_layout=>restrict_none ).
    lo_layout->set_save_restriction( if_salv_c_layout=>restrict_no_sorting ).

" b) 用 cell button / link，把主键文本带在单元格里，再用 key 反查（与行号无关）
    lo_col->set_cell_type( if_salv_c_cell_type=>link ).
    " on_link_click( row column ) → READ TABLE gt_po WITH KEY ebeln = <column 内文本>

" c) 事件里读 ALV 自己的数据快照（CL_SALV_TABLE 内部已按显示顺序重排）后再定位
```

### 5.2 致命：异常吞掉后仍解引用引用

```abap
      CATCH cx_salv_msg.
    ENDTRY.

    lo_popup->display( ).
```

`CATCH` 之后**没有 `IF lo_popup IS INITIAL. RETURN. ENDIF.`**。只要 `factory` 抛 `CX_SALV_MSG`，`lo_popup` 就是未绑定引用，`lo_popup->display( )` 立刻 **CX_SY_REF_IS_INITIAL short dump**——异常处理把一个可读的错误消息变成了 dump。

同一个 bug 在 `display_alv` 里也存在：

```abap
    TRY.
        cl_salv_table=>factory( ... r_salv_table = lo_alv ... ).
      CATCH cx_salv_msg.
        RETURN.
      ENDTRY.
    lo_aggr = lo_alv->get_aggregations( ).   " ← 同样可能对未绑定引用解引用
```

（这里恰好有 `RETURN` 兜住了，是对的；但两处错误处理风格不一致，说明是复制粘贴时漏改。）

### 5.3 `list_display = false` 得到的不是"弹窗"

`IF_SALV_C_BOOL_SAP=>false` 表示 **全屏 ALV**（独立 P1000 屏幕，靠 `BACK` 返回），不是浮动弹窗。真要浮动窗口，需要 `list_display = true` 配合：

```abap
    lo_popup_disp = lo_popup->get_display_settings( ).
    lo_popup_disp->set_start_column( 20 ).
    lo_popup_disp->set_start_row( 5 ).
```

而且弹窗 ALV 缺了几样"下钻弹窗"应有的配置：没有 `set_key`（无法保存列宽，用户每次都要拖）、没有 zebra、没有列宽优化、没有标题/总数。`display( )` 之前也没设 titlebar。

### 5.4 `show_items` 与全局缓冲区

```abap
  METHOD show_items.
    SELECT ebeln posnr matnr menge netwr
      FROM ekpo INTO TABLE gt_item
      WHERE ebeln = iv_ebeln.
  ENDMETHOD.
```

- **没有 `sy-subrc` / 空结果处理**：订单无项目（或全部被标记删除）时，弹窗是一张**空白网格**，用户以为程序坏了。至少给一句 `MESSAGE`。
- **`EKPO` 缺过滤**：没有 `AND lo_gsk <> 'X'`（逻辑删除）、没有 `menge <> 0`、没有 `erdat`，项目列表会带上已删除行和 0 数量行。
- **`gt_item` 是全局且被复用**：每次下钻都整体覆盖。当前没有嵌套弹窗所以还没出事，但一旦加"项目行再下钻到交货/发票"，这个共享缓冲区立刻变成 bug 温床。建议改成局部内表，通过 `show_items` 的 `EXPORTING et_item` 或独立 ALV 类返回。
- **`gt_item` 建了 `WITH EMPTY KEY` 却用 `INTO TABLE gt_item` 直接灌数据**：CL_SALV_TABLE 需要无键表，这步是对的，值得肯定；但 `mt_data` 没有走这条路（它是行类型），说明作者对"行类型 vs 表类型"还没完全分清。

---

## 6. 其余编译/规范问题

1. **选择屏引用了尚未声明的对象**：

```abap
DATA gt_po   TYPE STANDARD TABLE OF ty_po WITH EMPTY KEY.
...
SELECT-OPTIONS s_ebeln FOR gs_key-ebeln.   " ← 第 57 行
DATA gs_key TYPE ty_po.                     " ← 第 58 行，晚了一行
```

`SELECT-OPTIONS ... FOR <f>` 要求 `<f>` **在之前已声明**，否则编译错误。两行顺序必须对调。

2. 命名/语义错位：`mt_data`（行类型却用 `mt_` 前缀）、`menge`（源字段 `KUMQW`，与 `EKPO-MENGE` 同名不同义）。
3. 无 `TABLES: ekko.` / `ekpo.`（7.40+ 不需要，OK），但也**没有 DDIC 结构**——直接用 EKKO/EKPO 字段拼内表，字段一旦变更就 dump。
4. 没有 `sy-uname` 之类的权限检查，没有 `NO-DISPLAY` 的参数化入口。

---

## 7. 修复优先级

| 级别 | 问题 | 位置 |
|---|---|---|
| **P0 编译** | `SELECT-OPTIONS ... FOR gs_key-ebeln` 顺序颠倒 | :57-58 |
| **P0 编译** | 外部访问 `mv_show`（private） | :137 |
| **P0 运行** | `kumvw` 应为 `kumqw` | :74 |
| **P0 逻辑** | `INDEX row` 在排序/变式下取错行 → 下钻到错误订单 | :165, :187 |
| **P0 运行** | `CATCH` 后 `lo_popup->display( )` 对未绑定引用解引用 | :177-180 |
| **P1 逻辑** | `MODIFY mt_data FROM ls_row` 无键匹配，静默失效 | :81 |
| **P1 逻辑** | `gt_po` 隐式加 `waers = 'EUR'`，选择屏与结果不一致且无提示 | :88 |
| **P1 逻辑** | `on_link_click` 永不触发（无 link 型单元格） | :140 |
| **P1 逻辑** | 重复 SELECT；`mt_data` 死代码；ALV 缺 `LIFNR` | :74-88 |
| **P2 规范** | `NETWR` 用 `numeric` 应为 `currency`；合计无币种说明 | :134 |
| **P2 规范** | `WRITE: / 'loaded'` 调试残留；`INITIALIZATION` 硬编码 `0000000001` | :90, :61 |
| **P2 规范** | `get_column` 未包 TRY / 未 `IS BOUND` 检查 | :131, :133 |
| **P2 规范** | `show_items` 无空结果提示、无 EKPO 删除行过滤 | :149-152 |
| **P3 增强** | 弹窗全屏而非浮动；无 titlebar / 列宽 / key；`gt_item` 全局复用 | :172-180 |

---

## 8. 一句话总结

作者掌握了这套程序的**主干套路**（`WITH EMPTY KEY` 内表、`CL_SALV_TABLE` 工厂、`get_event( )` + `SET HANDLER`、`add_aggregation` 且异常类型选得准确），这几点都写对了；但在**细节一致性**上全面失守：两次结构不一致的取数、一个拼错的字段名、一个永远匹配不上的 `MODIFY`、一个编译不过的 private 赋值、一个永不触发的处理器，以及最致命的——**用显示行号去索引未被 ALV 重排的底表**。后者不会报错，只会安静地把用户带到错误的采购订单上，是这类 ALV 程序最典型的隐性事故。修完 P0/P1，这个报表才具备上线条件。
