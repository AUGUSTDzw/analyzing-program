# ABAP 程序分析报告：ZTEST7（可编辑 ALV + 合计行实时刷新）

- 源文件：`evals/ztest7.abap`
- 程序类型：可执行报表（Report），非 OO，全过程式（FORM 回调风格）
- 行数：115 行
- 依赖：`slis`（旧式 ALV Function Module 封装）+ `CL_GUI_ALV_GRID`（OO ALV 对象）

---

## 1. 它解决什么问题

这是一个**最小化技术验证程序（POC）**，验证 SAP 全屏 ALV 的三件事能否配合工作：

1. **单元格可编辑**——通过 `REUSE_ALV_FIELDCATALOG_MERGE` 生成 Field Catalog 后，只把 `BRGEW`（毛重）一列改为可编辑（`edit = 'X'`）；
2. **编辑事件被捕获**——`DATA_CHANGED` 事件回调 `GET_DATA_CHANGED`，把用户在 ALV 里改的值回写到内表；
3. **合计行随编辑实时重算**——`BRGEW` 列设为 `do_sum = 'X'`（总计行），用户每次修改数值，底部合计行立刻刷新，且**不丢失排序/筛选/滚动位置**。

业务上它模拟一个"物料毛重主数据维护"场景：`MARA`（物料主数据）里的 `BRGEW`（毛重量）字段，现实中在 SAP 标准里是**不可直接编辑**的，所以程序用 `SELECT ... FROM mara` 直接取出，在 ALV 上放开编辑权限，让用户可以批量修正毛重——典型的"标准事务不可改，Z 程序放开"的需求。

程序末尾 `READ TABLE gt_mara UP TO 10 ROWS` 的 10 行限制说明它只是为了跑通链路，**没有任何生产数据语义**。

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────┐
│  START-OF-SELECTION  （主流程，纯顺序代码）                │
│                                                          │
│  ① SELECT * FROM mara UPTO 10 → gt_mara                  │
│  ② REUSE_ALV_FIELDCATALOG_MERGE(ZTEST_S) → gt_fieldcat   │
│  ③ 手工改写 fieldcat：BRGEW 打上 edit/do_sum              │
│  ④ 注册 gt_events：DATA_CHANGED → GET_DATA_CHANGED       │
│  ⑤ REUSE_ALV_GRID_DISPLAY（挂 SET_PF_STATUS 回调）       │
└───────────────────────┬─────────────────────────────────┘
                        │  Function Module 内部驱动 ALV
                        ▼
┌─────────────────────────────────────────────────────────┐
│  ALV 控件（CL_GUI_ALV_GRID 实例，由 FM 隐式创建）          │
│                                                          │
│  ┌──────────────┐  edit 事件注册          ┌────────────┐ │
│  │ SET_PF_STATUS │◄────────────────────────┤ ALV 触发    │ │
│  └──────────────┘                          │ pf_status_ │ │
│                                            │ _set      │ │
│  ┌──────────────┐  DATA_CHANGED           └────────────┘ │
│  │ GET_DATA_     │◄────────────────────────┐            │
│  │  CHANGED      │                         │ 用户改单元格│
│  └──────────────┘                          └────────────┘ │
└─────────────────────────────────────────────────────────┘
                        │
                        ▼
        共享状态（ABAP 全局 DATA，FORM 无需传参）
        go_grid   : REF TO cl_gui_alv_grid
        gt_mara   : 展示 + 回写的同一张内表
        gs_stable : refresh_table_display 的稳定标记
```

### 关键架构特征：三层回调 + 全局状态

| 层次 | 载体 | 职责 |
|------|------|------|
| 主流程 | `START-OF-SELECTION` | 取数、构造 fieldcat、注册事件、拉起 ALV |
| UI 装配回调 | `FORM set_pf_status` | ALV 初始化时拿到 grid 引用、注册 edit 事件 |
| 数据回调 | `FORM get_data_changed` | 编辑落地、重算合计、稳定刷新 |

三者的**通信媒介不是参数，而是 ABAP 全局变量**。`SET_PF_STATUS` 唯一的职责就是把 `e_grid` 存进 `go_grid`——没有它，后面 `get_data_changed` 里所有 `go_grid->...` 调用都无法工作。这是新旧 ALV API 混用时的经典结构。

---

## 3. 执行流程（按时间轴）

```
用户双击运行 ZTEST7
   │
   ├─(A) TYPE-POOLS: SLIS  装载类型池
   │
   ├─(B) SELECT MATNR, BRGEW FROM mara INTO TABLE _mara UP TO 10 ROWS
   │        └─> gt_mara（注意：_mara 是行结构变量，隐式用作 it_outtab 之外的容器）
   │        └─> sy-subrc = 0 才继续（ABAP Open SQL 只要查到 0 行也会置 0，实际不严谨）
   │
   ├─(C) REUSE_ALV_FIELDCATALOG_MERGE
   │        i_program_name = 'ZTEST7'
   │        i_structure_name = 'ZTEST_S'   ← 决定列集合与默认文本
   │        ct_fieldcat = gt_fieldcat
   │        └─> 失败（异常 1/2/3）则整个显示被跳过，无提示
   │
   ├─(D) 后处理 fieldcat：定位 BRGEW → edit='X'、do_sum='X'
   │
   ├─(E) gt_events += DATA_CHANGED → form 'GET_DATA_CHANGED'
   │
   └─(F) REUSE_ALV_GRID_DISPLAY
          ├─ [FM 内部] 创建 CL_GUI_ALV_GRID
          ├─ [FM 内部] 设置 PF-STATUS → 触发 FORM set_pf_status
          │     ├─ GET_GLOBALS_FROM_SLVC_FULLSCR → e_grid = go_grid
          │     ├─ register_edit_event(mc_evt_modified)
          │     ├─ register_edit_event(mc_evt_enter)
          │     └─ CASE sy-ucomm: 仅 WHEN OTHERS（空实现）
          ├─ [FM 内部] 显示数据，控制权交还用户
          │
          │   ┌──── 用户双击 BRGEW 单元格并修改 ────┐
          │   ↓                                  │
          │   [ALV] 触发 DATA_CHANGED 事件        │
          │   ↓                                  │
          │   FORM get_data_changed(io_data_changed)
          │     ├─ go_grid IS BOUND 守卫
          │     ├─ LOOP mt_mod_cells WHERE fieldname='BRGEW'
          │     │     READ TABLE gt_mara INDEX <row_id> → 回写 brgew
          │     ├─ get_subtotals(ep_collect00 = gr_data)
          │     ├─ ASSIGN gr_data->* → <gtr_sum_tab>
          │     ├─ READ INDEX 1 → <l_sum>
          │     ├─ ASSIGN COMPONENT 'BRGEW' → <lg_val>
          │     ├─ <lg_val> = REDUCE #( SUM 所有 gt_mara-brgew )
          │     ├─ gs_stable-col/row = 'X'
          │     └─ refresh_table_display(soft_refresh='X')
          │   ↑                                  │
          │   └──────────────────────────────────┘
          │
          ├─ [FM 内部] 用户按 BACK/EXIT → FM 返回，sy-subrc = 0
          └─ [程序结束] ALV 对象销毁，程序结束（无 LIST_PROCESSING，无保存）
```

注意流程 F 中 **FM 内部回调 `SET_PF_STATUS` 早于 `DATA_CHANGED` 触发**——因为必须先 `register_edit_event`，否则 ALV 不认为该列可编辑触发修改事件。

---

## 4. 按子程序分组讲解

### 4.1 全局数据声明（行 4-11）

```abap
DATA: gt_mara     TYPE TABLE OF ztest_s,
      gt_fieldcat TYPE slis_t_fieldcat_alv,
      gt_events   TYPE slis_t_event,
      go_grid     TYPE REF TO cl_gui_alv_grid,
      gs_stable   TYPE lvc_s_stbl,
      gr_data     TYPE REF TO data.

FIELD-SYMBOLS: <gtr_sum_tab> TYPE table.
```

| 对象 | 类型 | 角色 |
|------|------|------|
| `gt_mara` | `ZTEST_S` 动态表 | **同时**是 ALV 数据源和编辑结果落地表（单一真相源，无 separate edit table） |
| `gt_fieldcat` | Field Catalog | 列定义（文本、可见性、可编辑、汇总） |
| `gt_events` | 事件表 | FM 回调分发表 |
| `go_grid` | grid 引用 | **桥接对象**：`slis` FM 世界 → OO ALV 世界 |
| `gs_stable` | `lvc_s_stbl` | 刷新时保持滚动位置/行高 |
| `gr_data` | `REF TO data` | 承载 subtotal 数据，避免类型硬编码 |
| `<gtr_sum_tab>` | 泛型表 FS | 让 `gr_data` 无需知道具体行结构 |

### 4.2 主流程 `START-OF-SELECTION`（行 13-48）

```abap
  SELECT matnr, brgew
    FROM mara
    INTO TABLE _mara UP TO 10 ROWS.
```

- **直接查标准表 `MARA`**，而非任何 Z 表/DDIC 视图。
- `INTO TABLE _mara` 实际等价于 `INTO TABLE @gt_mara`（`MARA-MATNR/NAME` 结构兼容分配），此处写法绕。
- `UP TO 10 ROWS` **无 ORDER BY**，DB 返回顺序不确定——后面的 `INDEX <row_id>` 回写依赖 ALV 行号，这是可行的（ALV 行号来自内表顺序），但显示顺序不可控。

```abap
      READ TABLE gt_fieldcat ASSIGNING FIELD-SYMBOL(<gs_fcat>) WITH KEY fieldname = 'BRGEW'.
      IF sy-subrc EQ 0.
        <gs_fcat>-edit = 'X'.
        <gs_fcat>-do_sum = 'X'.
      ENDIF.
```

Field Catalog 由 FM 根据 `ZTEST_S` DDIC 自动生成，随后**只挑 `BRGEW` 一列**打两个标记：
- `edit = 'X'` → ALV 允许单元格进入编辑态；
- `do_sum = 'X'` → 生成 **Overall Total 汇总行**（对应 `ep_collect00`）。

这解释了为什么后面 `get_subtotals` 只取 `ep_collect00` 一个累加器——只有一列需要总计。

```abap
      APPEND VALUE #( name = 'DATA_CHANGED' form = 'GET_DATA_CHANGED' ) TO gt_events.
```

用 `VALUE #(...)` 行构造器构造事件行（现代写法）。`form` 存的是 **FORM 名（大写）**，`name` 是 ALV 事件 ID 常量名。两者拼在一起形成 `slis_eventname` 级别的分发。

```abap
      CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
        EXPORTING
          i_callback_program       = sy-repid
          it_fieldcat              = gt_fieldcat
          it_events                = gt_events
          i_callback_pf_status_set = 'SET_PF_STATUS'
        TABLES
          t_outtab                 = gt_mara.
```

关键点：
- `i_callback_program = sy-repid` —— 告诉 ALV 用**当前程序**去 `PERFORM` 回调 FORM；
- `i_callback_pf_status_set` —— 这里名字容易误解：它设置 **当前自定义 PF-STATUS 的名字**（本例为空字符串，即用默认），而 `i_callback_pf_status_set` 的回调 FORM 名字是**通过 `gt_events` 里 `PF_STATUS_SET` 事件或 FM 约定**……实际上本程序是用 `i_callback_pf_status_set = 'SET_PF_STATUS'` 传 FORM 名，这在 slis 约定中不成立——正确参数是把它放在 `it_events` 中（`name = 'PF_STATUS_SET', form = 'SET_PF_STATUS'`）或用 `i_callback_pf_status_set`（该参数确实存在，含义是"设置 PF-STATUS 时的回调 FORM 名"）。**这是本程序中最容易误读的一点**：`i_callback_pf_status_set` 是"回调 FORM 名"而非"PF-STATUS 名"，后者由 `i_pf_status` 指定。
- `t_outtab = gt_mara` —— 传内表（非 work area），FM 直接接管显示；**编辑值不会自动回写**，必须靠 `DATA_CHANGED` 手动做。

### 4.3 `FORM set_pf_status`（行 51-72）—— UI 装配

```abap
  CALL FUNCTION 'GET_GLOBALS_FROM_SLVC_FULLSCR'
    IMPORTING
      e_grid = go_grid.
```

这是整段代码的**枢纽**。因为用的是 `REUSE_ALV_GRID_DISPLAY`（FM 封装），外部拿不到 grid 引用；必须借 FM 在 PF-STATUS 阶段回传 `e_grid`。`GET_GLOBALS_FROM_SLVC_FULLSCR` 是 slis 提供的"偷渡"接口，把 grid 对象引用塞进全局变量。

```abap
    CALL METHOD go_grid->register_edit_event
      EXPORTING
        i_event_id = cl_gui_alv_grid=>mc_evt_modified.

    CALL METHOD go_grid->register_edit_event
      EXPORTING
        i_event_id = cl_gui_alv_grid=>mc_evt_enter.
```

注册两种编辑完成时机：
- `MC_EVT_MODIFIED` —— 按下回车/切走单元格，值已校验；
- `MC_EVT_ENTER` —— 双击进入编辑态时触发。

**注册发生在 `set_pf_status`，即 ALV 首次显示时**。顺序不能颠倒：先有 edit 标记（fieldcat）+ 再 register 事件，ALV 才知道要发 `DATA_CHANGED`。

```abap
  " PF Status Code
  CASE sy-ucomm.
*	WHEN
    WHEN OTHERS.
  ENDCASE.
```

空壳：`CASE` 只有 `WHEN OTHERS`，无实际逻辑。**但它有一个隐藏价值**——正是这个 `CASE sy-ucomm` 语句让 SLIS 判定"PF-STATUS 需要被请求"，从而触发了上面 `GET_GLOBALS_FROM_SLVC_FULLSCR` 的执行时序。这是 slis 编程中典型的"用空语句维持时序"技巧，删除会导致 `go_grid` 为空。

### 4.4 `FORM get_data_changed`（行 74-115）—— 核心逻辑

```abap
    LOOP AT io_data_changed->mt_mod_cells ASSIGNING FIELD-SYMBOL(<gs_changed>) WHERE fieldname = 'BRGEW'.
      READ TABLE gt_mara ASSIGNING FIELD-SYMBOL(<gs_tab>) INDEX <gs_changed>-row_id.
      IF sy-subrc EQ 0.
        <gs_tab>-brgew = <gs_changed>-value.
      ENDIF.
    ENDLOOP.
```

**编辑回写三步**：
1. `mt_mod_cells` 是协议表，记录本次事件所有被改的单元格（字段名 + 行号 + 新值）；
2. 过滤 `fieldname = 'BRGEW'`（虽然本例只此列可编辑，但保留过滤是好习惯）；
3. `ASSIGNING FIELD-SYMBOL(<gs_tab>) INDEX <gs_changed>-row_id` —— 用 ALV 行号直接定位内表行，**改动内表对象本身**（因为内表是 `ASSIGNING`，不是拷贝），因此显示层和数据层自动一致。

`mt_mod_cells` 是标准类型 `lvc_s_mod_cell_s`，`value` 是 `lvc_value`（最多 255 字符的字符型），赋值给 `BRGEW`（`NTGEW_15`）时 ABAP 自动转换。

```abap
    go_grid->get_subtotals(
      IMPORTING
        ep_collect00 = gr_data   " Overall Total
    ).

    ASSIGN gr_data->* TO <gtr_sum_tab>.
    READ TABLE <gtr_sum_tab> ASSIGNING FIELD-SYMBOL(<l_sum>) INDEX 1.
```

- `ep_collect00` 是"Overall Total"累加器的返回参数（`RAISING` 型引用，实参传 `REF TO data`）；
- `ASSIGN gr_data->*` 把引用指向的整个结构/表整体赋给泛型表字段符号——因为 subtotal 数据本身是一张表（外层：sort key 组合；这里只有一个 total 组合 → 1 行）；
- `READ INDEX 1` 取那条唯一的 overall total 行。

```abap
      ASSIGN COMPONENT 'BRGEW' OF STRUCTURE <l_sum> TO FIELD-SYMBOL(<lg_val>).
      IF <lg_val> IS ASSIGNED.
        <lg_val> = REDUCE #( INIT lv_i TYPE ntgew_15 FOR <ls_t> IN gt_mara NEXT lv_i = lv_i + <ls_t>-brgew ).
      ENDIF.
```

**本程序最值得讨论的一段**。逻辑是：
1. 动态取 subtotal 结构里 `BRGEW` 这个分量的字段符号；
2. **用 `REDUCE` 自己重算一遍总和**，覆盖 ALV 算出来的值。

为什么需要"自己重算"而不是直接用 ALV 的值？因为编辑之后，ALV 内部 subtotal 缓存可能基于**旧值**——用户改了单元格，ALV 还没重算，先算一次写入，反而会得到过期结果。这里通过直接对 `gt_mara` 全表求和（数据层已是最新的），**绕过 ALV 的 subtotal 缓存**，得到权威合计。这是"编辑后合计不刷新"这一经典 bug 的规避手法。

`IS ASSIGNED` 检查防止组件不存在时的短程赋值崩溃。

```abap
    gs_stable-col = 'X'.
    gs_stable-row = 'X'.
```

`LVC_S_STBL`（Stabilization）：要求刷新后**保持行/列位置**，避免用户编辑第 50 行时合计行刷新后光标跳回顶部。

```abap
    go_grid->refresh_table_display(
      EXPORTING
        is_stable      = gs_stable
        i_soft_refresh = 'X'
      EXCEPTIONS
        finished       = 1
        OTHERS         = 2
    ).
```

- `is_stable` → 稳定刷新；
- `i_soft_refresh = 'X'` → **软刷新**：保留排序、筛选、汇总展开状态，只重绘数据（对比硬刷新会重置全部 UI 状态）。这是合计能"原位跳变"而非"整表重建"的关键。

```abap
    IF sy-subrc <> 0.
    ENDIF.
```

空异常处理——`refresh_table_display` 在 ALV 已销毁（如导出后）时会 dump，这里只是"吞掉"（注释说是 by Export）。**风险：异常被吞，无任何日志**。

---

## 5. 数据流与合计刷新机制（重点）

```
        用户修改 B 行 BRGEW: 10 → 25
                    │
                    ▼
      ALV: DATA_CHANGED(io_data_changed)
      mt_mod_cells = [ {row_id = B, fieldname='BRGEW', value='25'} ]
                    │
      ┌─────────────┴──────────────┐
      ▼                            ▼
 ① 回写数据层                  ② 重算合计
 gt_mara[B]-brgew = 25         get_subtotals → gr_data
 （ASSIGNING 直改内表）        （此刻可能是过期值）
      │                            │
      │                     ASSIGN → <gtr_sum_tab>(1) → BRGEW 分量
      │                            │
      │                     REDUCE SUM(gt_mara) ← 数据层已是最新
      │                            │
      └────────────┬───────────────┘
                   ▼
        refresh_table_display
        is_stable    = 'X'  → 行/列位置不动
        i_soft_refresh= 'X'  → 排序/筛选/合计层级保留
                   ▼
        合计行显示新值，光标仍在 B 行
```

---

## 6. 问题清单与改进建议

### 6.1 严重（会导致生产问题）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| **S1** | 行 81 | `<gs_tab>-brgew = <gs_changed>-value` **无有效性校验**。`LVC_VALUE` 是字符型；用户输入 `1e999`、`abc`、`1,5`（逗号）会 **dump（CONVT_NO_NUMBER / 字段长度溢出）** | 加 `CALL FUNCTION 'CONV_NO_NUMBER_TO_INT'`，捕获异常后 `MESSAGE` 给用户并 `gr_grid->set_cell_foreground` 标红 |
| **S2** | 行 15-18 | 直接 **`SELECT FROM mara`（全表 21 万行）**，无 WHERE、无 `UP TO` 之外的保护。生产上会拖垮/锁表 | 加 `WHERE matnr IN ...` 或按用户输入范围过滤；或改用 CDS View / 已有索引 |
| **S3** | 行 15-18 + 79 | **编辑值没有任何 `UPDATE`**，数据只在内存。用户按 BACK 后全部修改丢失，而用户可能以为已保存 | 至少加显式 SAVE 按钮 + `MODIFY mara ...` 或调用 BAPI `BAPI_MATERIAL_SAVES_INTENDED`，并做权限检查（`AUTHORITY-CHECK` / `SAPLACKLIST`） |
| **S4** | 全程序 | **无 `WHEREUSEDLIST` / 权限校验**：任何能运行 `ZTEST7` 的人都能改 `MARA-BRGEW`。这是标准主数据字段 | 前置 `AUTHORITY-CHECK` 对象，如 `F_BA_MATERIA` 的 `MATERIASA_C` |

### 6.2 正确性 / 可维护性

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| **M1** | 行 95 | `REDUCE` 里 `lv_i` 声明在**行内联**但未在 `INIT` 前 `DATA` 声明——ABAP 7.40 inline 语法在 `REDUCE #( INIT lv_i ...)` 中是合法的，但 `lv_i TYPE ntgew_15` **只覆盖前 3 位小数**，`MARA-BRGEW` 是 `NTGEW_15`（15 位含 3 小数），累加 N 行可能溢出到 `QUAN`/`MATH` | 声明为 `lv_i TYPE ntgew_15`，并在提交前检查溢出，或直接用 ALV 的 subtotal 值 + `SY-SUBRC` 校验 |
| **M2** | 行 85-88 | `get_subtotals` **没有任何 EXCEPTIONS 捕获**（`ALV_NO_DATA`, `SUBTOTAL_NOT_ACTIVATED`） | 加 `EXCEPTIONS` 处理，至少 `SUBTOTAL_NOT_ACTIVATED` 时提示 |
| **M3** | 行 19, 32, 92 | `sy-subrc EQ 0` 检查 `READ TABLE` 后紧跟的字段符号使用是安全的，但**行 19 `IF sy-subrc EQ 0` 包住整个显示逻辑**，若查询返回 0 行 `sy-subrc` 仍为 0（Open SQL 语义），会显示空 ALV | 加 `IF lines( gt_mara ) > 0` 或用 `SELECT ... ENDSELECT` 判断 |
| **M4** | 行 20-29 | Field Catalog FM 的 `OTHERS = 3` 被忽略，`sy-subrc` 之后没检查（行 30 有一层，但外层 IF 结构混乱） | 统一错误处理，`MESSAGE e ...` 或日志 |
| **M5** | 行 85-96 | "ALV 算一遍 + 自己算一遍"**双重计算**，读者困惑到底是哪个生效 | 加注释说明这是为规避 ALV subtotal 缓存过期；或测试确认后直接用 ALV 值（若不需 REDUCE 则删除） |
| **M6** | 行 78 | 若将来开放更多列可编辑，硬编码 `WHERE fieldname = 'BRGEW'` 和单列回写需改写 | 改为 `LOOP ... ` 通用回写 + `ASSIGN COMPONENT <fieldname> OF STRUCTURE` 动态赋值 |

### 6.3 性能

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| **P1** | 行 78-83 + 85-96 | 每次编辑事件都：① 全表 REDUCE 求和 ② `get_subtotals` 全量算 ③ `refresh_table_display` 重绘。**O(N) per keystroke**，万行内表会明显卡顿 | 数据量大时改用增量维护汇总值（在回写时同步 `lv_running_total`），或对 subtotal 用 ALV 自身能力（`do_sum` + `refresh` 已足够时不手动 REDUCE） |
| **P2** | 行 78 | `mt_mod_cells` 循环内对每个单元格做一次 `READ TABLE ... INDEX` | 内表行数大时，ALV 事件通常一次含多个单元格；可用 `LOOP` 累积而无需多次 READ（当前实现每次 INDEX 是 O(1) 到 O(log n)，可接受） |

### 6.4 结构 / 现代化

| # | 问题 | 建议 |
|---|------|------|
| **A1** | **新旧 API 混用**：`slis` FM + `GET_GLOBALS_FROM_SLVC_FULLSCR` 属旧式封装，`CL_GUI_ALV_GRID` 属 OO API。混用必须靠 `go_grid` 全局桥接 | 迁移到纯 OO：直接 `CREATE OBJECT go_grid`，用 `set_pf_status` / `set_table_layout` / `on_data_changed` 事件类，不再需要 `REUSE_ALV_GRID_DISPLAY` 与 `GET_GLOBALS_FROM_SLVC_FULLSCR` |
| **A2** | 无类、无单元测试、无 settings | 可抽 `ZCL_ALV_EDIT_DEMO`（Local Class）+ 构造器注入配置（表名、列、可编辑列表），便于扩展与测试 |
| **A3** | `set_pf_status` 中空 `CASE sy-ucomm` 是"时序 hack" | OO 化后自然消失；若保留，加注释说明为何不可删 |
| **A4** | 无消息、无 `MESSAGE` 反馈 | 用户修改后应有 `MESSAGE s` 或状态栏提示；错误应明确告知哪行哪列非法 |
| **A5** | `gs_stable` / `gr_data` 声明为全局 `DATA` 而非局部 | `gs_stable` 完全可改为 `set_pf_status` 内的局部变量；仅 `go_grid` 必须全局 |

---

## 7. 亮点（值得保留的设计）

1. **`edit` + `do_sum` 精准到列**：不是把 Field Catalog 全表放开可编辑，而是 `READ TABLE ... ASSIGNING` 定位单列打标，最小权限。
2. **`mt_mod_cells` 协议驱动回写**：不用整表刷新、不用 `get_selected_rows`，只处理真正变更的单元格。
3. **`ASSIGNING ... INDEX` 直改内表**：`ASSIGNING` 使修改直接作用于内表，不产生额外拷贝。
4. **`i_soft_refresh` + `is_stable` 组合**：兼顾"合计实时跳变"与"排序/筛选/光标位置不丢"，是 ALV 编辑场景的标准解法。
5. **`gr_data REF TO data` + 泛型字段符号**：subtotal 数据结构不硬编码，与具体 DDIC 解耦。
6. **`REDUCE #(...)`**：现代 ABAP 表达式的恰当使用，比 `LOOP ... lv_sum = lv_sum + ...` 更简洁。

---

## 8. 一句话总结

ZTEST7 是一个**技术验证型 POC**：它用 `REUSE_ALV_GRID_DISPLAY` 拉起 ALV，通过 `REUSE_ALV_FIELDCATALOG_MERGE` 生成的 Field Catalog 把 `MARA-BRGEW` 单列设为可编辑+可汇总，借 `GET_GLOBALS_FROM_SLVC_FULLSCR` 把 grid 引用桥接进全局，在 `DATA_CHANGED` 回调里用 `mt_mod_cells` 把编辑值回写内表、用 `REDUCE` 自行重算合计、并以 `is_stable` + `soft_refresh` 平滑刷新，实现"编辑即刷新合计、界面不跳"。它把**编辑闭环**打通得很干净，但**缺输入校验、缺落库、缺权限、缺性能保护**，是演示级代码而非生产代码。
