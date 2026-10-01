# ZTEST7 程序分析报告 —— ALV 可编辑单元格 + 合计行实时重算（POC）

> 分析对象：`ztest7.abap`（115 行，Classic ALV 报表，TYPE-POOLS SLIS）
> 分析视角：业务意图 → 架构分层 → 执行时序 → 逐模块走读 → 缺陷与改进

---

## 0. 一句话结论

这是一个**演示型 POC**：它想展示「Classic ALV 中如何让某一列可编辑，并在用户每次修改单元格后，重新计算并刷新底部合计行」这一件事。但**当前代码存在一个致命缺陷——真正传给 ALV 的内表 `gt_mara` 从未被填充**（数据被 SELECT 进了另一个内表 `_mara`），因此屏幕上会显示一个空网格，后续所有编辑/合计逻辑在当前状态下永远不会被触发。

---

## 1. 它解决什么问题

### 1.1 业务背景（从代码反推）

程序从物料主数据表 `MARA` 取 10 行，展示 `MATNR`（物料号）和 `BRGEW`（毛重），并把 `BRGEW` 列开放为可编辑。业务意图是：

> 让用户在报表/事务界面里直接修改物料的毛重，修改后合计（总毛重）立即同步更新，无需另开一个「求和」逻辑或手工汇总。

### 1.2 典型的使用场景

这类需求在 SAP 里通常来自 MM/仓库顾问：

- **多行手工调整**：一个批次/清单里几十行毛重需要按实称值修正，界面上改完要立刻看到总重变化。
- **轻量录入替代**：本意是想做一个"能编辑的清单报表"，代替 `MM01/MM02` 的逐个维护。
- **演示/教学**：目录名 `alv-editable-total-poc` 明确指向 POC——重点是**技术可行性验证**，而不是一个可投产的维护程序。

### 1.3 它**没有**解决的问题（同样重要）

| 缺失项 | 意味着 |
|---|---|
| 没有 `UPDATE` / BAPI 回写 | 改动只停留在内存内表，退出即丢失。**这是一个纯前端演示** |
| 没有权限检查（`AT_CHECK`） | 任何能执行该报表的用户都可以"改"毛重（虽然没落库，但一旦被后人补上 UPDATE 就是漏洞） |
| 没有业务校验 | 负数、0、超限、非数值、非重量单位都放行 |
| 没有物料/工厂/客户端过滤 | 全库任意 10 条 MARA，非确定结果 |
| 没有工具栏/保存/导出/布局变式 | POC 级交互 |

> ⚠️ **SAP 领域提醒**：`MARA-BRGEW` 属于物料基本数量数据，正常由 WM/数量层（`MARM`、货物移动）间接维护，SAP 不允许通过 `UPDATE mara` 直接改毛重（会破坏数量一致性与已过账凭证的一致性）。真要落库必须走 `BAPI_MATERIAL_SAVEGENERAL` 之类的官方接口。本程序规避了这个问题，但也正因如此，它**不可能**成为一个真正的数据维护程序。

---

## 2. 整体架构

### 2.1 技术选型

| 维度 | 选择 | 评价 |
|---|---|---|
| 界面框架 | `REUSE_ALV_GRID_DISPLAY`（**Classic ALV / 非 OO**） | 遗留技术，但可编辑 + 合计在它上面确实能做 |
| 类型池 | `TYPE-POOLS: slis.` | 正确，使用 `REUSE_ALV_*` FM 的硬性前提 |
| 字段目录 | `REUSE_ALV_FIELDCATALOG_MERGE` + DDIC 结构 `ZTEST_S` | 标准做法，零代码维护 |
| 事件模型 | `it_events` + `FORM` 回调（DATA_CHANGED） | Classic ALV 的"ALV 模块反向调用报表"模型 |
| Grid 引用获取 | `GET_GLOBALS_FROM_SLVC_FULLSCR` | ⚠️ 已知 hack，全局状态反查 |
| 数据模型 | `TYPE TABLE OF ztest_s`（结构而非表类型） | 弱类型，字段名/顺序靠约定 |
| 错误处理 | FM 异常列表 + 少量 `sy-subrc` | 不完整（见第 5 节） |

### 2.2 架构分层

```text
┌──────────────────────────────────────────────────────────────┐
│ L4 事件/回调层（Classic ALV 反向驱动的 FORM）                  │
│   FORM set_pf_status  ── 抓 grid 引用 + 注册编辑事件 + 命令分派 │
│   FORM get_data_changed ── 写值 → 取总计 → 覆写总计 → 刷新     │
├──────────────────────────────────────────────────────────────┤
│ L3 展示定义层                                                  │
│   REUSE_ALV_FIELDCATALOG_MERGE → gt_fieldcat                 │
│   手工打标记：edit = 'X'（可编辑）、do_sum = 'X'（参与合计）   │
│   REUSE_ALV_GRID_DISPLAY     → gt_events（事件注册）           │
├──────────────────────────────────────────────────────────────┤
│ L2 网格控制层（go_grid: cl_gui_alv_grid 引用）                 │
│   register_edit_event / get_subtotals / refresh_table_display │
├──────────────────────────────────────────────────────────────┤
│ L1 数据层                                                      │
│   MARA ──SELECT──▶ _mara（!!未被使用）                         │
│   gt_mara : ALV 数据表（!!未填充）                             │
│   REDUCE #( ) : 合计的计算逻辑内联在回调里                      │
└──────────────────────────────────────────────────────────────┘
        全局状态：gt_mara / gt_fieldcat / gt_events
                  go_grid / gs_stable / gr_data / <gtr_sum_tab>
```

### 2.3 全局状态清单（模块级单例）

| 变量 | 类型 | 作用 | 风险 |
|---|---|---|---|
| `gt_mara` | `TABLE OF ztest_s` | ALV 输出内表 | **未填充（P0）** |
| `gt_fieldcat` | `slis_t_fieldcat_alv` | 字段目录 | 全局副作用，FORM 内直接改 |
| `gt_events` | `slis_t_event` | 事件表 | 全局累积，重进程序会重复 APPEND |
| `go_grid` | `REF TO cl_gui_alv_grid` | 网格对象引用 | 靠 `GET_GLOBALS_FROM_SLVC_FULLSCR` 反查，是全局状态耦合源 |
| `gs_stable` | `lvc_s_stbl` | 刷新时保持行列稳定 | 全局复用，其它刷新场景会继承 |
| `gr_data` | `REF TO data` | 承接 `get_subtotals` 的总计行 | 生命周期不清，空引用风险 |
| `<gtr_sum_tab>` | `TYPE table`（通用） | 把总计行拆成内表 | 通用类型 → 后续全动态无编译期检查 |

**架构层面的关键判断**：这是一个**过程式 + 全局状态**的 Classic ALV 程序，没有分层封装、没有可测试的单元（"算合计"这件事被埋在 24 行的 `FORM` 里）。"计算合计"本应是一个纯函数 `sum( itab ) -> value`，现在却依赖 `go_grid`、事件上下文、`ASSIGN COMPONENT` 三重副作用。这是本 POC 最大的**架构债**。

---

## 3. 执行流程（时序）

```text
用户执行 ZTEST7（无选择屏，秒进）
  │
  ├─(1) START-OF-SELECTION
  │     SELECT matnr, brgew FROM mara INTO TABLE _mara UP TO 10 ROWS   → 结果进了 _mara
  │     IF sy-subrc = 0
  │
  ├─(2)   REUSE_ALV_FIELDCATALOG_MERGE(ZTEST_S) → gt_fieldcat
  │     IF sy-subrc = 0
  │
  ├─(3)   READ gt_fieldcat WHERE fieldname = 'BRGEW'
  │        └─ <gs_fcat>-edit = 'X'   → 该列可编辑
  │           <gs_fcat>-do_sum = 'X' → 该列进合计
  │
  ├─(4)   APPEND VALUE #( DATA_CHANGED → get_data_changed ) TO gt_events
  │
  └─(5)   REUSE_ALV_GRID_DISPLAY( t_outtab = gt_mara )  ←── 此 FM 阻塞，内部死循环
            │  创建 fullscreen grid，PF-STATUS 回调链
            ├─────────────▶ (6) FORM set_pf_status( it_extab )
            │                 GET_GLOBALS_FROM_SLVC_FULLSCR → go_grid
            │                 register_edit_event( mc_evt_modified )
            │                 register_edit_event( mc_evt_enter   )
            │                 CASE sy-ucomm. WHEN OTHERS. ENDIF   ← 空壳
            │
            │   ◀────── 用户在 BRGEW 单元格回车/离开单元格
            │
            └─────────────▶ (7) FORM get_data_changed( io_data_changed )
                              LOOP mt_mod_cells WHERE fieldname = 'BRGEW'
                                READ gt_mara INDEX row_id → 写入新值 ★正确顺序
                              go_grid->get_subtotals( ep_collect00 = gr_data )
                                ASSIGN gr_data->* → <gtr_sum_tab> → INDEX 1
                                ASSIGN COMPONENT 'BRGEW' → 用 REDUCE 重算并覆写
                              refresh_table_display( is_stable + soft_refresh )
                              → 回到 (6)/(5) 的消息循环，等待下一个事件
```

**流程上的两个要点**：

1. **顺序是对的**（值得肯定）：先把新值写进 `gt_mara`，**再**调 `get_subtotals`，所以取到的是含新值的总计，而不是旧值。
2. **阻塞模型是理解本程序的关键**：第 (5) 步的 FM 直到用户按返回才返回。`START-OF-SELECTION` 里 (1)→(5) 是一次性初始化，(6)(7) 是 ALV 在消息循环里反复反向调用报表的 FORM。**所有"业务逻辑"都寄生在这个回调里**——这正是 Classic ALV 可维护性差的根源。

---

## 4. 分模块走读

### 4.1 全局声明 `ztest7.abap:4-11`

```abap
DATA: gt_mara     TYPE TABLE OF ztest_s,
      gt_fieldcat TYPE slis_t_fieldcat_alv,
      gt_events   TYPE slis_t_event,
      go_grid     TYPE REF TO cl_gui_alv_grid,
      gs_stable   TYPE lvc_s_stbl,
      gr_data     TYPE REF TO data.

FIELD-SYMBOLS: <gtr_sum_tab> TYPE table.
```

- 报表 `ztest7` 是 **Include-free 的单文件报表**，全局 DATA 实际在 `START-OF-SELECTION` 之前就可见（`DATA` 语句隐式在事件块之前生成 LOAD OF PROGRAM）。
- `TABLE OF ztest_s`：**结构**而非**表类型**。`REUSE_ALV_FIELDCATALOG_MERGE` 需要 `i_structure_name`，用结构是对的；但 `TABLE OF` 一个结构意味着内表没有行类型语义，ABAP 侧退化成位置映射。
- `SLIS_T_FIELDCAT_ALV` / `SLIS_T_EVENT` 属于 **SLIS** 时代类型；而 `LVC_S_STBL` / `CL_GUI_ALV_GRID` / `CL_ALV_CHANGED_DATA_PROTOCOL` 属于 **LVC**（OO ALV）体系。**同一个程序里混用两代 ALV 类型**，是 Classic ALV 的历史包袱。

### 4.2 数据装载 `ztest7.abap:15-18`

```abap
SELECT matnr, brgew
  FROM mara
  INTO TABLE _mara UP TO 10 ROWS.
```

- `MARA` 是跨客户端、跨工厂的**大表**（物料主数据基本视图），`UP TO 10 ROWS` 且**无 `WHERE`、无 `ORDER BY`**：结果由 DB 优化器/缓冲区状态决定，**每次执行可能不同**。
- 缺 `ORDER BY` + `UP TO n` 在生产里被视为反模式（POC 可接受）。
- 🔴 **致命点**：`_mara` 是一个由 SELECT 语句**隐式声明的新局部内表**，和 `gt_mara` 毫无关系。第 (5) 步 `t_outtab = gt_mara` 传的是空表 → **屏幕上 0 行**。

### 4.3 字段目录与"可编辑 + 可求和"标记 `ztest7.abap:20-35`

```abap
CALL FUNCTION 'REUSE_ALV_FIELDCATALOG_MERGE'
  EXPORTING
    i_program_name   = sy-repid
    i_structure_name = 'ZTEST_S'
  CHANGING
    ct_fieldcat      = gt_fieldcat
  EXCEPTIONS ...
```

- 只给 DDIC 结构名，**不扫描程序写 `REFRESH TABLE`**，是推荐用法。
- `i_program_name` 与 `i_structure_name` 同时传是合法的（程序名仅在处理 `REF` 字段时参与检查表推导），但纯结构场景下冗余。
- `'ZTEST_S'` 是字面量，**ABAP 语法无法校验**；DDIC 对象改名/删除 → 运行时 short dump。
- 关键两步标记（`:31-35`）：

```abap
READ TABLE gt_fieldcat ASSIGNING FIELD-SYMBOL(<gs_fcat>) WITH KEY fieldname = 'BRGEW'.
IF sy-subrc EQ 0.
  <gs_fcat>-edit   = 'X'.   " 单元格可编辑（也可由用户按 F9 切换）
  <gs_fcat>-do_sum = 'X'.   " 该列参与底部合计行
ENDIF.
```

  - `ASSIGNING FIELD-SYMBOL` 直接改内表行，是 Classic ALV 里比 `MODIFY` 更惯用的写法。
  - `WITH KEY fieldname` 未指定 `sy-subrc` 之外的 `binary search`（对非排序表会退化为顺序扫描，但 `fieldcat` 一般 10~30 行，可忽略）。
  - `edit` / `do_sum` 是**本程序唯一的"列级开关"**，全部硬编码在 `START-OF-SELECTION` 里，没有配置化。
  - 缺少 `justification = 'R'`（右对齐，数字列应右对齐）、`no_outline`、`key`（MATNR 未标为 key 列）。

### 4.4 事件注册与显示 `ztest7.abap:37-46`

```abap
APPEND VALUE #( name = 'DATA_CHANGED' form = 'GET_DATA_CHANGED' ) TO gt_events.

CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
  EXPORTING
    i_callback_program       = sy-repid
    it_fieldcat              = gt_fieldcat
    it_events                = gt_events
    i_callback_pf_status_set = 'SET_PF_STATUS'
  TABLES
    t_outtab                 = gt_mara.
```

- `VALUE #(...)` 行结构构造 + `APPEND` 是现代 ABAP 语法在 Classic 报表里的正确用法。
- `i_callback_program = sy-repid`：把 `DATA_CHANGED` 事件路由回**本程序**的 `FORM get_data_changed`。
- `i_callback_pf_status_set`：在 grid 创建完成后回调 `FORM set_pf_status` 来设置状态栏 —— 这是 Classic ALV **唯一**能在 fullscreen 下拿到 `go_grid` 引用的时机（也是 `GET_GLOBALS_FROM_SLVC_FULLSCR` hack 存在的原因）。
- 🔴 **没有 `EXCEPTIONS`**：`REUSE_ALV_GRID_DISPLAY` 有 `error_cnt_create_error / initialization_error / program_error / cntl_error / cntl_no_error_cntl / cntl_zero_error_cntl / cntl_internal_error` 七种异常。不声明意味着任一异常直接 short dump，**没有任何可诊断的信息**。
- 没有 `it_sort`（默认排序 = DB 顺序）、`i_grid_title`、`i_default_layout` / `i_save`（无布局变式）、`i_callback_toolbar`（无保存/导出按钮）、`i_callback_user_command`。
- `t_outtab` 是 `TABLES` 参数（已废弃写法，OO ALV 惯例是 `gt_mara` 传引用），但对 Classic FM 仍必须这么写。

### 4.5 `FORM set_pf_status` `ztest7.abap:51-72`

```abap
FORM set_pf_status USING itr_extab TYPE slis_t_extab.

  CALL FUNCTION 'GET_GLOBALS_FROM_SLVC_FULLSCR'
    IMPORTING
      e_grid = go_grid.
  IF go_grid IS BOUND.
    CALL METHOD go_grid->register_edit_event
      EXPORTING i_event_id = cl_gui_alv_grid=>mc_evt_modified.
    CALL METHOD go_grid->register_edit_event
      EXPORTING i_event_id = cl_gui_alv_grid=>mc_evt_enter.
  ENDIF.

  CASE sy-ucomm.
    WHEN OTHERS.
  ENDCASE.
ENDFORM.
```

- **形态**：参数名必须叫任意但类型要对 —— FM 传的是 `it_extab TYPE slis_t_extab`，这里 `itr_extab` 类型匹配 ✅，但**从未使用**。因为 `REUSE_ALV_GRID_DISPLAY` 没有传 `i_extab`，所以拿到的是空表 + **标准 PF-STATUS**（无自定义按钮）。
- **双重身份**：这个 FORM 干了三件不相干的事——(a) 抓全局引用，(b) 注册编辑事件，(c) 命令分派。职责不单一。
- `GET_GLOBALS_FROM_SLVC_FULLSCR` 是 SAP 官方 FM，但语义是"从 ALV 全局管理器里反查当前活动控件"，**依赖调用时机和唯一的 active list**，是全局状态耦合的典型。OO 时代的正规替代是用 `E_OBJECT` 传对象引用。
- `register_edit_event` 放在这里意味着**每次 PF-STATUS 设置都注册一遍**（PF-STATUS 可能被多次设置，重复注册幂等，风险小但语义不清）。更规范的位置是 grid 创建成功之后立即注册。
- 同时注册 `MODIFIED` + `ENTER`：一次编辑可能触发**两次** `DATA_CHANGED`（离开单元格一次、回车一次）。当前逻辑幂等（每次都重算），所以无实害，但多了一倍开销。
- `CASE sy-ucomm. WHEN OTHERS. ENDCASE.` —— **纯空壳**，死代码。`sy-ucomm` 在 PF-STATUS 回调里通常有值，但既然没做 `i_callback_user_command` 配套，命令分派应写在 `user_command` 回调中更可靠。

### 4.6 `FORM get_data_changed` `ztest7.abap:74-115`（核心）

分段拆解：

**① 守卫 + 提取变更单元格**

```abap
LOOP AT io_data_changed->mt_mod_cells ASSIGNING FIELD-SYMBOL(<gs_changed>)
      WHERE fieldname = 'BRGEW'.
  READ TABLE gt_mara ASSIGNING FIELD-SYMBOL(<gs_tab>) INDEX <gs_changed>-row_id.
  IF sy-subrc EQ 0.
    <gs_tab>-brgew = <gs_changed>-value.
  ENDIF.
ENDLOOP.
```

- `mt_mod_cells` 是**本次编辑的差量集**（用户可能一次粘贴多格/改多行），按 `fieldname` 过滤后逐个回写 —— 这个处理方式本身是正确的，且比"整表刷新"高效。
- ✅ `READ TABLE ... INDEX` 后面立刻判 `sy-subrc`，正确。
- 🔴 `INDEX <gs_changed>-row_id` **默认 `row_id` 是 ALV 显示行号**。用户排序或过滤后，显示行序 ≠ 内表物理行序，会**写错行**。`cl_alv_changed_data_protocol` 提供了 `get_cell_value` / `modify_cell` 这类按协议内部索引操作的方法，语义不会错位。（POC 里表空 + 只有 10 行，看不出问题，但这是必须修的正确性缺陷。）
- ⚠️ 直接 `<gs_tab>-brgew = <gs_changed>-value`：`value` 是通用类型（ALV 通常已按 `fieldcat` 的 `REF` 转成数值），若字段目录缺 `ref`，可能以字符形式传入，隐式转换到 `QUAN` 会带来小数位/舍入风险。规范做法：`io_data_changed->get_cell_value(...)` + fieldcat 里给 `BRGEW` 配 `ref = 'ZTEST_S-BRGEW'`。
- ⚠️ 无任何输入校验（负数/0/超限/单位非 KG 的毛重）。

**② 取总计并覆写**

```abap
go_grid->get_subtotals(
  IMPORTING
    ep_collect00 = gr_data   " Overall Total
).

ASSIGN gr_data->* TO <gtr_sum_tab>.
READ TABLE <gtr_sum_tab> ASSIGNING FIELD-SYMBOL(<l_sum>) INDEX 1.
IF sy-subrc EQ 0.
  ASSIGN COMPONENT 'BRGEW' OF STRUCTURE <l_sum> TO FIELD-SYMBOL(<lg_val>).
  IF <lg_val> IS ASSIGNED.
    <lg_val> = REDUCE #( INIT lv_i TYPE ntgew_15
                     FOR <ls_t> IN gt_mara
                     NEXT lv_i = lv_i + <ls_t>-brgew ).
  ENDIF.
ENDIF.
```

- `get_subtotals` 的 `EP_COLLECT00` 返回 grid 自己算出的**总计行**（一个 ALV 行结构的引用），本质是"把 grid 的聚合结果借出来给我用"。写法是社区标准套路。
- 然后用 `REDUCE #(...)` **自己把整表重加一遍**，把结果写回这个总计结构。意图不明，大概率是 POC 作者为了"显式演示 ABAP 侧求和"（`NTGEW_15` 是数量类型，3 位小数，与 `BRGEW` 的 `QUAN` 匹配）。
- 🔴 **口径冲突风险（重要）**：grid 的合计遵循 `do_sum` 且通常**只统计过滤/可见行**（受 ALV 的合计语义影响），而 `REDUCE` 遍历的是**全内表**。一旦用户加了过滤，屏幕上的合计会和程序语义不一致——代码正在**制造**"两个真相"。
- ⚠️ `ASSIGN gr_data->*` 之前没有 `IF gr_data IS BOUND`。若 grid 未返回总计（无 `do_sum` 字段、或控件异常），`gr_data` 为初始引用，解引用会抛 `CX_SY_REF_IS_INITIAL` → short dump。
- ⚠️ 性能：每次单元格编辑触发 **两趟全表扫描**（grid 一次 + `REDUCE` 一次）。10 行无所谓；换成全量 MARA（百万级）就是编辑即卡死的量级。
- ⚠️ `ASSIGN COMPONENT ... TO <lg_val>`（通用类型）使赋值退化为动态、无编译期类型检查，收益（少写一个字段符号）远小于可读性损失。

**③ 刷新**

```abap
gs_stable-col = 'X'.
gs_stable-row = 'X'.

go_grid->refresh_table_display(
  EXPORTING
    is_stable      = gs_stable
    i_soft_refresh = 'X'
  EXCEPTIONS finished = 1 OTHERS = 2).
IF sy-subrc <> 0.
ENDIF.
```

- `is_stable-row/col = 'X'`：**保持行/列的相对位置不变**，避免每次编辑后用户光标跳回顶部。✅ 这是可编辑表格的**标准且必要**的做法。
- `i_soft_refresh = 'X'`：软刷新，**保留用户的排序和过滤**。✅ 正确。
- `EXCEPTIONS finished = 1` 的注释写"Display was Ended (by Export)"——但本程序**没有任何工具栏/导出功能**，注释与实际不符，属复制粘贴残留。
- 🔴 `IF sy-subrc <> 0. ENDIF.` —— **空 IF，什么都不做**。捕获了异常却不处理，比不捕获更糟（掩盖问题）。
- ⚠️ 在 `DATA_CHANGED`（而非 `DATA_CHANGED_FINISHED`）事件里调 `refresh_table_display` 属于官方不推荐的做法：编辑事件尚未收尾就重绘，可能造成光标/焦点抖动。规范做法是改注册 `DATA_CHANGED_FINISHED`，或干脆不刷新（grid 本身会重算合计）。

---

## 5. 问题清单（按严重度）

### P0 —— 功能不通（当前状态跑不出 POC 效果）

| # | 位置 | 问题 | 影响 |
|---|---|---|---|
| 1 | `:18` vs `:46` | 数据 SELECT 进 `_mara`，ALV 却用 `gt_mara` | **界面 0 行**；编辑与合计逻辑完全不可达；整份 POC 等于没跑通 |
| 2 | `:79` | `INDEX <gs_changed>-row_id` 假设显示行序 = 内表行序 | 排序/过滤后**写错行**（静默数据损坏） |

### P1 —— 健壮性与正确性

| # | 位置 | 问题 |
|---|---|---|
| 3 | `:39-46` | `REUSE_ALV_GRID_DISPLAY` 未声明 `EXCEPTIONS` → 控件创建失败即 short dump |
| 4 | `:90` | `ASSIGN gr_data->*` 前缺 `IS BOUND` 检查 → 空引用解引用 |
| 5 | `:78-97` | 合计口径冲突：grid 合计（可能仅可见行） vs `REDUCE` 全表求和 |
| 6 | `:78-97` | 合计口径未定义：**根本没必要自己算**，`do_sum = 'X'` 已由 grid 维护 |
| 7 | `:78` | 缺输入校验；缺 fieldcat `ref`，`value` 隐式转换有风险 |
| 8 | `:81` | 直接改 `gt_mara` 而非用 `modify_cell`/`get_cell_value`，行号语义隐患 |
| 9 | 无 | 无权限检查、无持久化、无错误提示（fieldcat 失败时用户只见空白屏） |

### P2 —— 性能与可维护性

| # | 位置 | 问题 |
|---|---|---|
| 10 | `:85-96` | 每次编辑两趟全表扫描（`get_subtotals` + `REDUCE`）→ 大数据量必卡 |
| 11 | `:102-109` | 在 `DATA_CHANGED` 而非 `DATA_CHANGED_FINISHED` 中刷新，光标易抖 |
| 12 | `:58-64` | `MODIFIED` + `ENTER` 双注册 → 单次编辑回调两次 |
| 13 | `:51-72` | 一个 FORM 兼三职（抓引用/注册事件/命令分派）；`itr_extab` 未用；`CASE` 为死代码 |
| 14 | `:95` | 合计逻辑埋在回调里，不可独立测试、不可复用（应抽为独立 FORM/FORM 链） |
| 15 | `:4-11` | 全局状态 6 个变量全裸奔，无封装；`gr_data` / `gs_stable` 命名不遵循 `gt_/gs_/go_` 约定 |
| 16 | `:15-18` | `MARA` 无 `WHERE` 无 `ORDER BY` 的 `UP TO 10 ROWS` → 结果不确定、DB 压力不可控 |
| 17 | `:23` | `'ZTEST_S'` 字面量无编译期检查 |
| 18 | 全局 | 混用 SLIS 类型（`SLIS_T_*`）与 LVC 类型（`LVC_S_STBL`） |
| 19 | `:107` | `finished` 注释提"Export"但无导出功能；`:110-111` 空 IF |
| 20 | 全局 | 无选择屏、无布局变式、无工具栏、无标题、无列格式化（数值对齐/单位显示） |

---

## 6. 改进建议

### 6.1 立即修复（P0）

```abap
* ① 让数据真的进 ALV 内表。★注意：SELECT INTO 结构化内表按"选择列表位置"映射到结构组件，
*    务必保证 ZTEST_S 的前两个组件依次是 MATNR、BRGEW；否则显式 Z 结构再 MOVE。
SELECT matnr, brgew
  FROM mara
  WHERE client = @sy-mand
  INTO TABLE @gt_mara
  UP TO 10 ROWS.
```

```abap
* ② 不要用 INDEX + row_id 定位行；用协议自身的行索引，避免排序/过滤错位
LOOP AT io_data_changed->mt_mod_cells ASSIGNING FIELD-SYMBOL(<ls_mod>)
      WHERE fieldname = 'BRGEW'.
  io_data_changed->get_cell_value( <ls_mod>-row_id <ls_mod>-col_id <lv_value> ).
  IF <lv_value> <= 0.
    " 可选：回写并提示
    CONTINUE.
  ENDIF.
  io_data_changed->modify_cell( is_mod_cell = <ls_mod> ip_data = <lv_value> ).
ENDLOOP.
```

### 6.2 删掉自造的合计（最有价值的一处简化）

`do_sum = 'X'` 之后，**grid 自己在编辑后会重算并刷新合计**。`get_subtotals` + `ASSIGN COMPONENT` + `REDUCE` 这一整段是纯粹的重复劳动，还引入了口径冲突、空引用和 O(n) 开销。删掉后回调瘦身为：

```abap
FORM get_data_changed USING io_data_changed TYPE REF TO cl_alv_changed_data_protocol.

  LOOP AT io_data_changed->mt_mod_cells ASSIGNING FIELD-SYMBOL(<ls_mod>)
        WHERE fieldname = 'BRGEW'.
    io_data_changed->get_cell_value( <ls_mod>-row_id <ls_mod>-col_id <lv_weight> ).
    IF <lv_weight> <= 0.
      " 写回原值或 set_protocol_entry 上报错误
    ENDIF.
    io_data_changed->modify_cell( is_mod_cell = <ls_mod> ip_data = <lv_weight> ).
  ENDLOOP.

  " 保持光标位置：仍然建议保留一次 soft refresh（或改用 DATA_CHANGED_FINISHED）
  gs_stable-row = 'X'.
  gs_stable-col = 'X'.
  go_grid->refresh_table_display( EXPORTING is_stable = gs_stable i_soft_refresh = 'X' ).
ENDFORM.
```

> 如果业务上**确实**要求"自己算"（比如要按基本单位换算、排除某些行、或合计值要落库），那就把逻辑抽成独立单元并写清口径：
>
> ```abap
> FORM get_total_weight USING it_rows TYPE tt_ztest_s CHANGING ev_total TYPE ntgew_15.
>   ev_total = REDUCE ntgew_15( INIT lv_sum = 0
>                        FOR ls_row IN it_rows NEXT lv_sum = lv_sum + ls_row-brgew ).
> ENDFORM.
> ```
> 这样可被单元测试覆盖，也不再依赖 `go_grid` 副作用。

### 6.3 健壮性

```abap
  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    ...
    EXCEPTIONS
      error_cnt_create_error = 1  initialization_error  = 2
      program_error          = 3  cntl_error           = 4
      cntl_no_error_cntl     = 5  cntl_zero_error_cntl = 6
      cntl_internal_error    = 7.
  IF sy-subrc <> 0.
    MESSAGE 'ALV 控件创建失败，请检查 GUI 状态' TYPE 'E'.
    RETURN.
  ENDIF.
```

- fieldcat 合并失败也要 `MESSAGE ... TYPE 'E'`，否则用户看到空白屏却不知道为什么。
- `ASSIGN gr_data->*` 之前加 `IF gr_data IS BOUND.`，`REDUCE` 前后加边界检查。

### 6.4 事件与刷新

- 改注册 **`DATA_CHANGED_FINISHED`**（值已稳定）来做刷新，避免 `DATA_CHANGED` 中途重绘。
- `register_edit_event` 移到 grid 创建后一次性的位置，不要放在可能重复触发的 `set_pf_status` 里。
- 只保留 `mc_evt_modified`（或只保留 `mc_evt_enter`）之一，去掉双触发。

### 6.5 交互与可维护性补齐

- 加 `i_grid_title`、`i_callback_toolbar`（保存/取消/导出）、`i_default_layout = 'X'` + `i_save = 'A'`（布局变式）。
- fieldcat 补：`MATNR` 设 `key = 'X'`（作为默认排序键，顺带解决排序稳定性）、`BRGEW` 设 `justification = 'R'`、必要时 `ref`。
- 拆职责：`set_pf_status` 只留命令分派；grid 引用获取与事件注册各自独立。
- 用 `CONSTANTS` 收口 `'ZTEST_S'`、`'BRGEW'` 等字面量。
- 若这程序要"投产"，**必须**补：选择屏 + 物料范围 + `AT_CHECK` 授权 + 输入校验 + 走 `BAPI_MATERIAL_SAVEGENERAL` 回写（不可 `UPDATE mara`）。

### 6.6 现代化替代方向

`REUSE_ALV_GRID_DISPLAY` + `GET_GLOBALS_FROM_SLVC_FULLSCR` + `FORM` 回调已经是三代前的技术栈。如果目标不是"必须复用现有 ALV"，更合理的是：

- **数据源**：把 `SELECT ... FROM mara UP TO 10 ROWS` 换成 **CDS View**（带物料/工厂筛选、已算好 `SUM` 聚合、暴露语义模型），让"合计"在数据库层完成。
- **UI 层**：`cl_salv_gui_alv_grid`（SALV）有类事件、对象引用直连、无需 `TYPE-POOLS`。**但 SALV 默认不支持单元格编辑**，要编辑仍需回落 Classic ALV 或自绘/ Fiori。—— 这正是 Classic ALV 至今还活在很多 MM 报表里的原因。
- 若这是 BP/ Fiori 场景：**可编辑 + 实时合计**用 Fiori 的 `Editable Table` + `Aggregation` 模板是最贴的方案，合计可用 `$sum` 声明式实现。

---

## 7. 复现/验证要点

| 场景 | 预期（修复后） |
|---|---|
| 直接执行 `SAVF` `ZTEST7` | 弹出全屏 ALV，显示 10 行物料 |
| 点 `BRGEW` 单元格按 F9 | 可编辑（`edit = 'X'`） |
| 输入 `999` 回车 | 该行毛重变 999，底部合计行同步变化，光标不跳行 |
| 在合计行上右键 → 汇总信息 | 显示 GTOTAL = 10 行之和 |
| **先在表头排序，再改一个单元格** | 改的是**屏幕上那一行**（回归第 2 条 P0 修复） |
| **加一个过滤条件后再改单元格** | 合计口径明确且与业务预期一致（回归第 5/6 条） |
| 传入负数 / 非数字 | 被拒绝并提示（回归第 7 条） |

---

## 8. 总评

**技术点选得对**：Classic ALV 里"可编辑列 + 编辑后重算合计"确实是这套框架的标准能力，`do_sum` / `DATA_CHANGED` / `is_stable` + `soft_refresh` 三个关键抓手都用上了，方向没有错。

**但完成度不足**：作为 POC，它连"能看见数据"这一步都没走通（P0-1），合计逻辑又是重复实现且口径不清（P1-5/6），错误处理基本为零。要让这个 POC 真正说服人，最小改动是 3 件事：**把数据 SELECT 进 `gt_mara`**、**删掉自造的 `REDUCE` 合计**、**给 `REUSE_ALV_GRID_DISPLAY` 补 `EXCEPTIONS` 和错误提示**。做完这三步，这份代码就可以作为"Classic ALV 可编辑合计"的合格教学样本了。
