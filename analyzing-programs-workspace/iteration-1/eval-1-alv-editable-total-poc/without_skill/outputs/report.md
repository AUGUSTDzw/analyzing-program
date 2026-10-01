# ABAP 程序分析报告：`ztest7`

> 源文件：`ztest7.abap`（共 115 行）
> 报告语言：中文

---

## 1. 一句话概括

`ztest7` 是一个 **可编辑 ALV 网格 + 手动重算合计行的概念验证（PoC）** 程序。它专门解决 SAP 标准 ALV 的一个著名缺陷：**当某列同时被设为可编辑（`edit`）且启用合计（`do_sum`）时，用户在网格里修改单元格后，底部「合计」行不会自动随编辑结果更新**——它只反映程序加载时的原始值。本程序通过捕获 `DATA_CHANGED` 事件、直接改写 ALV 网格内部的「总计缓冲区」来强行刷新合计。

目录名 `eval-1-alv-editable-total-poc` 中的 "poc" 即"概念验证"，说明这是一个**演示性 / 探索性**程序，而非生产事务代码。

---

## 2. 业务目的（解决什么问题）

### 2.1 真实痛点

SAP 的 `REUSE_ALV_GRID_DISPLAY`（以及面向对象的 `cl_gui_alv_grid`）有一个长期存在的行为限制：

- 如果某字段列字段目录（field catalog）里同时设置了 `edit = 'X'`（可编辑）与 `do_sum = 'X'`（参与合计），
- 那么在用户编辑该列某个单元格之后，**底部的「合计」单元不会重新计算**，依然显示旧值的合计。
- 原因是合计行属于 ALV 内部的"汇总集合（collect）"，编辑事件触发后只会把新值写回输出内表，并不会触发 ALV 的合计重算逻辑。

### 2.2 程序的目标

在 `MARA` 物料主数据里取出最多 10 条物料的 `MATNR`（物料号）与 `BRGEW`（毛重），以 `BRGEW` 列为示例：

- 让 `BRGEW` 列既能编辑、又能合计；
- 当用户改了任一行的 `BRGEW` 后，**程序自己把新值累加并写回 ALV 的总计缓冲区**，使底部合计立刻反映新值；
- 刷新时保持行列位置稳定（用户视角的"原地更新"）。

典型应用场景：临时让用户在 ALV 上调数、做 What-if 试算、快速复核重量/金额合计等——需要一个"所见即所得"的合计行。

---

## 3. 整体架构设计

程序采用经典的 **过程式 ABAP + 函数池式 ALV** 架构，结构非常简单（单文件、无类、无模块池），由「数据声明 → 主流程 → 两个回调 FORM」三层组成：

```
┌──────────────────────────────────────────────────────────────┐
│  全局数据声明（DATA / FIELD-SYMBOLS / TYPE-POOLS）           │
│  - gt_mara      输出内表（基于 DDIC 结构 ZTEST_S）            │
│  - gt_fieldcat  字段目录                                       │
│  - gt_events   ALV 事件表                                     │
│  - go_grid     ALV 网格对象引用（cl_gui_alv_grid）            │
│  - gs_stable   刷新稳定性标记（保持行列）                      │
│  - gr_data     指向「总计缓冲区」的数据引用                    │
│  - <gtr_sum_tab> 字段符号，承载总计集合表                     │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  START-OF-SELECTION（主流程）                                 │
│   1. SELECT 从 MARA 取数                                      │
│   2. REUSE_ALV_FIELDCATALOG_MERGE 基于结构 ZTEST_S 构字段目录 │
│   3. 把 BRGEW 列标记为 edit + do_sum                          │
│   4. 注册 DATA_CHANGED 事件 → 回调 FORM 'GET_DATA_CHANGED'    │
│   5. REUSE_ALV_GRID_DISPLAY 显示网格                          │
│      └─ 设置 PF 状态回调 SET_PF_STATUS                          │
└──────────────────────────────────────────────────────────────┘
                              │
            ┌──────────────────┴───────────────────┐
            ▼                                       ▼
┌────────────────────────────┐   ┌──────────────────────────────────┐
│ FORM set_pf_status         │   │ FORM get_data_changed             │
│  - 取得 go_grid 对象引用    │   │  - 把编辑值回写 gt_mara            │
│  - 注册两个编辑事件：       │   │  - go_grid->get_subtotals          │
│    mc_evt_modified         │   │    取 ep_collect00（总计缓冲区）   │
│    mc_evt_enter            │   │  - 用 REDUCE 重算 BRGEW 总和        │
│  - 预留 PF 状态分发（空）    │   │  - 写回总计行的 BRGEW 组件          │
└────────────────────────────┘   │  - 软刷新（保持行列稳定）            │
                                  └──────────────────────────────────┘
```

### 3.1 设计要点

| 维度 | 选择 | 说明 |
|------|------|------|
| ALV 风格 | 函数式 `REUSE_ALV_GRID_DISPLAY`（基于 SLIS 类型组） | 而非 OO ALV（`cl_gui_alv_grid` 容器方式）。但仍需拿到内部 OO 对象引用来调底层方法。 |
| 字段目录来源 | DDIC 结构 `ZTEST_S` + `REUSE_ALV_FIELDCATALOG_MERGE` | 复用数据字典定义，减少手工维护字段目录。 |
| 编辑事件 | 同时注册 `mc_evt_modified`（失焦即触发）+ `mc_evt_enter`（按回车触发） | 双保险，无论用户用哪种交互方式都能捕获。 |
| 合计刷新 | 直接写 ALV 内部「总计缓冲区」`ep_collect00` | 这是**非官方/底层**手段，绕过 ALV 不重算合计的限制。 |
| 刷新策略 | `is_stable` 行列均 'X' + `i_soft_refresh = 'X'` | 软刷新，不触发排序/筛选，保持用户当前视图。 |

---

## 4. 执行流程（时序）

### 4.1 启动阶段

1. **`START-OF-SELECTION`** 触发。
2. `SELECT matnr, brgew FROM mara INTO TABLE _mara UP TO 10 ROWS.`
   - 取最多 10 条物料。
   - ⚠️ 注意：此处写的是 `_mara`，而声明的是 `gt_mara`（见第 4 行）。**这是一个疑似笔误 / 拼写错误**，按字面代码无法激活（详见 §7.1）。
3. `sy-subrc = 0` 时进入 ALV 构建逻辑。
4. 调 `REUSE_ALV_FIELDCATALOG_MERGE`，用程序名 `sy-repid` 与结构名 `'ZTEST_S'` 生成 `gt_fieldcat`。
5. `sy-subrc = 0` 后：
   - `READ TABLE gt_fieldcat` 找到字段名为 `BRGEW` 的行，用字段符号 `<gs_fcat>` 指向它；
   - 设 `<gs_fcat>-edit = 'X'`、`<gs_fcat>-do_sum = 'X'`——**这是触发后续一切行为的根因配置**。
6. 往 `gt_events` 追加一行：事件名 `DATA_CHANGED`，处理 FORM 名 `GET_DATA_CHANGED`。
7. 调 `REUSE_ALV_GRID_DISPLAY`：
   - 传入字段目录、事件表；
   - `i_callback_pf_status_set = 'SET_PF_STATUS'`，把 GUI 状态设置权交给我们的 FORM。

### 4.2 运行期（用户交互）

8. ALV 显示后，标准 ALV 会回调 `FORM set_pf_status`：
   - `GET_GLOBALS_FROM_SLVC_FULLSCR` 拿到当前屏幕上 ALV 的 OO 对象引用 `go_grid`；
   - `go_grid IS BOUND` 后：
     - `register_edit_event( mc_evt_modified )`——单元格失焦即视为"已修改"；
     - `register_edit_event( mc_evt_enter )`——按回车也视为"已修改"。
   - `CASE sy-ucomm` 目前只有 `WHEN OTHERS`，是预留的 PF 状态分发空壳（如自定义按钮）。
9. 用户在 `BRGEW` 单元格里输入新值并失焦 / 按回车 → ALV 触发 `DATA_CHANGED` 事件 → 调 `FORM get_data_changed`，传入参数 `io_data_changed`（类型 `cl_alv_changed_data_protocol`，承载改动协议）。

### 4.3 合计重算阶段（核心）

10. `go_grid IS BOUND` 判定通过后：
    - **第 1 步：把新值回写输出表。**
      `LOOP AT io_data_changed->mt_mod_cells` 中 `fieldname = 'BRGEW'` 的改动项；对每个改动 `<gs_changed>`，用 `row_id` 去 `gt_mara` 里定位行（`<gs_tab>`），把 `<gs_changed>-value` 写入 `<gs_tab>-brgew`。
    - **第 2 步：取出 ALV 的"总计缓冲区"。**
      `go_grid->get_subtotals( IMPORTING ep_collect00 = gr_data )`。
      `ep_collect00` 即 **"Overall Total / 总合计"集合**（与 `do_sum` 产生的底部合计行对应），是一个泛型数据引用。
    - **第 3 步：定位总计行内的 BRGEW 单元。**
      `ASSIGN gr_data->* TO <gtr_sum_tab>`（解引用为表）；`READ TABLE <gtr_sum_tab> INDEX 1` 取第 1 行（即总合计行）；`ASSIGN COMPONENT 'BRGEW' OF STRUCTURE <l_sum> TO <lg_val>` 拿到该单元的字段符号。
    - **第 4 步：手工重算合计。**
      用 `REDUCE` 遍历 `gt_mara`，把所有 `brgew` 累加进累加器 `lv_i`（类型 `ntgew_15`）：
      ```abap
      <lg_val> = REDUCE #(
        INIT lv_i TYPE ntgew_15
        FOR <ls_t> IN gt_mara
        NEXT lv_i = lv_i + <ls_t>-brgew ).
      ```
      把累加结果直接赋给 `<lg_val>`——**因为字段符号直接绑定到 ALV 总计缓冲区的内存，写入即生效**。
    - **第 5 步：稳定刷新。**
      设 `gs_stable-col = 'X'`、`gs_stable-row = 'X'`；
      调 `go_grid->refresh_table_display` 传 `is_stable = gs_stable`、`i_soft_refresh = 'X'`，让 ALV 把改写后的总计渲染出来，且不打乱用户当前的行列位置与排序/筛选状态。
11. 用户视觉上看到：底部合计行立刻变成了新值的合计。

---

## 5. 子程序（FORM）详解

### 5.1 `FORM set_pf_status` （第 51–72 行）

**职责：** 在 ALV 准备 GUI 状态时被回调，**关键副作用是借机拿到 OO 网格对象并注册编辑事件**。

| 步骤 | 代码 | 作用 |
|------|------|------|
| 取对象引用 | `GET_GLOBALS_FROM_SLVC_FULLSCR` → `go_grid` | 函数式 ALV 也能拿到内部的 `cl_gui_alv_grid` 实例 |
| 注册失焦事件 | `register_edit_event( mc_evt_modified )` | 单元格失焦 → 触发 `DATA_CHANGED` |
| 注册回车事件 | `register_edit_event( mc_evt_enter )` | 回车 → 触发 `DATA_CHANGED` |
| PF 状态分发 | `CASE sy-ucomm ... WHEN OTHERS` | 空壳，预留扩展自定义按钮 |

**注意：** 这里把"拿对象 + 注册事件"放在 PF 状态回调里，是因为此时屏幕对象已经实例化。这是函数式 ALV 中获取 OO 引用的常见做法。

### 5.2 `FORM get_data_changed` （第 74–115 行，核心）

**签名：**
```abap
FORM get_data_changed
  USING io_data_changed TYPE REF TO cl_alv_changed_data_protocol.
```
**入参** `io_data_changed` 是 ALV 改动协议对象，其 `mt_mod_cells` 是一个"改动单元格清单"表，每条含 `row_id`、`fieldname`、`value` 等。

**逻辑分四段：**

1. **回写输出表（第 78–83 行）**
   ```abap
   LOOP AT io_data_changed->mt_mod_cells ASSIGNING <gs_changed>
        WHERE fieldname = 'BRGEW'.
     READ TABLE gt_mara ASSIGNING <gs_tab> INDEX <gs_changed>-row_id.
     IF sy-subrc EQ 0.
       <gs_tab>-brgew = <gs_changed>-value.
     ENDIF.
   ENDLOOP.
   ```
   按 `row_id` 把新值写回 `gt_mara` 对应行——这是后续 `REDUCE` 能算出正确合计的前提。

2. **取总计缓冲区（第 85–88 行）**
   ```abap
   go_grid->get_subtotals(
     IMPORTING ep_collect00 = gr_data ).  " Overall Total
   ```
   `ep_collect00` 对应"总合计"集合（`ep_collect01..09` 则对应各级小计）。

3. **重写总计的 BRGEW 单元（第 90–97 行）**
   ```abap
   ASSIGN gr_data->* TO <gtr_sum_tab>.
   READ TABLE <gtr_sum_tab> ASSIGNING <l_sum> INDEX 1.   " 第 1 行 = 总合计行
   ASSIGN COMPONENT 'BRGEW' OF STRUCTURE <l_sum> TO <lg_val>.
   <lg_val> = REDUCE #( INIT lv_i TYPE ntgew_15
                       FOR <ls_t> IN gt_mara
                       NEXT lv_i = lv_i + <ls_t>-brgew ).
   ```
   - 这里**直接通过字段符号把累加结果写进 ALV 总计缓冲区的内存**——这是整个技巧的精髓。
   - `REDUCE` 构造式：累加器 `lv_i` 初值 0，遍历 `gt_mara` 每行把 `brgew` 累加上去。

4. **稳定刷新（第 99–109 行）**
   ```abap
   gs_stable-col = 'X'. gs_stable-row = 'X'.
   go_grid->refresh_table_display(
     EXPORTING is_stable      = gs_stable
               i_soft_refresh = 'X'
     EXCEPTIONS finished = 1 OTHERS = 2 ).
   ```
   - `is_stable`：刷新时保持当前光标行列位置。
   - `i_soft_refresh = 'X'`：软刷新，不重跑排序、筛选、过滤逻辑——这样合计行能"安静地"显示新值。
   - 异常分支为空（`IF sy-subrc <> 0. ENDFORM`），即出错也不处理。

---

## 6. 关键技术点小结

| # | 技术 | 在程序中的体现 |
|---|------|----------------|
| 1 | 函数式 ALV + 字段目录来自 DDIC 结构 | `REUSE_ALV_FIELDCATALOG_MERGE` + `ZTEST_S` |
| 2 | 可编辑 + 合计同时启用 | `<gs_fcat>-edit = 'X'` + `<gs_fcat>-do_sum = 'X'` |
| 3 | 函数式 ALV 中获取 OO 引用 | `GET_GLOBALS_FROM_SLVC_FULLSCR` → `go_grid` |
| 4 | 注册编辑事件 | `register_edit_event( mc_evt_modified / mc_evt_enter )` |
| 5 | 事件 FORM 回调注册 | `APPEND VALUE #( name='DATA_CHANGED' form='GET_DATA_CHANGED' ) TO gt_events` |
| 6 | 改动协议对象 | `cl_alv_changed_data_protocol` 的 `mt_mod_cells` |
| 7 | 取 ALV 内部总计缓冲区（非官方 API） | `go_grid->get_subtotals( ep_collect00 = … )` |
| 8 | 字段符号绑定到 ALV 内部内存并直写 | `ASSIGN gr_data->*` → `ASSIGN COMPONENT 'BRGEW'` → 赋值 |
| 9 | 构造式 `REDUCE` 求和 | `REDUCE #( INIT lv_i … FOR … NEXT … )` |
| 10 | 软刷新 + 稳定行列 | `refresh_table_display( is_stable … i_soft_refresh='X' )` |

---

## 7. 风险与隐患

### 7.1 ⚠️ 高危：源码疑似拼写错误（`_mara` vs `gt_mara`）

第 18 行：
```abap
SELECT matnr, brgew FROM mara INTO TABLE _mara UP TO 10 ROWS.
```
- 声明的是 `gt_mara`（第 4 行），但此处写 `_mara`。
- `_mara` 未声明，**按字面代码无法通过语法检查（激活失败）**。
- 合理推断：这是从原始环境复制时的笔误 / 编辑器残影；正确写法应为 `INTO TABLE gt_mara`。
- **如真要运行此 PoC，必须先修正此处。**

### 7.2 依赖 ALV 内部 / 非公开 API

- `get_subtotals` 的 `ep_collect00` 是 `cl_gui_alv_grid` 较底层的接口，SAP 未在官方文档中明确保证其行为与稳定性。
- "总合计在第 1 行"是经验性结论：**当未定义小计（no subtotal）时**，`ep_collect00` 表的第 1 行即总合计。一旦将来加上排序 + 小计，行索引假设可能失效。
- 直接改写 ALV 内部缓冲区属于"绕路"行为，存在被 SAP 升级 / 补丁影响的风险。

### 7.3 只处理 BRGEW 一列

`get_data_changed` 只对 `fieldname = 'BRGEW'` 的改动做回写与重算。若以后再增加别的可编辑 + 合计列，本程序不会自动适配，需要为每列复制逻辑。

### 7.4 类型不完全一致

- `REDUCE` 累加器 `lv_i` 类型为 `ntgew_15`（净重数据元素，DEC），而被累加的 `brgew`（毛重）在 MARA 中是类型 `BRGEW`（QUAN）。两者都是数值，赋值兼容，但严格类型校验场景下可能告警。
- `<lg_val>` 通过 `ASSIGN COMPONENT` 得到，类型为泛型，赋值不做强校验。

### 7.5 异常处理薄弱

- `REUSE_ALV_FIELDCATALOG_MERGE`、`REUSE_ALV_GRID_DISPLAY` 的 `EXCEPTIONS` 只做了 `sy-subrc` 判断后嵌套继续，没有错误提示或回退。
- `refresh_table_display` 的 `EXCEPTIONS` 分支是空的 `IF sy-subrc <> 0. ENDIF.`，刷新失败时静默忽略。
- `GET_GLOBALS_FROM_SLVC_FULLSCR` 取 `go_grid` 失败时，靠 `IF go_grid IS BOUND` 静默跳过——不会报错但也不会刷新合计，问题不易察觉。

### 7.6 仅内存态、无持久化

- 改动只回写到 `gt_mara` 内表与 ALV 缓冲区，**不会写回 MARA 数据库**。这是 PoC 的合理选择，但如果被误当成"维护工具"使用会有歧义。

### 7.7 性能（数据规模）

- 每次 `DATA_CHANGED` 都对 `gt_mara` 整表 `REDUCE`，复杂度 O(n)。
- 本例 `UP TO 10 ROWS` 完全无压力；若扩展到上万行且频繁编辑，可能引入可感延迟，可考虑维护增量累加器代替全量重算。

### 7.8 字段符号 / 引用生命周期

- `<gtr_sum_tab>`、`<l_sum>`、`<lg_val>` 都依赖 `gr_data` 与 `go_grid` 仍有效。若 ALV 被销毁 / 重建，引用可能悬挂；好在 PoC 内不会发生。

### 7.9 PF 状态分发为空壳

- `CASE sy-ucomm ... WHEN OTHERS` 无任何分支，等于没有自定义按钮逻辑。若期望"保存到 DB""撤销""导出"等按钮，需要补 `WHEN` 分支 + 自定义 `PF-STATUS`（`SET PF_STATUS` 实际未在本程序里 `SET PF-STATUS`，只命名了回调）。

### 7.10 硬编码耦合

- 结构名 `'ZTEST_S'`、字段名 `'BRGEW'`、表 `MARA`、取数 `UP TO 10 ROWS` 等均写死。换字段 / 换结构 / 换数据源都要改代码，复用性低（PoC 可接受）。

### 7.11 双编辑事件可能重复触发

- `mc_evt_modified` 与 `mc_evt_enter` 在某些交互序列下可能**同一改动触发两次** `DATA_CHANGED`。逻辑幂等（每次都按当前 `gt_mara` 全量重算），结果一致，但会有重复刷新开销。

---

## 8. 改进建议（若要生产化）

1. **修正 `_mara` → `gt_mara`**（§7.1），确保程序可激活。
2. 把字段名、结构名、取数上限参数化（`PARAMETERS` / `SELECTION-SCREEN`），或抽出为常量。
3. 把合计重算逻辑泛化为"对每个 `do_sum = 'X'` 且 `edit = 'X'` 的列"，遍历字段目录动态处理。
4. 增加日志 / `MESSAGE` 提示：`get_subtotals` 取不到、`go_grid` 未绑定时给出可见警告。
5. 对大表使用增量累加：维护一个旧值快照，编辑时 `新合计 = 旧合计 - 旧值 + 新值`，O(1) 更新。
6. 用面向对象 ALV（`cl_gui_alv_grid` + 自定义容器 + `DATA_CHANGED_FINISHED` 事件）替代函数式 ALV，可更稳健地持有对象引用，避免 `GET_GLOBALS_FROM_SLVC_FULLSCR` 这类"取全局"技巧。
7. 给 `refresh_table_display` 异常分支加 `MESSAGE` 或日志。
8. 若需要持久化，在 PF 状态里加"保存"按钮 + `WHEN` 分支 + `UPDATE mara` / BAPI 调用与错误回滚。
9. 文档化"直接改写 `ep_collect00`"的脆弱性，升级 SAP Basis 时回归测试。

---

## 9. 结论

`ztest7` 是一份**针对"SAP ALV 可编辑列合计不随编辑刷新"这一已知缺陷的概念验证程序**：

- **业务目的：** 在可编辑 ALV 上，让 `BRGEW`（毛重）的合计行能实时反映用户编辑后的新总和。
- **架构：** 经典函数式 ALV + 两个回调 FORM；通过 `GET_GLOBALS_FROM_SLVC_FULLSCR` 取 OO 网格对象、注册编辑事件，再在 `DATA_CHANGED` 回调里**直接改写 ALV 内部总计缓冲区 `ep_collect00` 并软刷新**——这是程序最关键、也最"野路子"的一步。
- **价值：** 思路清晰、可作为同类需求的模板；演示了对 ALV 内部机制较深入的把控。
- **风险：** 含一处疑似拼写错误导致无法直接激活；依赖 ALV 非公开内部缓冲区；只覆盖单列、无持久化、异常处理薄弱；适合作为 PoC / 学习样例，离生产化仍有距离。

**一句话总结：** 一个"用脏内存直写 + 软刷新"绕过 ALV 合计不重算限制的可编辑 ALV PoC，思路巧妙但工程鲁棒性不足。
