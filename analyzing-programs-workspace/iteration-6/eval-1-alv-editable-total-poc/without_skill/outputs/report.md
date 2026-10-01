# ABAP 程序分析报告：`ZTEST7`

> 分析对象：`D:\Workspace\Skills\analyzing-programs\evals\ztest7.abap`（115 行）
> 程序类型：报表程序 + TYPE-POOLS（`slis`），经典 `REUSE_ALV_*` 全屏可编辑 ALV
> 结论速览：这是一份 **可编辑 ALV + 实时合计（POC / DEMO 级）** 的骨架代码，思路正确，但存在 1 个致命数据缺陷（查库结果写进了未声明变量，ALV 实际为空表）、1 个潜在运行期短时转储（未绑定引用 ASSIGN）、以及若干类型/健壮性问题。

---

## 一、它解决什么业务问题

| 维度 | 说明 |
|---|---|
| 表面功能 | 从 `MARA`（物料主数据）取前 10 行，显示 `MATNR`（物料号）、`BRGEW`（毛重），允许用户在 ALV 表格中直接修改毛重 |
| 核心诉求 | **可编辑表格 + 编辑后合计行（Total）实时重算并正确刷新**，同时不丢行号、不丢排序/滚动位置 |
| 业务含义 | 典型的"POC 验证片段"：验证 `cl_gui_alv_grid` 的 `DATA_CHANGED` 事件、`EDIT` 标记、`DO_SUM` 合计行、`GET_SUBTOTALS` 写回总计、`REFRESH_TABLE_DISPLAY` 稳定刷新的完整链路 |
| 数据落点 | **无落库、无保存按钮**。所有修改只存在于内表 `GT_MARA` 的内存快照中，退出即丢失 |
| 结论 | 属于"技术验证型程序"，不是完整业务程序。命名（`ZTEST7` / `ZTEST_S`）与代码中残留的空 `IF`、注释掉的 `WHEN`、`" PF Status Code` 注释风格也都印证这一点 |

一句话：**它演示了"如何在 ALV Grid 中让某一列可编辑，并在每次编辑后把总计行刷新成正确值，同时保持光标不跳动"。**

---

## 二、整体架构

### 2.1 架构分层

```
┌─────────────────────────────────────────────────────────────┐
│ 层 3  事件处理层（TYPE-POOLS: SLIS 中的 FORM）                 │
│   • SET_PF_STATUS        ← ALV 显示时回调：取 grid 引用 + 注册编辑事件 │
│   • GET_DATA_CHANGED     ← 单元格修改回调：写回数据 → 重算合计 → 刷新 │
├─────────────────────────────────────────────────────────────┤
│ 层 2  控制/事件注册层（START-OF-SELECTION）                  │
│   • 查库 → 生成字段目录 → 打 EDIT/DO_SUM 标记 → 挂事件 → 显示 ALV │
├─────────────────────────────────────────────────────────────┤
│ 层 1  数据访问层（MARA 直查，UP TO 10 ROWS）                  │
├─────────────────────────────────────────────────────────────┤
│ 层 0  全局状态层（程序级 DATA / FIELD-SYMBOLS）               │
│   GT_MARA  GT_FIELDCAT  GT_EVENTS  GO_GRID  GS_STABLE  GR_DATA │
└─────────────────────────────────────────────────────────────┘
                         ↓ 封装层
        REUSE_ALV_GRID_DISPLAY / CL_GUI_ALV_GRID（SAP 标准）
```

### 2.2 全局对象清单

| 对象 | 类型 | 作用 | 备注 |
|---|---|---|---|
| `GT_MARA` | `TABLE OF ZTEST_S` | ALV 数据源（也是编辑结果的落点） | **实际未被填充，见 5.1** |
| `GT_FIELDCAT` | `SLIS_T_FIELDCAT_ALV` | 动态字段目录 | 由 FM 生成后手工改 2 个标记 |
| `GT_EVENTS` | `SLIS_T_EVENT` | 事件表 | 仅含 `DATA_CHANGED` |
| `GO_GRID` | `REF TO CL_GUI_ALV_GRID` | Grid 对象引用 | `SET_PF_STATUS` 中取得，`GET_DATA_CHANGED` 中使用 |
| `GS_STABLE` | `LVC_S_STBL` | 刷新时保持行列位置 | `col/row = 'X'` |
| `GR_DATA` | `REF TO DATA` | 承接 `GET_SUBTOTALS` 的合计结构 | 泛型引用，**未做 `IS BOUND` 判断** |
| `<GTR_SUM_TAB>` | `FIELD-SYMBOL TYPE TABLE` | 承接上一步的动态表 | 仅 FORM 内部使用，却声明在全局 |

### 2.3 架构风格评价

- **优点**：事件驱动职责划分清晰（显示前 / 显示中 / 编辑后三段分离）；把 ALV 包装 FM 的官方推荐用法用对了（`i_callback_pf_status_set` + `it_events` + `get_data_changed`）。
- **缺点**：全局可变状态过多且未收敛到单一上下文；反射式（`REF TO DATA` + 两次 `ASSIGN`）把编译期检查换成了运行期风险；`TYPE-POOLS:slis` 在 7.40+ 已属过时约束（它只为"让 FORM 可见"而存在，现可直接用局部 FORM 或改 OO）。

---

## 三、执行流程

### 3.1 主流程（`START-OF-SELECTION`，第 13–48 行）

```
1. SELECT matnr, brgew FROM mara INTO TABLE _mara UP TO 10 ROWS   (:15-18)
        ↓  ⚠ 目标变量是隐式声明的 _mara，不是 GT_MARA
2. IF sy-subrc = 0  → 至少取到 1 行                            (:19)
3. REUSE_ALV_FIELDCATALOG_MERGE  i_structure_name = 'ZTEST_S'  (:20-29)
        ↓  异常 inconsistent_interface / program_error / OTHERS
4. READ TABLE gt_fieldcat ASSIGNING <gs_fcat> WITH KEY fieldname = 'BRGEW' (:31)
5.   <gs_fcat>-edit   = 'X'                                    (:33)
6.   <gs_fcat>-do_sum = 'X'                                    (:34)
        ↓  ⚠ 未检查 sy-subrc：BRGEW 不存在时静默跳过，ALV 变成只读
7. APPEND VALUE #( name='DATA_CHANGED' form='GET_DATA_CHANGED' ) TO gt_events (:37)
8. REUSE_ALV_GRID_DISPLAY                                      (:39-46)
        i_callback_program        = sy-repid
        it_fieldcat               = gt_fieldcat
        it_events                 = gt_events
        i_callback_pf_status_set  = 'SET_PF_STATUS'
        TABLES t_outtab           = gt_mara
        ↓  FM 内部：先调用 SET_PF_STATUS，再显示网格
        ↓  FM 内部：跳转到事件循环，等待用户操作
9. 用户编辑单元格 → CL_GUI_ALV_GRID 触发 DATA_CHANGED → GET_DATA_CHANGED
```

### 3.2 子程序 A：`SET_PF_STATUS`（第 51–72 行）— ALV 显示阶段

```abap
FORM set_pf_status USING itr_extab TYPE slis_t_extab.

  CALL FUNCTION 'GET_GLOBALS_FROM_SLVC_FULLSCR'
    IMPORTING e_grid = go_grid.                 " 取得 Grid 对象引用

  IF go_grid IS BOUND.
    CALL METHOD go_grid->register_edit_event      " 注册"单元格被修改"事件
      EXPORTING i_event_id = cl_gui_alv_grid=>mc_evt_modified.
    CALL METHOD go_grid->register_edit_event      " 注册"回车确认"事件
      EXPORTING i_event_id = cl_gui_alv_grid=>mc_evt_enter.
  ENDIF.

  CASE sy-ucomm.
    WHEN OTHERS.                                  " 空壳：预留工具栏/自定义功能点
  ENDCASE.
ENDFORM.
```

关键点：
- `GET_GLOBALS_FROM_SLVC_FULLSCR` **仅适用于全屏 ALV**（`REUSE_ALV_GRID_DISPLAY` 默认全屏）。若改成弹出式，此 FM 取不到引用 → 编辑功能静默失效。
- 两次 `REGISTER_EDIT_EVENT` 是编辑功能的**开关**：不注册，ALV 允许进入单元格但修改不会回调 `DATA_CHANGED`（表现是"能选中、存不进"）。
- `CASE sy-ucomm. WHEN OTHERS. ENDCASE` 为纯占位死代码；`itr_extab` 参数未使用。

### 3.3 子程序 B：`GET_DATA_CHANGED`（第 74–115 行）— 编辑回调，核心逻辑

```
① 守卫：GO_GRID IS BOUND                                        (:76)
② 遍历 mt_mod_cells，只处理 fieldname = 'BRGEW' 的修改           (:78)
     → READ TABLE gt_mara ASSIGNING <gs_tab> INDEX row_id        (:79)
       把 <gs_changed>-value 写回 <gs_tab>-brgew                (:81)
   ★ 这一步是必需的：后面的 REDUCE 是从 GT_MARA 求和的，
     如果不回写，合计会用旧值
③ go_grid->get_subtotals( ep_collect00 = gr_data )               (:85-88)
   取回 Grid 自己算出的"总计行"结构对象
④ ASSIGN gr_data->* TO <gtr_sum_tab>   ← 解引用赋值到行结构       (:90)
   READ TABLE <gtr_sum_tab> INDEX 1 INTO <l_sum>                 (:91)
   ASSIGN COMPONENT 'BRGEW' OF STRUCTURE <l_sum> TO <lg_val>    (:93)
⑤ REDUCE # 求和覆盖合计行单元格                                  (:95)
     REDUCE #( INIT lv_i TYPE ntgew_15
               FOR <ls_t> IN gt_mara
               NEXT lv_i = lv_i + <ls_t>-brgew )
⑥ GS_STABLE-col/row = 'X'                                       (:99-100)
⑦ go_grid->refresh_table_display( is_stable = gs_stable
                                   i_soft_refresh = 'X' )       (:102-109)
⑧ IF sy-subrc <> 0. ENDIF.   ← 空 IF，死代码                     (:110-111)
```

设计意图：**"每次单元格修改 → 全量重算总计 → 覆盖 Grid 的总计行单元格 → 稳定刷新"**，属于最直白可靠的实现方式（而不是依赖 Grid 自行更新）。

---

## 四、问题清单

### 4.1 🔴 严重（会导致功能不可用 / 短时转储）

| # | 位置 | 问题 | 影响 |
|---|---|---|---|
| 1 | `:15-18` | `INTO TABLE _mara` —— **`_mARA` 全文未声明**。ABAP 对未声明标识符只在运行期于**全局数据区隐式创建**，它和 `GT_MARA` 是两个不同对象 | 查库结果进了另一个表；`:46` 传给 ALV 的 `GT_MARA` 始终为空 → **界面只有表头、一行数据都没有**，合计恒为 0。这是本程序最致命的问题 |
| 2 | `:90` | `ASSIGN gr_data->* TO <gtr_sum_tab>`，未先判断 `gr_data IS BOUND` | 当 `DO_SUM` 未生效（字段目录里没有 `BRGEW`、合计行被关闭、或 Grid 未产生 collect 数据）时 `GR_DATA` 未绑定，**解引用未绑定引用 → 运行期错误 `CX_SY_REF_IS_INITIAL` 短时转储** |
| 3 | `:95` | `INIT lv_i TYPE ntgew_15` 与目标单元格类型不一致 | `NTGEW_15`（17 位净重）与 `MARA-BRGEW`（13 位 3 位小数）宽度/小数位不同，赋值时可能**溢出截断或 `CONVT_NO_NUMBER`**；同时把"数量"语义换成"净重"语义属于语义错误 |

### 4.2 🟠 中等（功能/健壮性风险）

| # | 位置 | 问题 | 影响 |
|---|---|---|---|
| 4 | `:22-23` | 字段目录来自 DDIC 结构 `ZTEST_S`，数据却来自 `MARA` | 两处"事实来源"不一致。即便修好问题 1，`ZTEST_S-BRGEW` 与 `MARA-BRGEW` 类型不兼容时，`REUSE_ALV` 的接口一致性检查与后续 `ASSIGN COMPONENT` 都会出问题。应统一：**要么字段目录用 `'MARA'`，要么 `ZTEST_S` 的字段类型严格对齐 `MARA` 的类型** |
| 5 | `:31-35` | `READ TABLE ... WITH KEY fieldname = 'BRGEW'` 后不检查 `sy-subrc` | 找不到 `BRGEW` 就静默不设 `EDIT/DO_SUM`，用户得到一个**只读且无合计的 ALV**，且没有任何提示，极难排查 |
| 6 | `:19` | `IF sy-subrc EQ 0` 包住了**整个显示逻辑** | 查不到数据 → 不显示 ALV、不给消息 → 白屏。建议空结果时给 `MESSAGE` 或仍显示空 ALV |
| 7 | `:15-18` | `UP TO 10 ROWS` 无 `WHERE`、无 `ORDER BY` | 取哪 10 行由优化器决定，**不可复现**；且可能是已删除/已冻结的物料，`BRGEW` 可能为 0 或负数，让"合计"演示效果失真 |
| 8 | `:102-111` | `EXCEPTIONS` 捕获后 `IF sy-subrc <> 0. ENDIF.` 是空块 | 异常被吞掉；`OTHERS = 2` 与 `finished = 1` 未区分处理。建议至少 `finished` 不做刷新、`OTHERS` 记日志 |

### 4.3 🟡 轻微（代码质量 / 可维护性）

| # | 位置 | 问题 |
|---|---|---|
| 9 | `:11` | `<gtr_sum_tab>` 只在 FORM 内使用，却声明为全局；应移到 FORM 内部（同样 `:99` 的 `gs_stable` 也只被一处使用） |
| 10 | `:37` | 用 `APPEND VALUE #( ... )` 单条追加，可直接 `gt_events = VALUE #( ( name = 'DATA_CHANGED' form = 'GET_DATA_CHANGED' ) )` |
| 11 | `:67-71` | `" PF Status Code` 用双引号当注释（ABAP 惯例是 `*`）、`WHEN OTHERS` 空壳、被注释掉的 `WHEN` 残留 → 典型的复制粘贴/生成痕迹 |
| 12 | `:2` | `TYPE-POOLS:slis` 在现代 ABAP 已不需要（只为让 FORM 可被 FM 找到而设）；可改局部 FORM 或直接用 OO 封装类 |
| 13 | 全局 | 无选择屏幕（无法限定物料/工厂）、无 `SAVE` 逻辑、无 `USER_COMMAND`、无 `TOOLBAR_SET` → 作为 POC 尚可，作为报表功能不完整 |

### 4.4 ✅ 值得肯定的地方

- 事件注册（`REGISTER_EDIT_EVENT` × 2）与 `EDIT` 标记配套齐全，链路正确。
- `GS_STABLE` + `I_SOFT_REFRESH` 的组合是"编辑后刷新不跳行"的标准最佳实践。
- 用 `ASSIGNING` 代替 `READ TABLE ... INTO`（第 79 行）避免了内表整行复制，思路对。
- 手动回写 `mt_mod_cells` 到内表，使内存数据与界面一致，为后续 `REDUCE` 打下了正确前提。

---

## 五、改进建议

### 5.1 修复致命问题（必做）

```abap
* 1) 让查库结果真正进入 ALV 数据表：直接 INTO TABLE gt_mara
SELECT matnr, brgew
  FROM mara
  INTO TABLE gt_mara
  UP TO 10 ROWS.

IF gt_mara IS INITIAL.
  MESSAGE '未查到物料数据' TYPE 'S'.
  RETURN.
ENDIF.
```

```abap
* 2) 解引用前守卫引用
  go_grid->get_subtotals( IMPORTING ep_collect00 = gr_data ).

  IF gr_data IS BOUND.
    ASSIGN gr_data->* TO <gtr_sum_tab>.
    READ TABLE <gtr_sum_tab> ASSIGNING FIELD-SYMBOL(<l_sum>) INDEX 1.
    IF sy-subrc = 0 AND <l_sum> IS ASSIGNED.
      ASSIGN COMPONENT 'BRGEW' OF STRUCTURE <l_sum> TO FIELD-SYMBOL(<lg_val>).
      IF <lg_val> IS ASSIGNED.
        DATA(lv_sum) = REDUCE ty_sum WITH INIT lv_sum = <lg_val>
                       FOR <ls_t> IN gt_mara
                       NEXT   lv_sum = lv_sum + <ls_t>-brgew.
        <lg_val> = lv_sum.
      ENDIF.
    ENDIF.
  ENDIF.
```

```abap
* 3) 求和变量类型与目标字段对齐（不要引入 ntgew_15）
DATA lv_sum TYPE mara-brgew.     " 或 ztest_s-bgew：与写入目标同一类型
lv_sum = REDUCE mara-brgew WITH INIT lv_sum = lv_sum
             FOR <ls_t> IN gt_mara
             NEXT   lv_sum = lv_sum + <ls_t>-brgew.
```

### 5.2 结构统一（强烈建议）

消除"字段目录来自 `ZTEST_S`、数据来自 `MARA`"的双事实来源，二选一：

- **方案 A（推荐）**：本地显式类型 + 手工字段目录，不依赖 SE11 结构
  ```abap
  TYPES: BEGIN OF ty_mat,
           matnr TYPE mara-matnr,
           brgew TYPE mara-brgew,
         END OF ty_mat.
  DATA gt_mara TYPE STANDARD TABLE OF ty_mat WITH EMPTY KEY.
  ```
  字段目录仍可用 `REUSE_ALV_FIELDCATALOG_MERGE`（`i_structure_name = 'MARA'` 后 `DELETE` 掉多余列），或直接 `ls_fcat-no_out = 'X'`。
- **方案 B**：保留 `ZTEST_S`，但确保 `ZTEST_S-bgew` 的类型/长度/小数位与 `MARA-BRGEW` 完全一致。

### 5.3 健壮性加固

```abap
  READ TABLE gt_fieldcat ASSIGNING FIELD-SYMBOL(<gs_fcat>) WITH KEY fieldname = 'BRGEW'.
  IF sy-subrc <> 0.
    MESSAGE '字段目录中缺少 BRGEW，程序终止' TYPE 'E'.
    RETURN.
  ENDIF.
  <gs_fcat>-edit   = 'X'.
  <gs_fcat>-do_sum = 'X'.
```

```abap
  " 刷新异常别吞掉
  DATA(ls_refresh) = go_grid->refresh_table_display(
                        EXPORTING is_stable = gs_stable i_soft_refresh = 'X'
                        EXCEPTIONS finished = 1 OTHERS   = 2 ).
  IF sy-subrc = 2.
    MESSAGE 'ALV 刷新异常' TYPE 'S' DISPLAY LIKE 'W'.
  ENDIF.
```

查库加可复现条件，便于演示与测试：

```abap
  SELECT matnr, brgew FROM mara
    INTO TABLE gt_mara
    WHERE matnr LIKE 'Z%'
    ORDER BY matnr
    UP TO 10 ROWS.
```

### 5.4 简化：整段合计重算其实可删（进阶）

`GET_SUBTOTALS` + 两次 `ASSIGN` + `REDUCE` 覆盖，本质是**手工模拟 Grid 已经会做的事**。两条更短的路：

- **换事件类型**：把 `it_events` 里的 `DATA_CHANGED` 换成 Grid 的 `et_data_changed`（`CL_GUI_ALV_GRID=>et_data_changed`）。该事件下 Grid 会在回调返回后自动重算并刷新合计行，`GET_DATA_CHANGED` 只需做"回写内表"，第 85–97 行整段可删。
- **保留现事件但让 Grid 自算**：`DO_SUM = 'X'` 时 Grid 内部已有合计机制，`REFRESH_TABLE_DISPLAY` + `IS_STABLE` 会触发它重算；先做实验验证，若成立则可把 `GET_SUBTOTALS`/`REDUCE` 全部删除。

> 注意：这一步属于"减法优化"，需在真实环境实测确认合计行为后再删，不能凭代码推断。保留现实现是安全选择。

### 5.5 可选增强（面向"真报表"）

1. 加选择屏幕（`SELECT-OPTIONS matnr`），避免全表 `UP TO 10 ROWS`。
2. 加 `USER_COMMAND` 或工具栏自定义（`i_callback_toolbar_set`），提供"保存"入口，否则用户编辑后毫无归宿——要么落库/调 RFC，要么明确提示"仅演示，不保存"。
3. 加 `i_callback_data_changed_finish`（`finishing_edit`）在编辑结束时做一次落库/校验。
4. 把 `SET_PF_STATUS` 的 `CASE sy-ucomm` 真正用起来：`SAVE`、`CHECK`、自定义按钮。
5. 全面弃用 `TYPE-POOLS`，若要继续 OO 化，封装为 `CL_ZTEST7_ALV` + `ZCL_ALV_SUBMIT_TO_LSGRID`，把 `GO_GRID`、事件、合计逻辑收敛到类属性中，程序只剩取数与实例化。

---

## 六、重构后的骨架参考

```abap
REPORT ztest7.

TYPES: BEGIN OF ty_mat,
         matnr TYPE mara-matnr,
         brgew TYPE mara-brgew,
       END OF ty_mat.

DATA: gt_mara     TYPE STANDARD TABLE OF ty_mat WITH EMPTY KEY,
      gt_fieldcat TYPE slis_t_fieldcat_alv,
      gt_events   TYPE slis_t_event,
      go_grid     TYPE REF TO cl_gui_alv_grid,
      gs_stable   TYPE lvc_s_stbl,
      gr_data     TYPE REF TO data.

START-OF-SELECTION.

  SELECT matnr, brgew FROM mara
    INTO TABLE gt_mara
    WHERE matnr LIKE 'Z%'
    ORDER BY matnr
    UP TO 10 ROWS.

  IF gt_mara IS INITIAL.
    MESSAGE '未查到物料数据' TYPE 'S'.
    RETURN.
  ENDIF.

  CALL FUNCTION 'REUSE_ALV_FIELDCATALOG_MERGE'
    EXPORTING i_program_name   = sy-repid
              i_structure_name = 'MARA'
    CHANGING  ct_fieldcat      = gt_fieldcat
    EXCEPTIONS inconsistent_interface = 1
               program_error          = 2
               OTHERS                 = 3.

  IF sy-subrc <> 0.
    MESSAGE '生成字段目录失败' TYPE 'E'.
    RETURN.
  ENDIF.

  LOOP AT gt_fieldcat ASSIGNING FIELD-SYMBOL(<fcat>).
    <fcat>-no_out  = 'X'.
    <fcat>-edit    = ' '.
    <fcat>-do_sum  = ' '.
  ENDLOOP.

  READ TABLE gt_fieldcat ASSIGNING FIELD-SYMBOL(<fcat>) WITH KEY fieldname = 'BRGEW'.
  IF sy-subrc <> 0.
    MESSAGE '字段目录缺少 BRGEW' TYPE 'E'.
    RETURN.
  ENDIF.
  <fcat>-edit   = 'X'.
  <fcat>-do_sum = 'X'.

  gt_events = VALUE #( ( name = 'DATA_CHANGED' form = 'GET_DATA_CHANGED' ) ).

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING i_callback_program       = sy-repid
              it_fieldcat              = gt_fieldcat
              it_events                = gt_events
              i_callback_pf_status_set = 'SET_PF_STATUS'
    TABLES     t_outtab                 = gt_mara.

FORM set_pf_status USING itr_extab TYPE slis_t_extab.
  CALL FUNCTION 'GET_GLOBALS_FROM_SLVC_FULLSCR' IMPORTING e_grid = go_grid.
  IF go_grid IS BOUND.
    go_grid->register_edit_event( EXPORTING i_event_id = cl_gui_alv_grid=>mc_evt_modified ).
    go_grid->register_edit_event( EXPORTING i_event_id = cl_gui_alv_grid=>mc_evt_enter ).
  ENDIF.
  CASE sy-ucomm.
    WHEN OTHERS.
  ENDCASE.
ENDFORM.

FORM get_data_changed USING io_data_changed TYPE REF TO cl_alv_changed_data_protocol.

  DATA lv_sum TYPE mara-brgew.

  IF go_grid IS BOUND.

    LOOP AT io_data_changed->mt_mod_cells ASSIGNING FIELD-SYMBOL(<cell>)
         WHERE fieldname = 'BRGEW'.
      READ TABLE gt_mara ASSIGNING FIELD-SYMBOL(<row>) INDEX <cell>-row_id.
      IF sy-subrc = 0.
        <row>-brgew = <cell>-value.
      ENDIF.
    ENDLOOP.

    go_grid->get_subtotals( IMPORTING ep_collect00 = gr_data ).

    IF gr_data IS BOUND.
      ASSIGN gr_data->* TO FIELD-SYMBOL(<sum_tab>).
      IF <sum_tab> IS ASSIGNED.
        READ TABLE <sum_tab> ASSIGNING FIELD-SYMBOL(<sum>) INDEX 1.
        IF sy-subrc = 0.
          ASSIGN COMPONENT 'BRGEW' OF STRUCTURE <sum> TO FIELD-SYMBOL(<val>).
          IF <val> IS ASSIGNED.
            lv_sum = REDUCE mara-brgew WITH INIT lv_sum = lv_sum
                       FOR <t> IN gt_mara
                       NEXT   lv_sum = lv_sum + <t>-brgew.
            <val> = lv_sum.
          ENDIF.
        ENDIF.
      ENDIF.
    ENDIF.

    gs_stable-col = 'X'.
    gs_stable-row = 'X'.

    go_grid->refresh_table_display( EXPORTING is_stable = gs_stable
                                             i_soft_refresh = 'X'
                                   EXCEPTIONS finished = 1 OTHERS = 2 ).
    IF sy-subrc = 2.
      MESSAGE 'ALV 刷新异常' TYPE 'S' DISPLAY LIKE 'W'.
    ENDIF.
  ENDIF.

ENDFORM.
```

---

## 七、一页总结

| 项目 | 评价 |
|---|---|
| 业务价值 | POC 级。演示"ALV 可编辑列 + 实时合计 + 稳定刷新"，本身不承载业务 |
| 架构合理性 | 三段式事件划分清晰，用的是 SAP 官方推荐路径；但全局状态 + 反射式写法偏脆弱 |
| 关键链路正确性 | 事件注册 ✅、`EDIT/DO_SUM` 标记 ✅、写回内表 ✅、`STABLE+SOFT_REFRESH` ✅ |
| 致命缺陷 | 查库写进未声明变量 `_mara`，`GT_MARA` 恒空 → **ALV 无数据**（`:15-18`） |
| 潜在崩溃 | `GR_DATA` 未绑定即解引用 → 短时转储（`:90`） |
| 类型隐患 | `ntgew_15` 与 `MARA-BRGEW` 不匹配，可能溢出/转换异常（`:95`） |
| 优先动作 | ① 改 `INTO TABLE gt_mara` ② 字段目录/数据结构统一 ③ `IS BOUND` 守卫 ④ 求和变量类型对齐 ⑤ 空结果给消息 |
| 是否可上线 | ❌ 不可。修复上述 3 个严重问题并补上"保存"入口后才具备实用价值 |