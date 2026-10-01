# ztest7.abap 程序分析报告

> 样本：`D:\Workspace\Skills\analyzing-programs\evals\ztest7.abap`（115 行，`REPORT` + `TYPE-POOLS: slis`）

---

## 一、一句话结论

`ztest7` 是一个**"可编辑 ALV + 合计行"技术验证（POC）**：从 `MARA` 随手取 10 行物料，把 `BRGEW`（毛重）列做成可编辑，用户改动后由 `DATA_CHANGED` 回调回写内表，并试图用 `get_subtotals` + `REDUCE` 手工把合计值算出来。整体是 **SAP 传统 ALV（Function Module + `slis` type pool）** 的经典结构，思路可以借鉴，但**当前代码存在 1 个阻断级缺陷和 3 个正确性缺陷，且合计那一整块逻辑实际上对屏幕显示毫无作用**。

---

## 二、它解决什么问题（业务问题）

严格说，它**没有业务问题**，它解决的是一个**技术问题**：

| 维度 | 说明 |
| --- | --- |
| 表面需求 | 让用户在 ALV 上直接修改物料毛重 `BRGEW`，并让合计行随编辑实时更新 |
| 真实动机 | 验证两件在旧 ALV 里"容易写错"的事：<br>1. `DATA_CHANGED` 事件里如何把用户的编辑**正确地回写**到后端内表；<br>2. 合计行（sum line）的取值**到底该由 ALV 自己算，还是手工算** |
| 业务语义 | 没有。选数据是 `SELECT matnr, brgew FROM mara UP TO 10 ROWS` —— 任意 10 条；写入只落在内存 `gt_mara`，**没有任何落库动作**（无 BAPI、无 FM、无 COMMIT） |
| 使用者 | 开发自己（没有 ALV 变式、用户清单、权限控制的痕迹） |

所以定位是：**demo / 骨架 / 技术验证**，不是可交付程序。目录名 `alv-editable-total-poc` 与代码内容完全吻合。

需要特别指出的是，"合计"这件事本身已经由 `fieldcat-do_sum = 'X'` 解决了（第 34 行）。程序后面 12 行（85–97 行）手工再算一次，属于**对同一问题的二次求解**——这正是本程序最需要讨论的地方（见第六节）。

---

## 三、整体架构

### 3.1 技术栈与风格

* **非 OO**：不是 `CL_SALV_TABLE` / `SALV_MODEL`，而是 **BC ALV 的 FM 套件**（`REUSE_ALV_GRID_DISPLAY` / `REUSE_ALV_FIELDCATALOG_MERGE` / `GET_GLOBALS_FROM_SLVC_FULLSCR`），依赖 `TYPE-POOLS: slis` 提供的 `slis_t_fieldcat_alv` 等类型。
* **全局状态驱动**：`REPORT` 的 6 个全局数据对象（4–9 行）承担了"数据 / 元数据 / 事件 / 控件引用 / 稳定性标志 / 合计结果"六种角色，事件回调 `FORM` 靠 `sy-repid` + 函数名做字符串关联，没有类、没有引用传递。
* **事件回调模型**：ALV 的"用户动作"通过两个 `FORM` 挂接，而不是通过类的 `ON_EVENT`：

```
                ①REUSE_ALV_FIELDCATALOG_MERGE → 拿到字段目录
                ②手工改 BRGEW: edit/do_sum
                ③REUSE_ALV_GRID_DISPLAY
                        │  i_callback_pf_status_set
                        ▼
              SET_PF_STATUS ──► 取 grid 引用 + register_edit_event(mc_evt_modified/mc_evt_enter)
                        │
                 用户改单元格
                        ▼  it_events 里的 DATA_CHANGED
              GET_DATA_CHANGED ──► 回写内表 → 取 subtotals → REDUCE 覆盖 → 手工刷新
```

### 3.2 五个模块（按职责分组）

| 模块 | 行号 | 职责 | 耦合点 |
| --- | --- | --- | --- |
| M1 全局声明 | 4–11 | 承载跨 `FORM` 共享的状态 | 全部依赖全局变量，无法参数化、无法单测 |
| M2 主流程 | 13–48 | 取数 → 生成 fieldcat → 配事件 → 显示 ALV | 嵌了两层 `IF sy-subrc`，异常被吞 |
| M3 PF-Status | 51–72 | 取 grid 对象引用、注册编辑事件 | `FORM` 参数 `itr_extab` 未使用 |
| M4 事件处理 | 74–83 | 把单元格改动写回 `gt_mara` | **用 `row_id` 当内表索引（核心风险点）** |
| M5 合计 + 刷新 | 85–111 | 取合计、改合计、稳定刷新 | **对 UI 无效、且吞异常** |

### 3.3 数据流

```
MARA (DB, 10 行)
   │  SELECT ... INTO TABLE _mara          ← 目标变量与 gt_mara 不一致（阻断级问题）
   ▼
gt_mara : TABLE OF ztest_s                  ← ALV 的 t_outtab（视图模型）
   │                                       ← 唯一持久状态，无版本号/无脏标记
   ▼
cl_gui_alv_grid (Full-screen)              ← 控件内部另存一份展示数据
   │  DATA_CHANGED / mt_mod_cells
   ▼
gt_mara (回写) ──► get_subtotals ──► gr_data ──► REDUCE ──► refresh_table_display
                     (返回副本，修改无效)  (算出的值 = do_sum 已有值)
```

**关键认知**：ALV grid 内部有自己的一份数据副本，程序侧的 `gt_mara` 与它是**两份数据**。所有编辑回写与刷新同步的麻烦，都源于这个"两份数据"模型。程序选择手工同步（写内表 + 手工刷新），而现代做法是交给 `it_data_changed->modify_cell()` 一步到位。

---

## 四、执行流程

1. **M2 启动**（13 行）：`START-OF-SELECTION` 从 `MARA` 读 `MATNR/BRGEW`，`UP TO 10 ROWS` 截断。
2. **生成字段目录**（20–29 行）：`REUSE_ALV_FIELDCATALOG_MERGE` 以 DDIC 结构 `ZTEST_S` 为模板产出 `gt_fieldcat`（这也是 `TYPE-POOLS: slis` 存在的唯一理由）。
3. **开放编辑 + 合计**（31–35 行）：在 fieldcat 里找到 `BRGEW`，置 `edit = 'X'`、`do_sum = 'X'`。**合计行能力在这一步已经完成。**
4. **挂事件**（37 行）：向 `gt_events` 追加 `DATA_CHANGED → GET_DATA_CHANGED`。
5. **显示 ALV**（39–46 行）：`REUSE_ALV_GRID_DISPLAY`，把 `gt_mara` 作为 `t_outtab`，并指定自定义 PF-Status 例程。
6. **M3 初始化**（51–65 行）：ALV 回调 `SET_PF_STATUS`；`GET_GLOBALS_FROM_SLVC_FULLSCR` 拿到 `go_grid` 引用；**注册 `mc_evt_modified` 与 `mc_evt_enter`**（必须注册，否则编辑类字段不可输入）。
7. **用户编辑**：`ENTER` 或 `mc_evt_modified` 触发 `DATA_CHANGED`。
8. **M4 回写**（78–83 行）：遍历 `mt_mod_cells` 中 `fieldname = 'BRGEW'` 的项，用 `row_id` 作 `INDEX` 找到 `gt_mara` 行，写入 `value`。
9. **M5 合计与刷新**（85–109 行）：`get_subtotals` 取回合计表 → `ASSIGN COMPONENT 'BRGEW'` 定位列 → 用 `REDUCE` 全表求和覆盖 → 设 `gs_stable` 稳定行/列 → `refresh_table_display(i_soft_refresh = 'X')`。

---

## 五、按子程序分组讲解

### M1 全局声明（4–11 行）

```abap
DATA: gt_mara     TYPE TABLE OF ztest_s,
      gt_fieldcat TYPE slis_t_fieldcat_alv,
      gt_events   TYPE slis_t_event,
      go_grid     TYPE REF TO cl_gui_alv_grid,
      gs_stable   TYPE lvc_s_stbl,
      gr_data     TYPE REF TO data.

FIELD-SYMBOLS: <gtr_sum_tab> TYPE table.
```

`go_grid` 是后面三个动作的前提（注册事件、取合计、刷新），必须靠 `GET_GLOBALS_FROM_SLVC_FULLSCR` 回填。`gr_data TYPE REF TO data` 配 `<gtr_sum_tab> TYPE table` 是**完全类型擦除**的写法：拿不到任何编译期类型检查，字段名写错只在运行时炸。

### M2 主流程（13–48 行）

```abap
  SELECT matnr,
         brgew
    FROM mara
    INTO TABLE _mara UP TO 10 ROWS.
  IF sy-subrc EQ 0.
```

* `INTO TABLE _mara`：源码中**没有 `_mara` 的 `DATA` 声明**。而 `_MARA` 恰恰是 ABAP **对话模块的系统字段**（结构类型 `MARA`，不是内表）。这一行要么编译不过，要么语义完全错位。
* 即使它能编译，ALV 的 `t_outtab` 传的是 `gt_mara`（46 行），而数据读进了 `_mara` → **屏幕上是一张空表**。这是最典型的"POC 半成品"痕迹。

```abap
      CALL FUNCTION 'REUSE_ALV_FIELDCATALOG_MERGE'
        EXPORTING
          i_program_name         = sy-repid
          i_structure_name       = 'ZTEST_S'
        CHANGING
          ct_fieldcat            = gt_fieldcat
        EXCEPTIONS
          inconsistent_interface = 1
          program_error          = 2
          OTHERS                 = 3.
```

* `i_structure_name` 硬编码字符串 `'ZTEST_S'`，与 `gt_mara TYPE TABLE OF ztest_s` 重复声明同一依赖；打错字或 DDIC 未传输（无 TDDIR 记录）就落进 `program_error`。
* 三个异常全部**不区分处理、无 MESSAGE**，失败即整块 `IF sy-subrc = 0` 跳过，程序静默结束。

```abap
        <gs_fcat>-edit = 'X'.
        <gs_fcat>-do_sum = 'X'.
```

**这两行是整个"合计需求"的正解。** `do_sum = 'X'` 让 ALV 自己在底部合计行汇总该列，实时、免维护、永不与筛选后子集不一致。后面 85–97 行的手工合计与之重复。

### M3 `FORM set_pf_status`（51–72 行）

```abap
FORM set_pf_status USING itr_extab TYPE slis_t_extab.
  CALL FUNCTION 'GET_GLOBALS_FROM_SLVC_FULLSCR'
    IMPORTING
      e_grid = go_grid.
  IF go_grid IS BOUND.
    CALL METHOD go_grid->register_edit_event
      EXPORTING
        i_event_id = cl_gui_alv_grid=>mc_evt_modified.
    CALL METHOD go_grid->register_edit_event
      EXPORTING
        i_event_id = cl_gui_alv_grid=>mc_evt_enter.
  ENDIF.
```

* 注册 `mc_evt_modified` / `mc_evt_enter` 是**编辑型 ALV 的必要样板代码**，缺了 `-edit = 'X'` 的列就敲不进字。写法正确。
* `CASE sy-ucomm. WHEN OTHERS. ENDCASE.`（68–71 行）是空壳：没有 `SAVE` / `EXIT` / `REFRESH` 任何一个功能码；且**因为指定了 `i_callback_pf_status_set`，就必须自己设置状态**，而这里既没调 `ALV_SET_TOOLBAR`，也没给 `set_pf_status` 的 `r_sucomm`/`r_exit` 赋回值 → 用户大概率面对一个**空的工具栏/状态栏**。
* 参数 `itr_extab` 未使用（无备选状态切换能力）。

### M4 `FORM get_data_changed`（74–83 行）— 最关键的风险点

```abap
    LOOP AT io_data_changed->mt_mod_cells ASSIGNING FIELD-SYMBOL(<gs_changed>) WHERE fieldname = 'BRGEW'.
      READ TABLE gt_mara ASSIGNING FIELD-SYMBOL(<gs_tab>) INDEX <gs_changed>-row_id.
      IF sy-subrc EQ 0.
        <gs_tab>-brgew = <gs_changed>-value.
      ENDIF.
    ENDLOOP.
```

* 意图正确：只处理被改动的 `BRGEW` 单元格，避免全表比对。
* **缺陷**：`row_id` 是 **ALV 当前显示顺序**（含排序、筛选、隐藏行）的行号，而 `gt_mara` 是**原始顺序**。用户按 `MATNR` 排序后再改第 1 行，值会写进 `gt_mara` 的第 1 条（可能是完全无关的物料）→ **静默数据错乱**，且因为第 5 步的稳定刷新，错写的内容还可能马上被覆盖，看起来"像是对的"。
* `IF sy-subrc EQ 0` 的判断在 `ASSIGNING ... INDEX` 场景下只能挡住越界，挡不住"索引语义错位"。

### M5 合计 + 刷新（85–111 行）— 无效功 + 静默吞异常

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
        <lg_val> = REDUCE #( INIT lv_i TYPE ntgew_15 FOR <ls_t> IN gt_mara NEXT lv_i = lv_i + <ls_t>-brgew ).
      ENDIF.
    ENDIF.
```

逐条拆解：

1. **`get_subtotals` 每次调用都返回一份新的结果表**（`ep_collect00` 是 data reference，指向新建的合计行集合）。因此 `ASSIGN gr_data->*` 之后改 `<lg_val>`，改的是**这份临时副本**，Grid 下一帧会自己重新算 —— 这段赋值**对屏幕零影响**。
2. **算出来的值与 `do_sum` 的值完全相同**：`REDUCE` 对 `gt_mara` 全表求和，正是 ALV 合计行已有的值。也就是说：**先向 ALV 要一次答案，再自己算一遍同样的答案，写进一个没人读的变量。**
3. **筛选态下还不一致**：如果用户按条件筛选出 5 行，ALV 合计行只算这 5 行，而 `REDUCE` 算的是 `gt_mara` 全部 10 行 —— 程序里存在两个互相矛盾的"合计"。
4. **`IF <lg_val> IS ASSIGNED` 是死代码**：`ASSIGN COMPONENT` 未带 `CATCHING` 时，失败会直接 **dump**（运行时错误），不会给 `sy-subrc`。所以 `IS ASSIGNED` 恒为真，这个判断提供的是**虚假的安全感**。
5. `REDUCE` 里 `TYPE ntgew_15` 是正确的类型选择（`BRGEW` 即 `NTGEW`，15 位含 3 位小数），但只有 12 位整数位，且**没有溢出检查、没有符号位处理、没有单位（`MEINS`）校验**。

```abap
    gs_stable-col = 'X'.
    gs_stable-row = 'X'.

    go_grid->refresh_table_display(
      EXPORTING
        is_stable      = gs_stable
        i_soft_refresh = 'X'
      EXCEPTIONS
        finished       = 1
        OTHERS         = 2
    ).
    IF sy-subrc <> 0.
    ENDIF.
```

* `is_stable` 稳定行/列 + `i_soft_refresh`（保留排序/筛选）是合理的组合，意图是"编辑后光标不跳、排序不丢"。
* 但 `DATA_CHANGED` 事件**结束后 ALV 本来就会自动刷新**；这里再手工 `refresh_table_display` 属于**多余且有害**：多一次全量重绘、编辑密集时明显卡顿，并存在事件重入的隐患。
* `IF sy-subrc <> 0. ENDIF.` 是**空 IF 壳**，`finished = 1`（显示被 Export 结束）与其他异常被静默丢弃 —— 用户会看到"改了没反应"却没有任何提示。

---

## 六、核心机制小结：合计到底该谁算

| 做法 | 本程序 | 评价 |
| --- | --- | --- |
| `fieldcat-do_sum = 'X'` | ✅ 第 34 行 | **正解**：ALV 内部维护，永远正确，自动适配排序/筛选/分组 |
| `get_subtotals` 读回改写 | ⚠️ 第 85–97 行 | **无效功**：改的是临时副本，UI 不变，还引入类型擦除与 dump 风险 |
| 编辑后手工 `refresh_table_display` | ⚠️ 第 102 行 | **多余**：ALV 事件结束已自动刷新；换成 `modify_cell` 可整段删掉 |

---

## 七、问题清单（按严重度）

### P0 阻断级

| # | 位置 | 问题 | 后果 |
| --- | --- | --- | --- |
| 1 | 18 行 | `INTO TABLE _mara` 的目标表**未声明**；`_MARA` 是对话模块系统字段（类型 `MARA`，非内表） | 编译失败；即使通过，数据也进不了 `gt_mara` |
| 2 | 18 vs 46 行 | 取数进 `_mara`，`t_outtab` 传 `gt_mara` | **ALV 空白** |
| 3 | 26–47 行 | 三个 `EXCEPTIONS` 不区分、不 `MESSAGE`；`IF sy-subrc = 0` 一跳过就静默结束 | 失败时用户看不到任何东西 |

### P1 正确性级

| # | 位置 | 问题 | 后果 |
| --- | --- | --- | --- |
| 4 | 79 行 | 用 `row_id` 直接 `INDEX gt_mara` | **排序/筛选后写错行**，静默数据损坏 |
| 5 | 85–97 行 | 改 `get_subtotals` 的返回副本 | 对 UI 无效；且筛选下与 `do_sum` 得出两个矛盾合计 |
| 6 | 93–94 行 | `ASSIGN COMPONENT` 不带 `CATCHING` + `IS ASSIGNED` 死判断 | 字段名写错 → **dump**，而非可控错误 |
| 7 | 102 行 | 事件内手工全量刷新 | 重绘开销、光标跳动、事件重入风险 |

### P2 健壮性/性能级

| # | 位置 | 问题 | 后果 |
| --- | --- | --- | --- |
| 8 | 15–18 行 | `UP TO 10 ROWS` 无 `WHERE`/`ORDER BY` | 取哪 10 行不确定，**不可复现**；`IF sy-subrc EQ 0` 对 `SELECT INTO TABLE` 恒真，无意义 |
| 9 | 95 行 | `NTGEW_15` 累加无溢出检查；无 `MEINS` 单位校验 | 极端值溢出/量纲错误 |
| 10 | 37 行 | `gt_events` 只 `APPEND` 不 `CLEAR`；`go_grid`/`gs_stable` 无初始化 | 多次调用 ALV 会**重复注册 `DATA_CHANGED`** → 回调执行多次 |
| 11 | 全局 | 无 `AUTHORITY-CHECK`、无锁、无落库、无前台校验 | 作为 POC 可接受；转生产必须补齐（`GRID_VALIDATION_REDIT` + `ENQUEUE` + BAPI） |

### P3 体验级

| # | 位置 | 问题 | 后果 |
| --- | --- | --- | --- |
| 12 | 44/51–71 行 | 指定了自定义 PF-Status 却不设置任何状态；`CASE sy-ucomm` 是空壳 | 工具栏/状态栏可能为空，无 `SAVE`/`REFRESH`/`LAYOUT` |
| 13 | 全局 | 无 F4、无 `NO_MESSAGE`/`MESSAGE`、无未保存离开提示 | 交互粗糙 |

### P4 可维护性级

| # | 位置 | 问题 |
| --- | --- | --- |
| 14 | 23 行 | `i_structure_name = 'ZTEST_S'` 硬编码字符串，与 `gt_mara` 行类型重复 |
| 15 | 9/11 行 | `REF TO data` + `TYPE table` 泛型 + 无 `CATCHING` 的 `ASSIGN`，静态检查彻底失效 |
| 16 | 3 处 | `'BRGEW'` 硬编码出现 4 次（结构名、组件名、WHERE 条件、fieldcat 查找） |
| 17 | 11 行 | `<gtr_sum_tab>` 只在 `FORM` 内使用却声明为全局 |
| 18 | 全局 | 全局变量式架构无法单元测试，回归靠手点 |

---

## 八、改进建议

### 阶段 1：先让它"跑对"

```abap
START-OF-SELECTION.

  SELECT matnr, brgew FROM mara
    INTO TABLE @gt_mara
    WHERE matnr BETWEEN '0000000000' AND '9999999999'
    ORDER BY matnr
    UP TO 10 ROWS.

  CALL FUNCTION 'REUSE_ALV_FIELDCATALOG_MERGE'
    EXPORTING
      i_program_name         = sy-repid
      i_structure_name       = 'ZTEST_S'
    CHANGING
      ct_fieldcat            = gt_fieldcat
    EXCEPTIONS
      inconsistent_interface = 1
      program_error          = 2
      OTHERS                 = 3.

  IF sy-subrc <> 0.
    MESSAGE ID '00' TYPE 'S' NUMBER '001' WITH '字段目录生成失败'.
    RETURN.
  ENDIF.
```

* 目标内表改成 `gt_mara`；`WHERE` + `ORDER BY` 让样本可复现；删掉无意义的 `sy-subrc` 判断；`EXCEPTIONS` 必须给 `MESSAGE`。
* 清理全局状态：`gt_events` 每次显示前 `CLEAR`（`gr_data`/`gs_stable` 同理）。

### 阶段 2：删掉无效功，改用 `modify_cell`（核心简化）

```abap
FORM get_data_changed USING io_data_changed TYPE REF TO cl_alv_changed_data_protocol.

  LOOP AT io_data_changed->mt_mod_cells ASSIGNING FIELD-SYMBOL(<ls_mod>)
       WHERE fieldname = 'BRGEW'.

    " ① 交给 ALV 自己改：值、数据、合计行、刷新一次完成
    io_data_changed->modify_cell(
      EXPORTING
        i_row_id    = <ls_mod>-row_id
        i_fieldname = 'BRGEW'
        i_data      = CONV ntgew_15( <ls_mod>-value ) ).

    " ② 需回写业务内表时：按业务键回写，天然免疫排序/筛选
    "    data_table 为 ALV 当前显示数据，与 row_id 对齐
    ASSIGN io_data_changed->data_table[ <ls_mod>-row_id ]
           TO FIELD-SYMBOL(<ls_alv_row>).
    IF <ls_alv_row> IS ASSIGNED.
      gt_mara[ matnr = <ls_alv_row>-matnr ]-brgew = <ls_alv_row>-brgew.
    ENDIF.
  ENDLOOP.

ENDFORM.
```

这一改动的收益是**数量级的**：

* 整段 `get_subtotals` + `ASSIGN gr_data->*` + `ASSIGN COMPONENT` + `REDUCE`（85–97 行，13 行）**直接删除**；
* `gs_stable` 全局变量、`refresh_table_display` 和它的两个 `EXCEPTIONS`（99–111 行，13 行）**全部删除**；
* `row_id` 语义错位问题**从根上消失**（不再拿显示索引去索引 `gt_mara`）；
* 合计行由 `do_sum` 持续正确，筛选态自动收敛。

> 落地前请在 SE24 里确认 `cl_alv_changed_data_protocol` 的 `DATA_TABLE` 在该事件中已被填充（不同版本略有差异）；若不可用，退而求其次用 `go_grid->get_sorted_rows( IMPORTING et_row_index = lt_idx )` 建立"显示行 → 原始行"的索引映射表，**不要**再直接用 `row_id` 当内表下标。

### 阶段 3：补齐状态栏、校验与落库（转生产时）

```abap
FORM set_pf_status USING itr_extab TYPE slis_t_extab.

  CALL FUNCTION 'GET_GLOBALS_FROM_SLVC_FULLSCR' IMPORTING e_grid = go_grid.

  SET PF-STATUS 'ZTEST7'.
  SET TITLEBAR 'ZTEST7'.
  TABLES: extab.
  extab = itr_extab.

  CASE sy-ucomm.
    WHEN 'SAVE'.
      PERFORM save_data.
    WHEN 'EXIT' OR 'BACK' OR 'CANC'.
      IF NOT grid_data_is_saved( ).
        PERFORM confirm_discard.
      ENDIF.
  ENDCASE.
ENDFORM.
```

保存时至少要有：**`AUTHORITY-CHECK`（物料主数据 + `BRC` 工厂范围）→ `ENQUEUE_EZMARA` 锁 → `BAPI_MATERIAL_SAVEMATERIALS` 或 `MATERIAL_SAVE` → `DEQUEUE` → `COMMIT WORK` → 成功/失败 `MESSAGE`**；前台编辑再叠加 `GRID_VALIDATION_REDIT` 校验（`MEINS` 单位、是否允许为空、上限）。

### 通用层面

* **字段名集中化**：`CONSTANTS c_field_brgew TYPE fieldname VALUE 'BRGEW'`，消除 4 处硬编码。
* **`ASSIGN` 全部带 `CATCHING`**，`sy-subrc` 判空；能用具名行内表就别用 `FIELD-SYMBOL` + 泛型 `TYPE table`。
* **`i_structure_name` 改为由内表行类型派生**（或干脆迁到 `CL_SALV_TABLE` + `SALV_TABLE_COLUMN`），顺带白拿校验、F4、排序、合计、PDF/Excel 导出，代码量降一半。
* **数据量放大后重新评估**：本程序 10 行无性能意义；若真到十万行，每次编辑触发 `get_subtotals` + 全量刷新会明显卡顿，`do_sum` + `modify_cell` 方案是唯一合理选择。

---

## 九、值得保留的四个"知识点"

1. `TYPE-POOLS: slis` 是传统 ALV 的**硬性依赖**，只为了 `slis_t_fieldcat_alv` / `slis_t_event` / `slis_t_extab` 这几个类型。
2. `GET_GLOBALS_FROM_SLVC_FULLSCR` 是 FM 版 ALV 里唯一能拿到 `cl_gui_alv_grid` 引用的标准途径；拿到后必须**注册编辑事件**，否则 `-edit = 'X'` 的列无法输入。
3. `DATA_CHANGED` 回调 `FORM` 的**形参类型是固定的**（`USING ... TYPE REF TO cl_alv_changed_data_protocol`），只能靠 `sy-repid` + 函数名与 ALV 关联，改名即失效（无编译期保护）。
4. `do_sum = 'X'` 就是合计行的正解；一切"手工算合计再改显示"的做法在旧 ALV 里都属于**改副本**，不产生可见效果。

---

## 十、总体评价

**架构层面**：选型是"能跑起来最省事"的经典路径，FM 套件示例多、编辑事件开箱即用，对 POC 是合理选择；但**全局变量 + `FORM` 回调 + 无落库**决定了它只能是原型，无法演进为生产程序。

**最大问题不是缺功能，而是"看起来做了、实际没生效"**：`get_subtotals` + `REDUCE` 这 13 行是全篇最容易误导人的代码 —— 它读起来像"我在控制合计"，实际上既不生效，还引入了 dump 风险。而真正的阻断问题（`_mara` 未声明、ALV 数据表对不上）会让程序连"跑起来"都做不到。

**修复路径很短**：把取数目标改成 `gt_mara`、给 `EXCEPTIONS` 加 `MESSAGE`、`DATA_CHANGED` 改用 `modify_cell` 并删除合计与刷新两段，程序就从"半成品"变成"正确且最小"。补上权限、锁、校验、落库后，才谈得上是生产程序。
