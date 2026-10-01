# ABAP 程序分析报告：`ztest7` — 可编辑 ALV + 自定义合计行（POC）

> 分析对象：`D:\Workspace\Skills\analyzing-programs\evals\ztest7.abap`（115 行，`REPORT`）
> 分析视角：业务问题 / 整体架构 / 执行流程 / 分组逐段讲解 / 问题清单 / 改进建议
> 结论一句话：**它想解决「用户在可编辑 ALV 里改数量后，合计行不按我期望的值刷新」的问题，方案是绕过 ALV 自带汇总、直接篡改框架内部的合计对象——思路对，但代码在主链路上已经断了（查出来的数据从未赋给 ALV），当前状态下程序只能显示一个空网格。**

---

## 0. 速览（TL;DR）

| 维度 | 判断 |
|---|---|
| 业务属性 | **技术 POC / 演示程序**，不是可交付的业务功能（无落库、无授权、无消息、无 F4、无标题） |
| 技术栈 | SLIS（`TYPE-POOLS: slis` + `REUSE_ALV_*` FM + `FORM` 回调）× `CL_GUI_ALV_GRID` OO 控件，**混合体** |
| 核心技巧 | `GET_SUBTOTALS` → 就地改写合计对象 → `REFRESH_TABLE_DISPLAY(stbl + soft_refresh)`，即"**自己算合计，冒充成框架算的**" |
| 可运行性 | 编译大概率通过，但**功能不可用**：`SELECT` 结果进 `_mara`，从未赋给 `gt_mara`（P0） |
| 维护性 | 低。框架私有内存写入 + 未文档化行为依赖 + 6 处静默失败路径 |
| 现代化程度 | 需要重写为 OO ALV；建议保留思路，替换实现 |

**五条最关键结论**

1. **`ztest7.abap:18` 与 `:46` 之间断了链**：`SELECT ... INTO TABLE _mara` 的结果被丢弃，`TABLES t_outtab = gt_mara` 拿到的是初始空表 → 网格空白、`DATA_CHANGED` 永不触发、`REDUCE` 恒为 0。整个后半段是死代码。
2. **合计值是写进框架私有对象的**（`ztest7.abap:85-96`）。这条路径**没有 SAP 文档背书**，且强依赖"ALV 自己算出的 collect 行里恰好有一个名为 `BRGEW` 的分量"。
3. **`SET_PF_STATUS` 里的 `CASE sy-ucomm`（`:68-71`）逻辑上不可能正确**：PF-STATUS 回调阶段 `sy-ucomm` 还是上一次的命令值，读取用户命令必须走 `USER_COMMAND` 事件。
4. **`GET_SUBTOTALS` 的调用形态需要在自己的系统里核实**（参数名 `ep_collect00`、以及是否必须传 `it_subtotals`），见第 9 节。这一处决定了"就地改写"这条路是否在语法/语义上成立。
5. **汇总口径是"全量 REDUCE"，与 ALV 的筛选状态无关** → 一旦用户用了筛选，屏幕合计行会与用户预期（筛选后小计）不一致，属于业务口径错误，不是显示问题。

---

## 1. 程序要解决什么问题

### 1.1 从代码反推出的真实诉求

代码里没有一句注释说明业务场景（只有 `Overall Total`、`With Stable Rows/Columns`、`Without Sort, Filter, etc.` 三条英文注释）。但从"**为什么需要在 `DATA_CHANGED` 里手工重算合计**"这个反常动作，可以反推出作者面对的具体问题：

> 在 `REUSE_ALV_GRID_DISPLAY` 全屏网格上，用户直接编辑 `BRGEW`（毛重，NTGEW_15）这一列，ALV 顶部的合计行没有按"用户改完之后的数据"正确刷新。

这类诉求在真实项目里有四种常见来源，本程序最可能命中的是第 2 和第 4 种：

| 可能动因 | 描述 | 与本代码的吻合度 |
|---|---|---|
| A. 汇总口径包含非本行字段 | 总计需要按额外维度（工厂、批次）折算后汇总，ALV 的 `DO_SUM` 做不到 | 低（代码里没有任何维度线索） |
| B. 已知 ALV 合计刷新缺陷 | 编辑单元格后合计滞留旧值，需手动干预（SAP 有多条相关 note，历史上 `DATA_CHANGED` + `SET_SUBTOTALS` 是官方 workaround） | **高**（这正是本代码做的事） |
| C. 需要"含汇率/含税"的自定义合计 | 合计 = 各行按业务规则折算后的加总 | 低（代码只是裸 `+`） |
| D. 合计要覆盖框架算错的值 | 框架因 `NO_SUM`/排序/汇总定义问题给出错误合计，作者直接改写框架结果 | **高**（改写 `ep_collect00` 而不是"重新配置汇总定义"，说明是要覆盖而不是补齐） |

### 1.2 需求还原成一句技术规格

> 给一个通过 `ZTEST_S` 生成的字段目录的 ALV 网格，把 `BRGEW` 设为可编辑 + 可汇总；用户每次修改单元格后，把改动值回写到内表，重新对全表求和，并把该和**写回 ALV 的合计行**；为了让合计变化不引起行跳动，刷新时带 `STBL_ROW/STBL_COL`。

### 1.3 这是 POC 还是业务功能？

从下面 6 个特征可以确定是 POC：

- `SELECT ... FROM mara` **没有任何 `WHERE` 条件** + `UP TO 10 ROWS`：数据是随手抓的 10 行物料，不构成业务查询。
- **没有任何数据库写入**：用户改的毛重只存在于内存，退出即丢。如果这是"维护毛重"的业务程序，缺 `UPDATE mara`；如果它**本来就不是**要落库，那它就是一个纯 UI 技术验证。
- 没有 `MESSAGE`、没有标题、没有变式保存（`it_save_layout`）、没有 `USER_COMMAND`、没有 `USER_F1`。
- 没有权限校验（`AUTHORITY-CHECK`），而 `BRGEW` 是物料主数据字段（毛重属于需要变更凭证管控的字段）。
- 写框架私有内存这种"手法"，在可交付代码里过不了 Code Review。
- 没有单元测试、没有示例注释里的业务上下文。

**结论：**它的价值是"证明了『ALV 合计行可以被程序自己接管』这条路在技术上是通的"，而不是业务价值。

---

## 2. 对象与数据模型

### 2.1 全局声明逐项解读（`ztest7.abap:1-11`）

```abap
REPORT ztest7.
TYPE-POOLS: slis.

DATA: gt_mara     TYPE TABLE OF ztest_s,
      gt_fieldcat TYPE slis_t_fieldcat_alv,
      gt_events   TYPE slis_t_event,
      go_grid     TYPE REF TO cl_gui_alv_grid,
      gs_stable   TYPE lvc_s_stbl,
      gr_data     TYPE REF TO data.

FIELD-SYMBOLS: <gtr_sum_tab> TYPE table.
```

| 符号 | 类型 | 真实角色 | 备注 |
|---|---|---|---|
| `gt_mara` | `TABLE OF ztest_s` | ALV 的**唯一数据源**（`T_OUTTAB`） | **命名与类型严重不符**：叫 `mara` 却是 `ZTEST_S` 类型；且从未被填充（见 P0-1） |
| `gt_fieldcat` | `slis_t_fieldcat_alv` | 由 FM 从 DDIC 结构 `ZTEST_S` 生成，再手工改 `EDIT`/`DO_SUM` | 由 FM 生成后又被手工改造，生成时就该带 `REF_TABLE`/变式 |
| `gt_events` | `slis_t_event` | 事件注册表，只放了 `DATA_CHANGED` | 缺 `USER_COMMAND`，缺 `TOOLBAR`/`USER_COMMAND` 扩展位 |
| `go_grid` | `REF TO cl_gui_alv_grid` | 回调上下文里抓到的网格对象引用 | 存在全局，回调内重复抓取会覆盖；`FORM` 之间靠全局通信是老式写法 |
| `gs_stable` | `lvc_s_stbl` | 刷新时的"稳定行列"参数 | 复用全局，避免每次构造 |
| `gr_data` | `REF TO data` | ALV **合计对象**的无类型句柄 | `REF TO data` 正确（要接未声明类型的导出参数），但没有 `IS BOUND` 保护 |
| `<gtr_sum_tab>` | `TYPE table` | 泛型表字段符号，承接 `GR_DATA->*` | 类型信息全丢，后续只能靠 `ASSIGN COMPONENT` 摸黑 |

### 2.2 数据流（现状 = 断裂）

```text
        MARA (DB)
          │
          │  SELECT matnr, brgew  UP TO 10 ROWS
          ▼
      ┌───────────┐                                  ┌──────────────────────┐
      │  _mara    │  ← 结果落在这里                 │      gt_mara         │
      │ (隐式声明) │                                  │  (TYPE TABLE OF      │
      └─────┬─────┘                                  │   ztest_s，初始为空) │
            │                                         └──────────┬───────────┘
            ✖ 断链：没有 MOVE / CORRESPONDING                  │ T_OUTTAB
            （源码里不存在 gt_mara = _mara）                  ▼
                                                   ┌──────────────────────┐
                                                   │  FULLSCREEN GRID     │
                                                   │  BRGEW 可编辑+合计   │
                                                   └──────────┬───────────┘
                                                              │ DATA_CHANGED
                                                              ▼
   MARA 表 ──────────────────────────► REDUCE 求和 ──► 改写 ep_collect00 ──► refresh
   （与用户改动后的 gt_mara 无关）      （永远 = 0）    （永远进不去）
```

**这个图就是本程序最要紧的一张图。**现状下：`_mara` 有 10 行、`gt_mara` 有 0 行、合计恒为 0、无单元格可编辑、回调永不触发。

### 2.3 数据类型链的一致性风险

`MARA-BRGEW` 是 `NTGEW_15`（15 位、3 位小数）。`ZTEST_S` 是自定义结构，**其 `BRGEW` 的类型不由本程序控制**：

- 若 `ZTEST_S-BRGEW` 也是 `NTGEW_15` → 一切自洽；
- 若是 `C`/`CHAR` → 网格输入校验、`DO_SUM` 汇总、`:95` 的 `REDUCE`（`lv_i TYPE ntgew_15`）三处类型都会打架；
- 若是 `CURR` → **跨物料、跨币种/计量单位求和 = 业务事故**（毛重在物料主数据里按基本计量单位维护，混加需要先归一）。

这是必须找业务确认的第一件事：**`ZTEST_S-BRGEW` 到底是什么类型、和 `MARA-BRGEW` 是否同义**。

---

## 3. 整体架构

### 3.1 技术栈定位：SLIS × OO 的"半吊子"混合

```text
┌────────────────────────────────────────────────────────────────┐
│  程序形态：REPORT（过程式） + TYPE-POOLS: slis                 │
│  报表层  ：REUSE_ALV_FIELDCATALOG_MERGE（DDIC→字段目录）        │
│  展示层  ：REUSE_ALV_GRID_DISPLAY（SLIS FM 门面，内部是        │
│            CL_GUI_ALV_GRID 全屏控件）                            │
│  事件层  ：FORM 回调（SLIS 风格）  ←→  OO 方法（Grid 风格）    │
│  数据层  ：全局内表 + 全局字段符号                                │
└────────────────────────────────────────────────────────────────┘
```

这种混合是**允许且常见的过渡写法**：SLIS 的 FM 门面负责"生成字段目录 + 建全屏网格 + 派发 `FORM` 回调"，一旦拿到 `go_grid` 就可以直接用 OO 控件的丰富能力（`REGISTER_EDIT_EVENT`、`GET_SUBTOTALS`、`REFRESH_TABLE_DISPLAY`、`LVC_S_STBL`）。SAP 官方 demo 里也这么干。

代价是**两套心智模型并存**：调试时你要同时知道"SLIS 派发回调的时机"和"Grid 的事件模型"；而且 `TYPE-POOLS: slis` 是 4.6 时代的技术表态，与代码里 7.50 的 inline `FIELD-SYMBOL(<...>)`、`REDUCE`、`VALUE #()` 并存，风格上自相矛盾。

### 3.2 分层

| 层 | 代码位置 | 职责 | 健康度 |
|---|---|---|---|
| L1 取数层 | `:15-18` | 抓 10 行 `MARA` 到 `_mara` | ❌ 结果未下游使用 |
| L2 元数据层 | `:20-35` | 由 `ZTEST_S` 生成字段目录，并把 `BRGEW` 标成可编辑+汇总 | ⚠️ 静默失败、缺变式维护 |
| L3 事件注册层 | `:37` | 注册 `DATA_CHANGED` | ⚠️ 事件名/形式待核实 |
| L4 展示层 | `:39-46` | 起全屏网格 | ⚠️ 无 `EXCEPTIONS`、无 `IT_SORT`/`I_GRID_TITLE` |
| L5 PF-STATUS 层 | `:51-72` | 抓 `go_grid`、注册编辑事件、（本想）处理用户命令 | ❌ `CASE sy-ucomm` 逻辑无效 |
| L6 变更处理层 | `:74-83` | 把 `mt_mod_cells` 的改动回写进 `gt_mara` | ⚠️ 按 `ROW_ID`→索引定位，脆弱 |
| L7 汇总干预层 | `:85-97` | 读框架合计对象 → 覆盖 `BRGEW` 分量 | ❌ 写入框架私有内存 |
| L8 重绘层 | `:99-109` | 稳定刷新，把新合计显示出来 | ⚠️ 异常被吞 |

### 3.3 回调/事件拓扑

```text
                 REUSE_ALV_GRID_DISPLAY
                          │
        ┌─────────────────┴──────────────────┐
        │                                    │
 (a) PF_STATUS_SET 回调               (b) 用户编辑单元格
   FORM set_pf_status                      │
        │                                    ▼
        ├─ GET_GLOBALS_FROM_SLVC_FULLSCR   mc_evt_modified / mc_evt_enter
        │   → go_grid                      （(a) 里注册的，不是 SLIS 事件）
        ├─ register_edit_event(MODIFIED)   │
        └─ register_edit_event(ENTER)      ▼
                                   DATA_CHANGED (SLIS 事件 (c))
        (c) IT_EVENTS 里的 'DATA_CHANGED'   │
        │                                    ▼
        │                     FORM get_data_changed
        │                       ├─ L6 回写 gt_mara
        │                       ├─ L7 get_subtotals → 改写 → 自己 REDUCE 求和
        │                       └─ L8 refresh_table_display(stbl, soft)
```

注意图中的**不对称**：`DATA_CHANGED` 是通过 **SLIS 事件表**（`it_events` + `FORM`）实现的，而"让单元格可编辑"是通过 **Grid 的 `REGISTER_EDIT_EVENT`** 实现的。两条不同的机制在同一个程序里协作，缺任何一条功能都不成立——这是本程序最需要写进注释的知识点。

### 3.4 为什么"这套写法能跑通"（机制补齐）

理解三个机制才算真正看懂这个程序：

1. **全屏网格的编辑能力必须显式开通**。`REUSE_ALV_GRID_DISPLAY` 拿到的 Grid 默认不响应键盘编辑事件，必须调用 `REGISTER_EDIT_EVENT`，且必须拿到 `go_grid` —— 而拿 `go_grid` 的官方入口就是 PF-STATUS 回调里的 `GET_GLOBALS_FROM_SLVC_FULLSCR`。所以 `:44` 传 `i_callback_pf_status_set = 'SET_PF_STATUS'` 不是"顺手加的"，**它是整个编辑功能的前置条件**。
2. **SLIS 的 `DATA_CHANGED` 不会自动回写你的内表**。事件参数 `io_data_changed` 里的 `mt_mod_cells` 只告诉你"第 N 行第 BRGEW 列变成了什么值"。你必须自己把它写回 `T_OUTTAB` 指向的表，然后 `REFRESH_TABLE_DISPLAY` 让网格重读。`:78-83` 就是干这个的。
3. **`IS_STABLE` + `I_SOFT_REFRESH` 是"刷新但不跳行"的正确组合**。改完单元格立刻整表刷新会让滚动位置和排序塌掉，用户体验极差；带 `STBL_ROW/STBL_COL` + `SOFT_REFRESH = 'X'` 可以保住位置。作者这里是对的。

---

## 4. 执行流程

### 4.1 主流程（Startup）

| # | 位置 | 动作 | 失败行为 |
|---|---|---|---|
| 1 | `:15-18` | `SELECT matnr brgew FROM mara INTO TABLE _mara UP TO 10 ROWS` | 无行时 `sy-subrc = 4` → 静默结束，屏幕空白无提示 |
| 2 | `:19` | `IF sy-subrc EQ 0` | 无 `ELSE` 分支，无消息 |
| 3 | `:20-29` | `REUSE_ALV_FIELDCATALOG_MERGE`，结构 `ZTEST_S`，程序 `sy-repid` | `OTHERS`（3）未区分，异常后无提示 |
| 4 | `:30-35` | 找 `BRGEW` 列，置 `EDIT = 'X'`、`DO_SUM = 'X'` | 找不到就静默跳过；用户看到不可编辑列却没有任何报错 |
| 5 | `:37` | 追加 `DATA_CHANGED` 事件 | 事件名/形式不匹配则运行时找不到 FORM |
| 6 | `:39-46` | `REUSE_ALV_GRID_DISPLAY` | **未声明 `EXCEPTIONS`**（如 `IT_DATA_INCONS`/`PROGRAM_ERROR`）→ 只能靠短 dump 看到 |
| 7 | `:51-52` | SLIS 派发 `SET_PF_STATUS` 回调 | — |
| 8 | `:54-56` | 抓 `go_grid` | 未取到时 `:57` 保护跳过 → 编辑功能静默失效 |
| 9 | `:58-64` | 注册 `MODIFIED` + `ENTER` 两个编辑事件 | 重复注册/双触发风险 |
| 10 | `:68-71` | `CASE sy-ucomm ... WHEN OTHERS`（第 69 行 `WHEN` 甚至被注释掉了） | 逻辑无效，空分支 |

### 4.2 交互流程（用户改一个 `BRGEW`）

```text
用户在某行 BRGEW 输入 12.345 并回车
   │
   ▼ Grid 派发 DATA_CHANGED → io_data_changed
   │
   ├─ LOOP mt_mod_cells WHERE fieldname = 'BRGEW'
   │     ├─ READ TABLE gt_mara INDEX row_id  →  <gs_tab>
   │     └─ <gs_tab>-brgew = <gs_changed>-value     ← 类型转换风险点
   │
   ├─ get_subtotals( ep_collect00 = gr_data )       ← 拿到框架算好的合计
   │     ASSIGN gr_data->* TO <gtr_sum_tab>
   │     READ TABLE <gtr_sum_tab> INDEX 1
   │     ASSIGN COMPONENT 'BRGEW' OF STRUCTURE <l_sum> TO <lg_val>
   │     <lg_val> = REDUCE ... FOR <ls_t> IN gt_mara NEXT ...   ← 自己算一遍
   │
   └─ refresh_table_display( stbl(row/col), soft )    ← 让新合计上屏
```

一个隐含但关键的**顺序假设**：编辑事件注册在 `SET_PF_STATUS`（第 7 步）里，而 `DATA_CHANGED` 的 SLIS 事件在第 5 步就登记了 —— 如果 `:44` 的 `i_callback_pf_status_set` 被删掉，**`DATA_CHANGED` 永远不会触发**，且没有任何编译期/运行期提示。这类"顺序耦合"必须注释化。

### 4.3 流程中的隐含假设（都未被验证）

1. 假设 `MARA` 的 10 行会到达 `gt_mara` —— **不成立**（P0-1）。
2. 假设 `ROW_ID` 等于 `gt_mara` 的行号 —— 在"ALV 直接排序同一张表"时成立；一旦引入 `IT_SORT`、服务端筛选、或改用 `CL_GUI_ALV_GRID` + `CL_ALV_TABLE_MODEL`，映射就可能失配。
3. 假设合计对象是**表**且第 1 行**有一个叫 `BRGEW` 的分量** —— 无任何 `IS ASSIGNED` 保护（`:90` 的 `ASSIGN` 无 `sy-subrc` 检查）。
4. 假设合计口径 = 全表求和 —— 与筛选/排序状态脱钩。
5. 假设框架不会在下一次重绘时重算合计覆盖注入值 —— **会在排序、筛选、切换页签、导出、返回后再进入时发生**。

---

## 5. 分段逐行讲解

### 5.1 全局声明（`:1-11`）

```abap
REPORT ztest7.
TYPE-POOLS: slis.
```

`:2` 的 `TYPE-POOLS: slis.` 让报表加载 SLIS 的类型池（`SLIS_T_FIELDCAT_ALV`、`SLIS_T_EVENT`、`SLIS_T_EXTAB` 等都来自 SAPLIS）。它**必须出现在所有声明之前**，本程序满足。它不带来任何能力，只是让 SLIS 的类型可用 —— 在纯 OO ALV 里这一行是完全不必要的。

`:4-11` 的声明有三个值得说的点：

- `gt_mara` 命名与类型不符（叫 `mara` 装 `ztest_s`），是后面所有理解偏差的源头。**命名应当反映"业务数据"而不是"来源表"**：`gt_matnr_data` / `gt_alv_data`。
- `gr_data TYPE REF TO data` 是**正确的类型选择**：接收一个类型未知的导出对象。用具体类型（比如 `zcl_collect=>ty_collect`）反而会引入耦合。
- `<gtr_sum_tab> TYPE table` 是泛型表 FS，**类型信息在这里被丢弃**，导致 `:93` 只能靠 `ASSIGN COMPONENT` 反射 + `IS ASSIGNED` 兜底。更稳的写法是给 ALV 合计行定义一个本地类型（见 8.4）。

### 5.2 `START-OF-SELECTION`（`:13-48`）

**`:15-18` 取数**

```abap
  SELECT matnr,
         brgew
    FROM mara
    INTO TABLE _mara UP TO 10 ROWS.
```

三个问题：

1. **结果被丢弃（P0）**。`_mara` 是通过 SQL 里的"下划线前缀隐式声明"创建的**局部**变量，它不在任何 `DATA:` 块里，也不会自动成为全局。后面 `:46` 的 `t_outtab = gt_mara` 用的是另一个变量。源码中不存在 `gt_mara = _mara`，也不存在 `CORRESPONDING`。**必须补一次赋值。**
2. **隐式声明本身是可读性隐患**。它在语法上合法（SQL 中以 `_` 开头且未声明的主机变量会隐式声明，类型由 select list 推导），但对读者是"魔法"。建议显式：
   ```abap
   DATA(lt_mara) TYPE STANDARD TABLE OF mara WITH EMPTY KEY.
   SELECT matnr brgew FROM mara INTO TABLE @lt_mara UP TO 10 ROWS.
   ```
3. **`UP TO 10 ROWS` 无 `ORDER BY` → 结果不确定**。同一个程序两次运行可能抓到不同的 10 行。POC 可接受，但要成为业务程序就必须有确定性排序或业务 `WHERE`。

**`:20-29` 生成字段目录**

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

- 正确之处：用 DDIC 结构生成字段目录，避免手写 `slis_t_fieldcat_alv`；把异常都列出来了。
- 缺失：
  - 没有 `i_main_program`，用户无法在 ALV 变式里维护列（保存/隐藏/顺序），而 `i_program_name` 又把变式挂在当前程序上 —— 组合别扭。
  - 没有 `no_program`，变式不可维护。
  - 没有 `i_texttype`/`slis_tab_typ` 等约束。
- `OTHERS = 3` 之后没有 `ELSEIF sy-subrc` 分派，也没有 `MESSAGE`，`inconsistent_interface` 与 `program_error` 完全等价 —— 三种失败模式对用户是同一种表现：**什么都没有**。

**`:31-35` 打上可编辑 + 汇总**

```abap
      READ TABLE gt_fieldcat ASSIGNING FIELD-SYMBOL(<gs_fcat>) WITH KEY fieldname = 'BRGEW'.
      IF sy-subrc EQ 0.
        <gs_fcat>-edit = 'X'.
        <gs_fcat>-do_sum = 'X'.
      ENDIF.
```

- inline `FIELD-SYMBOL` 需要 7.50 SP02+，OK。
- **只在成功时设置、失败时静默**，应补 `ELSE. MESSAGE ... TYPE 'E'.`
- 更根本的问题：**为什么不直接在 DDIC 里用 `CURRENCY`/汇总引用或直接在 FM 的变式里配好？** 因为 `DO_SUM` 只有在字段目录里带 `REF_TABLE`/变式信息时才与"总计行的显示位置、排序"配合正确。这里手改 `DO_SUM` 而不带 `SUBTOT` 定义，正是第 7 节里"合计行为不稳定"的根源之一。
- 字段名硬编码 `'BRGEW'` 出现 3 次（`:31`、`:78`、`:93`）。应提取为常量 `DATA gv_fld_brgew TYPE lvc_fname VALUE 'BRGEW'.`，改字段名只需改一处。

**`:37` 注册事件**

```abap
      APPEND VALUE #( name = 'DATA_CHANGED' form = 'GET_DATA_CHANGED' ) TO gt_events.
```

`DATA_CHANGED` 事件名正确。**但 `form =` 这个命名关联需要在系统内确认**：`SLIS_T_EVENT` 行的结构通常是 `SLIS_EVDATA`，其分量名为 `FORMNAME` 而非 `FORM`。若实际分量为 `FORMNAME`，本行会编译失败，应写 `formname = 'GET_DATA_CHANGED'`。请见第 9 节验证清单。

**`:39-46` 显示**

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

- `TABLES`（而不是 `TYPE ANY TABLE` 的 `it_outtab`）是 SLIS 风格，`t_outtab` 按引用传入，ALV 的排序/过滤直接作用在同一张表上 —— 这也是 `:79` 用 `INDEX` 对齐 `ROW_ID` 能成立的隐含前提。
- **`i_callback_pf_status_set` 是编辑功能的前置开关**，没有它就没有 `go_grid`、就没有编辑事件、没有 `DATA_CHANGED`。这一行承载了 `:54-64` 的全部意义。
- **缺少 `EXCEPTIONS`**：`REUSE_ALV_GRID_DISPLAY` 有 `IT_DATA_INCONS`、`IT_FIELDCAT_INCONS`、`IT_TABLENAME_MISS`、`IT_DABLIN_NOT_FOUND`、`PROGRAM_ERROR` 等异常。不声明意味着异常会走短 dump，用户看到"SAP short dump"而不是一句可读的 `MESSAGE`。
- 缺少 `i_grid_title`（屏幕标题栏空）、`i_default_layout`、`it_sort`、`i_callback_user_command`（标准 `BACK`/`EXIT`/`SAVE` 行为退化）。

### 5.3 `FORM set_pf_status`（`:51-72`）

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

- **定位 `go_grid` 的方式正确**：这是 SAP 文档给出的标准入口，且**必须在回调内调用**（放在外面会在 Grid 创建前执行）。
- `IF go_grid IS BOUND` 是必要保护，但**保护之后没有替代路径**（失败时应提示"编辑不可用"）。
- **`itr_extab` 未使用**：因为没有传 `i_callback_pf_status_extab`，该参数会是空表。这是 SLIS 的常见写法（很多程序直接 `FORM set_pf_status USING r_.. `）。更干净的做法是同时导出 `it_exclude` 复用 ALV 的排除菜单。
- **`REGISTER_EDIT_EVENT` 注册了 `MODIFIED` 和 `ENTER` 两个事件**：按 SAP 语义，注册 `ENTER` 后 `DATA_CHANGED` 只在用户按 Enter 时触发；两个都注册会造成**行为语义含糊 + 可能重复触发**（一次编辑既算 ENTER 又算 MODIFIED）。正常做法二选一：要"边输入边更新"用 `MODIFIED`；要"按回车才更新"用 `ENTER`。**POC 里两者混用，等于让每个单元格编辑走两遍 L7+L8。**
- **多次调用的风险**：`SET_PF_STATUS` 可能在 ALV 重建状态时被再次调用，重复注册会累积。虽然 `REGISTER_EDIT_EVENT` 是幂等的（覆盖而非追加），但重复的 `DATA_CHANGED` 处理开销是真实的。

```abap
  " PF Status Code
  CASE sy-ucomm.
*	WHEN
    WHEN OTHERS.
  ENDCASE.
```

- **这是本程序里最明确的一处逻辑错误**：PF-STATUS 设置阶段 `SY-UCOMM` 里是**上一个命令**（在标准列表场景下甚至常为空），**不可能**读到用户刚按的按钮。
- 正确做法二选一：
  ```abap
  " 方式一：注册 USER_COMMAND 事件读 sy-ucomm
  APPEND VALUE #( name = 'USER_COMMAND' form = 'HANDLE_USER_COMMAND' ) TO gt_events.

  FORM handle_user_command USING r_ucomm TYPE sy-ucomm r_sel1 TYPE lvc_row r_sel2 TYPE lvc_row.
    CASE r_ucomm.
      WHEN 'SAVE'  . ...
      WHEN 'DELETE'. ...
    ENDCASE.
  ENDFORM.

  " 方式二：在 set_pf_status 里用 r_ucomm（仅当同时导出 it_exclude 时可用）
  ```
- 第 69 行被注释掉的 `WHEN` 说明作者写到一半放弃了 —— 但**空分支没有留在正式代码里的理由**，要么删掉，要么补齐。

### 5.4 `FORM get_data_changed`（`:74-115`）

**`:78-83` 改动回写**

```abap
    LOOP AT io_data_changed->mt_mod_cells ASSIGNING FIELD-SYMBOL(<gs_changed>) WHERE fieldname = 'BRGEW'.
      READ TABLE gt_mara ASSIGNING FIELD-SYMBOL(<gs_tab>) INDEX <gs_changed>-row_id.
      IF sy-subrc EQ 0.
        <gs_tab>-brgew = <gs_changed>-value.
      ENDIF.
    ENDLOOP.
```

- **`WHERE fieldname = 'BRGEW'` 是必要的防御**：一次编辑可能影响多个单元格/多列，硬编码 `BRGEW` 让这段代码只为单列服务 —— 这正是"把通用 ALV 写成专用脚本"的痕迹。通用写法应遍历所有改动列并用 `ASSIGN COMPONENT`。
- **`READ TABLE ... INDEX <row_id>`**：
  - `ROW_ID` 是网格当前行号，与 `gt_mara` 行号的对应关系依赖"ALV 直接排序了同一张表"这一前提（POC 成立，复杂场景会失配）。
  - `READ TABLE` 默认线性查找，O(n)；正确写法是 `READ TABLE ... INDEX` 时无需 `BINARY SEARCH`（`INDEX` 本身是 O(1) 定位），此处**性能没问题**，但如果改成 `WITH KEY` 就必须加 `BINARY SEARCH`。
  - 更稳的定位方式：`READ TABLE gt_mara ASSIGNING <row> WITH KEY <key_fields>`（用 `mt_mod_cells` 提供的 `row_id` 不如用业务主键；Grid 还提供 `IT_FIELDS`/`MT_ROW_INFO` 之类的上下文，或用 `cl_alv_row_info` 由 `ROW_ID` 取行）。
- **`:81` 的赋值是隐性风险点**：`<gs_changed>-value` 是 `ANY`，源可能是 `C` 型字符串，目标 `BRGEW` 是数值型。如果输入了非法值（locale 下逗号/句点不一致、超长、小数位超限），ABAP 可能抛 `CX_SY_CONVERSION_NO_NUMBER`（无 handler → dump）。稳妥写法：
  ```abap
  DATA lv_val TYPE ztest_s-brgew.
  TRY.
      lv_val = <gs_changed>-value.
    CATCH cx_sy_conversion_no_number.
      io_data_changed->add_protocol_entry(
        i_msgid   = 'ZTEST7'
        i_msgno   = '001'
        i_msgty   = 'E'
        i_msgv1   = '必须输入数值'
        i_fieldname = <gs_changed>-fieldname
        i_row_id    = <gs_changed>-row_id ).
      RETURN.
  ENDTRY.
  ```
  同时这也是 ALV 推荐的**输入校验 + 协议回写**的标准姿势。

**`:85-97` 合计干预（核心技术点）**

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

逐层拆开：

1. `GET_SUBTOTALS` 把 ALV 自己算好的合计行对象导出。`ep_collect00` 对应**显示在网格顶部**的那条合计（`ep_collect01` 是底部）。
2. `ASSIGN gr_data->* TO <gtr_sum_tab>` —— **无 `sy-subrc` 检查**。如果 `gr_data` 未绑定（Grid 尚未产生合计，例如没有任何可汇总的行），解引用初始引用会抛 `CX_SY_REF_IS_INITIAL`（无 handler → 短 dump）；如果类型不是表，`ASSIGN` 失败而字段符号保持未绑定，下一句对未绑定 FS 的 `READ TABLE` 同样 dump。**这是全程序最脆弱的三行。**
3. `ASSIGN COMPONENT 'BRGEW' OF STRUCTURE <l_sum>` —— 反射式访问。**若合计行的分量名不是 `BRGEW`**（例如 FM 按字段目录的 `TECHNICAL_NAME` 生成，或结构里字段名大小写/带前缀差异），`ASSIGN` 不抛 dump，只是**静默不生效**：`IF <lg_val> IS ASSIGNED` 拦住后什么都不做 → **用户看到合计永远不更新，而且没有任何错误信息**。这种"静默失败"比 dump 更难排查。
4. `REDUCE` 求和：
   - `INIT lv_i TYPE ntgew_15` —— **选得很专业**。`MARA-BRGEW` 就是 `NTGEW_15`，累加器类型与业务字段一致，避免了 `I`（整数）截断和 `F`（浮点）舍入误差。这说明作者对数据类型是有意识的，值得肯定。
   - `FOR <ls_t> IN gt_mara` —— **口径问题**：这是**全表**求和，不受 ALV 筛选影响。如果 `ZTEST_S` 有工厂/批次维度，正确的合计应是"当前显示/筛选范围内求和"，而 ALV 天然支持这个语义（`do_sum` 会随筛选变化）。**所以这一行在"解决"问题的同时，制造了一个新的口径 bug。**
   - `<lg_val> = ...` 隐式类型转换，目标类型取决于合计行的 `BRGEW` 分量类型；若它比 `NTGEW_15` 窄（如 `MENGE` 13,3），可能溢出。
5. **本质**：这段代码是"**把框架的对象抢过来改内容**"。ABAP 里通过 `ASSIGN` 得到的字段符号指向的是**框架的原始数据内存**，所以写它 = 改框架的数据，随后 `REFRESH_TABLE_DISPLAY` 让框架把这个数据重新读一遍并渲染。因此技术上"生效"，但：
   - 依赖**未文档化**的内部结构（合计行字段名、行顺序、"对象是可写引用"）；
   - 违反"不写入框架内存"的工程原则；
   - **只在两次刷新之间有效**：用户一排序/筛选/翻页/导出，框架重算合计，注入值立刻被覆盖 → 合计行会"跳回"框架算法，前后不一致。
   - **官方合规的替代路径**是 `GET_SUBTOTALS`（**只读**，用于读取并在自绘标题栏显示合计）+ `SET_SUBTOTALS`（**写入**，用自己构造的 collect 结构回填），而不是就地改写返回对象。

**`:99-109` 刷新**

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
```

- `STBL_ROW/STBL_COL = 'X'`：保持行/列位置稳定，编辑后不跳行。**用法正确**，与"合计行在顶部、编辑任意行都要看到合计变化"的需求匹配。
- **`:105` 的注释是反的**：`I_SOFT_REFRESH = 'X'` 的语义是"**不重新**做排序/过滤/汇总的软刷新"，而不是注释说的 "Without Sort, Filter, etc."（容易被读成"刷新会丢掉排序过滤"）。软刷新正是为了**保留**当前排序与筛选。注释必须改，否则下一个维护者会做相反的决策。
- `finished`（显示被 Export 结束）被 `OTHERS` 一起吞掉：
  ```abap
    IF sy-subrc <> 0.
    ENDIF.
  ```
  **空异常处理**：`OTHERS` 意味着连 `cx_sy_no_handler`/接口错误都被静默。至少要区分：`finished` 正常忽略（但应 `LEAVE`/中断后续），其余 `MESSAGE` 提示或写日志。
- **性能**：每次按键（`MODIFIED`）都触发"全表 REDUCE + 整体刷新"。表大时（>10k 行）会明显卡顿/闪烁。正确做法：
  - 用 `ENTER` 而非 `MODIFIED`（减少触发次数）；
  - 维护"运行中合计"增量变量（改动一行只加减差值）；
  - 优先只更新合计（`SET_SUBTOTALS` + 局部刷新），确实需要才 `REFRESH_TABLE_DISPLAY`。

**`:113` 收尾**

```abap
  ENDIF.
ENDFORM.                    "get_data_changed
```

`IF go_grid IS BOUND` 的 `ENDIF` 与 `:76` 配对。结构正确，但**缺少 `ENDENDFORM` 前的注释说明 `ENDENDFORM "xxx` 风格的一致性**：`:72` 的 `ENDFORM.` 没有注释，`:115` 有。

---

## 6. 关键技术点深挖

### 6.1 编辑能力的三段式开通（必须记住）

```text
①  字段目录    →  EDIT = 'X'（本程序 :33）
②  编辑事件    →  REGISTER_EDIT_EVENT( MODIFIED / ENTER )（本程序 :58-64）
③  变更回调    →  DATA_CHANGED 事件 + FORM（本程序 :37 / :74）
④  回写 + 刷新 →  mt_mod_cells → 内表 → REFRESH（:78-109）
```

缺① → 单元格不接受输入；缺② → 输入了不产生事件；缺③ → 没有 FORM 可调；缺④ → 界面不回显。**本程序四步都写了，唯独数据没喂进去。**

### 6.2 `DATA_CHANGED` 的"单向通知"语义

`IO_DATA_CHANGED` 是**只读的通知载体**（外加协议回写），ALV **不会**替你更新 `T_OUTTAB`。这一"通知 ≠ 应用"的语义是本程序 `:78-83` 必须存在的根本原因，也是新手最常踩的坑（"我注册了 `DATA_CHANGED` 刷新了，为什么表格里还是旧值"）。

### 6.3 `GET_SUBTOTALS` 到底给了什么

| 项 | 说明 |
|---|---|
| 文档地位 | `GET_SUBTOTALS` 是文档化的方法，但**文档只保证"可以读取合计数据"**，不保证返回对象的可写性、字段构成或行顺序 |
| 结构构成 | 返回的是"合计行结构对象"（一种 collect 容器），其中含有与 ALV 字段目录对应技术名/字段名的分量 |
| 可写性 | 改写返回对象**有时**能生效（本程序押注在此），但框架可能在任意一次重绘时重新生成它 |
| 推荐用法 | 只读 + 在自绘标题/TOP_OF_PAGE 里显示自己算的合计；或用 `SET_SUBTOTALS` 明确回填 |
| `ep_collect00` vs `ep_collect01` | 前者是**顶部**合计（`T_OUTTAB` 之上的第一条合计行），后者是底部合计 |

### 6.4 类型选择：`NTGEW_15` 是本程序的技术亮点

`MARA-BRGEW : NTGEW_15`（数量类型，15 位、3 位小数）。作者在 `REDUCE` 里选 `INIT lv_i TYPE ntgew_15` 而不是 `TYPE i` 或默认整型，**避免了小数截断**，这在"重量求和"场景里是决定性的正确选择。多数人会随手写 `INIT lv_sum TYPE i`，那会把 `0.1+0.2` 变 `0`。

### 6.5 `TYPE-POOLS: slis` 的定位

- 作用：让 SLIS 类型/全局可用，是 SLIS 报表的标配。
- 代价：`(1)` 报表被绑死在 SAPLIS 体系；(2) 与 7.50 的 inline 声明、`REDUCE` 同框出现，风格割裂；(3) 纯 OO ALV 完全不需要它。

---

## 7. 问题清单（按严重度排序）

| 编号 | 严重度 | 位置 | 问题 | 后果 |
|---|---|---|---|---|
| P0-1 | **阻断** | `:18` ↔ `:46` | SELECT 结果在 `_mara`，从未赋给 `gt_mara` | **程序功能完全不可用**：空网格、无合计、无编辑、回调永不触发 |
| P0-2 | **阻断** | `:90-91` | `ASSIGN gr_data->*` 无 `IS BOUND`/`sy-subrc` 检查；对未绑定 FS 做 `READ TABLE` | 运行时 dump（`CX_SY_REF_IS_INITIAL` / 未绑定字段符号） |
| P1-1 | 高 | `:85-88` | `GET_SUBTOTALS` 参数名 `ep_collect00` 与是否需 `it_subtotals` 待确认；未处理异常 | 可能编译失败，或返回空 collect 导致 0-2 连锁失败 |
| P1-2 | 高 | `:85-96` | 写入框架私有内存合计对象 | 未文档化行为，升级/补丁后行为可能变化；注入值随时被重算覆盖 |
| P1-3 | 高 | `:95` | 合计口径 = 全表 `gt_mara` | 与筛选状态脱钩，筛选后合计错误（业务口径 bug） |
| P1-4 | 高 | `:68-71` | PF-STATUS 回调里读 `sy-ucomm` 判断用户命令 | 逻辑不成立，标准扩展点用错 |
| P1-5 | 高 | `:39-46` | `REUSE_ALV_GRID_DISPLAY` 无 `EXCEPTIONS` | 数据/字段目录不一致 → 短 dump，无可读提示 |
| P1-6 | 高 | `:4` | `gt_mara` 名为 `mara` 实为 `ztest_s` 类型；`_mara` 又隐式声明 | 三处数据源命名混乱，维护者极易改错 |
| P2-1 | 中 | `:31/78/93` | 字段名 `'BRGEW'` 硬编码 3 处 | 改名漏改；代码不可复用 |
| P2-2 | 中 | `:58-64` | 同时注册 `MODIFIED` 与 `ENTER` | `DATA_CHANGED` 可能重复触发 → 双倍 REDUCE + 双次刷新 |
| P2-3 | 中 | `:20-35` | FM 异常不分派、无 `MESSAGE`；找不到 `BRGEW` 静默跳过 | 三类失败对用户表现一致：无反应 |
| P2-4 | 中 | `:81` | `ANY → NTGEW_15` 隐式转换无保护、无协议回写 | 非法输入可能 dump；被拒绝的输入无反馈 |
| P2-5 | 中 | `:110-111` | 空 `IF sy-subrc <> 0. ENDIF.` | 吞掉 `OTHERS`，问题无法定位 |
| P2-6 | 中 | `:34` | 手工置 `DO_SUM` 但未配 `SUBTOT`/`REF_TABLE` | 合计行位置与刷新行为不稳定 |
| P2-7 | 中 | `:79` | `ROW_ID → INDEX` 映射无保护无注释 | 引入排序/筛选/新模型后静默错行 |
| P3-1 | 低 | `:105` | 注释语义写反（`i_soft_refresh`） | 误导后续维护者做反向决策 |
| P3-2 | 低 | `:69` | 被注释掉的 `WHEN` 残留在正式代码 | 死代码 |
| P3-3 | 低 | `:30` vs `:19` | `IF sy-subrc = 0` 与 `EQ 0` 混用 | 风格不一致（`sy-subrc` 是整型，应统一 `eq`/`IS INITIAL`） |
| P3-4 | 低 | `<gs_...>`/`<lg_...>`/`<l_...>` | 命名体系混杂（`<gs_changed>` 是 FS 却用结构体前缀） | 可读性下降 |
| P3-5 | 低 | 全局 | 无标题、无变式保存、无 `USER_COMMAND`、无 `BACK` 友好处理、无空数据提示 | 体验不完整 |
| P3-6 | 低 | `:2` + 7.50 inline 语法 | 4.6 技术姿态与新语法同框 | 风格割裂 |

**"静默失败"清单（最难查的一类）**：P1-1/P1-3 之外的 `:93` `ASSIGN COMPONENT` 失配、P2-3 的字段未找到、P2-7 的行错位 —— 这四处**都不会报错**，用户只会觉得"功能不好用"。建议在补 P0 之后，立刻给每一处加上 `MESSAGE` 或 `WRITE` 到状态栏。

---

## 8. 改进建议

### 8.1 第一步：让它真的能跑（P0 修复）

```abap
START-OF-SELECTION.

  DATA(lt_mara) TYPE STANDARD TABLE OF mara WITH EMPTY KEY.

  SELECT matnr brgew
    FROM mara
    INTO TABLE @lt_mara
    UP TO 10 ROWS
    ORDER BY matnr.                                " ← 确定性
  IF sy-subrc <> 0 OR lines( lt_mara ) = 0.
    MESSAGE '未查到物料数据' TYPE 'S'.
    RETURN.
  ENDIF.

  gt_mara = CORRESPONDING ztest_s( lt_mara ).        " ← 断链在此修复
```

同时给 `:90-96` 加保护：

```abap
    DATA(lv_sum) TYPE ztest_s.                      " 用真实类型替代反射
    ...
    IF gr_data IS BOUND.
      ASSIGN gr_data->* TO <gtr_sum_tab>.
      IF sy-subrc = 0 AND <gtr_sum_tab> IS ASSIGNED.
        READ TABLE <gtr_sum_tab> ASSIGNING FIELD-SYMBOL(<l_sum>) INDEX 1.
        IF sy-subrc = 0.
          ASSIGN COMPONENT lv_fld_brgew OF STRUCTURE <l_sum>
                 TO FIELD-SYMBOL(<lg_val>).
          IF <lg_val> IS ASSIGNED. ...
```

### 8.2 最小化加固清单（当天可做）

| 改动 | 位置 |
|---|---|
| 修数据断链 | `:18` 后加赋值（见 8.1） |
| `GR_DATA IS BOUND` + `ASSIGN` 后检查 `sy-subrc` + FS `IS ASSIGNED` | `:90-94` |
| FM 异常分派 + `MESSAGE` | `:30`、`:39` |
| 提取 `gv_fld_brgew` 常量，替换 3 处硬编码 | `:31/78/93` |
| 删掉 `CASE sy-ucomm` 空壳，改 `USER_COMMAND` | `:68-71`、`:37` |
| 编辑事件二选一（推荐 `ENTER` 或 `MODIFIED`） | `:58-64` |
| 非法输入用 `ADD_PROTOCOL_ENTRY` 回写 | `:81` |
| 区分 `finished` 与 `OTHERS`，后者至少 `MESSAGE`/日志 | `:110-111` |
| 修注释（`i_soft_refresh` 语义） | `:105` |
| 统一 `sy-subrc` 比较风格、清理注释掉的 `WHEN` | 全局 |

### 8.3 合计方案三选一（架构决策）

| 方案 | 做法 | 优点 | 缺点 | 适用 |
|---|---|---|---|---|
| **A. 官方只读（推荐）** | 不干预框架合计；自己算，写进 `TOP_OF_PAGE`/标题栏，或把合计行作为 `gt_mara` 的**第一条数据行**（并对该行置 `NO_SUM`/`EMPHASIZE`） | 完全合规、稳定、筛选口径正确、导出/打印一致 | 合计行不随排序浮动，需自己算筛选口径（可读 `GO_GRID->GET_FILTER` 或维护过滤信息） | **绝大多数场景** |
| **B. 显式 SET_SUBTOTALS** | 自己构造 collect 结构 → `SET_SUBTOTALS( ip_collect00 = ... )` | 使用文档化写入口 | 仍依赖 collect 结构形态与字段名 | 需要**框架自带的合计行**位置和交互 |
| **C. 现方案（就地改写）** | 保持 `:85-96` | 改动量最小 | 未文档化、易被覆盖、口径错 | **仅 PoC / 临时 workaround** |

> 如果业务真正需要的是"合计随筛选联动"，C 无论怎么修补都做不到 —— 因为 `:95` 求的是全表。此时只能走 A。

### 8.4 现代化重构版（OO ALV，本地类做事件接收者）

```abap
CLASS lcl_main DEFINITION FINAL.
  PUBLIC SECTION.
    INTERFACES if_salv_gui_c_changed_data_protocol.   " 或直接实现回调方法
  PRIVATE SECTION.
    DATA mo_grid  TYPE REF TO cl_gui_alv_grid.
    DATA mt_data  TYPE TABLE OF ztest_s.
    METHODS on_data_changed
      FOR callback_data_changed
      ON callback_data_changed TYPE REF TO cl_alv_changed_data_protocol.
    METHODS calc_total
      RETURNING VALUE(rv_total) TYPE ntgew_15.
ENDCLASS.

CLASS lcl_main IMPLEMENTATION.
  METHOD lcl_main#calc_total.
    DATA(lv) = REDUCE ntgew_15( INIT sum = CONV ntgew_15( 0 )
                                FOR <row> IN mt_data
                                NEXT sum = sum + <row>-brgew ).
    rv_total = lv.
  ENDMETHOD.

  METHOD lcl_main#on_data_changed.
    DATA lt_mod TYPE lvc_t_mod_cell.
    io_data_changed->get_mod_cells( IMPORTING et_mod_cells = lt_mod ).

    LOOP AT lt_mod ASSIGNING FIELD-SYMBOL(<mod>).
      ASSIGN COMPONENT <mod>-fieldname OF STRUCTURE ROW
             OF mt_data TO FIELD-SYMBOL(<val>).            " ROW：行对象
      IF sy-subrc = 0.
        TRY.
            <val> = <mod>-value.
          CATCH cx_sy_conversion_no_number.
            io_data_changed->add_protocol_entry( ... i_fieldname = <mod>-fieldname
                                                     i_row_id    = <mod>-row_id ).
        ENDTRY.
      ENDIF.
    ENDLOOP.

    mo_grid->set_subtotals( ip_collect00 = calc_total( ) ). " ← B 方案：文档化写入口
    mo_grid->refresh_table_display(
      EXPORTING is_stable = VALUE lvc_s_stbl( col = abap_true row = abap_true )
                    i_soft_refresh = abap_true ).
  ENDMETHOD.
ENDCLASS.
```

配合 `cl_gui_alv_grid` + `set_event_handler` 注册 `on_data_changed`，即可：

- 去掉 `TYPE-POOLS: slis`、`REUSE_ALV_*`、`FORM`、全局字段符号；
- 用 `cl_salv_gui_frontend_services` 直接拿到 `CL_GUI_ALV_GRID`；
- 合计口径可以用真实类型表达，不再靠 `ASSIGN COMPONENT` 摸黑；
- 输入校验 + 协议回写有标准姿势。

### 8.5 命名与风格（低成本高回报）

```text
gt_mara  → gt_alv_data        (反映角色，不反映来源表)
_mara    → lt_mara            (显式声明，去掉隐式魔法)
<gs_fcat> → <fcat>            (inline FS 不用结构体前缀)
<gs_changed> → <mod_cell>     (明确是协议行)
<lg_val> → <sum_value>
'BRGEW'  → gv_fld_brgew 常量
sy-subrc = 0 / EQ 0           → 统一 eq 0（或 IS INITIAL）
```

---

## 9. 需要在系统内确认的问题

以下 5 项无法仅凭源码判定，**必须**在你的 SAP 系统里查证，它们直接决定程序能否编译与行为是否正确：

| # | 待确认 | 查证方式 | 若结论为否 |
|---|---|---|---|
| 1 | `SLIS_T_EVENT` 行的分量名是 `FORM` 还是 `FORMNAME` | SE24 `SLIS_EVDATA`/`SLIS_EVENT` → F1；或 SE38 里对 `form =` 做语法检查 | `:37` 改为 `formname = 'GET_DATA_CHANGED'` |
| 2 | `CL_GUI_ALV_GRID->GET_SUBTOTALS` 的导出参数名与类型（`ep_collect00`? `et_collect00`? 是否 `REF TO data`?） | SE24 `CL_GUI_ALV_GRID` → `GET_SUBTOTALS` F1；查 SAP 示例代码 | 若为值参数（`et_collect00 TYPE ANY`），`:85-96` 的就地改写不成立，需改走 `SET_SUBTOTALS( ip_collect00 = ... )` |
| 3 | `GET_SUBTOTALS` 的 `it_subtotals` 是否必填 | 同上，看 `IT_SUBTOTALS TYPE lvc_t_sg_tl` 是否必传 | 未传则合计未定义，`ASSIGN`/`READ` 会落空 |
| 4 | `ZTEST_S-BRGEW` 的 DDIC 类型 | SE11 打开 `ZTEST_S` | 若是 `C`/`CHAR`/不同小数位 → `:95` 的累加器类型与 `:81` 的赋值都要改 |
| 5 | `MARA-BRGEW` 是否真的是 `NTGEW_15` | SE11 或 F1 on `MARA-BRGEW` | 若不是，累加器类型与"能否求和"都要重新评估（数量/币种/字符不可混加） |
| 6 | 目标 release 是否 ≥ 7.50（inline `FIELD-SYMBOL`、`REDUCE`、`VALUE #()`、`ASSIGN ... TO FIELD-SYMBOL`） | 系统版本 | 低于 7.50 需全部改写为显式声明 |

---

## 10. 测试与验证计划

修复 P0 之后，按下表走一遍。断点建议打在 `:18 / :31 / :37 / :54 / :78 / :85 / :90 / :93 / :95 / :102`。

| 用例 | 步骤 | 预期 | 对应风险 |
|---|---|---|---|
| TC-01 启动 | F8 运行 | 网格显示 10 行物料，`MATNR`/`BRGEW` 两列 | P0-1 |
| TC-02 合计初值 | 看顶部合计行 | 等于 10 行 `BRGEW` 之和 | P1-3 |
| TC-03 可编辑 | 双击 `BRGEW` 单元格 | 可输入（依赖 `:58-64` 注册成功） | 6.1 |
| TC-04 基本编辑 | 把某行改成 `12.345` 回车 | 该行显示新值，顶部合计同步变化，**不跳行** | P1-2 / P3-1 |
| TC-05 回写验证 | TC-04 后断点 `:81` 后查 `gt_mara` | 对应行 `brgew` 已更新 | 6.2 |
| TC-06 汇总一致性 | 连续改 3 个单元格 | 合计 = 三次增量后的全表和（不是框架算法值） | P1-2 |
| TC-07 筛选后合计 | 设一个筛选条件，再改单元格 | **观察**：合计是全量还是筛选后？（当前实现=全量，预期暴露口径 bug） | P1-3 |
| TC-08 排序稳定性 | 点列标题排序，再编辑 | 不 dump、不错行；合计是否被框架重算覆盖？ | P1-2 / P2-7 |
| TC-09 非法输入 | 输入 `abc` / `12,34` / 超 15 位 | 预期：被 ALV 拒绝并给出消息；实际可能 dump | P2-4 |
| TC-10 空数据 | 临时改成查不到数据的条件 | 预期：有明确 `MESSAGE`；实际：静默空屏 | P2-3 |
| TC-11 空表合计 | 让 `gt_mara` 为空后触发一次变更 | 是否在 `:90` dump？ | P0-2 |
| TC-12 导出 | 工具栏 → 导出 Excel | 是否走 `finished` 异常？导出值是否为注入后的合计？ | P2-5 |
| TC-13 重复回调 | 一次编辑后数 `DATA_CHANGED` 进入次数 | 应为 1；当前双事件注册可能为 2 | P2-2 |
| TC-14 字段改名 | 把 `ZTEST_S-BRGEW` 改名后运行 | 预期：常量一处改动即可；当前会静默失效 | P2-1 |

---

## 11. 给下一次迭代的输入

1. **先回答第 9 节的 6 个确认问题**，特别是 #2（`GET_SUBTOTALS` 参数形态）—— 它决定核心技术方案是否需要推翻重做。
2. **明确业务口径**：合计是"全量"还是"当前筛选范围"？这决定走 8.3 的 A 方案还是 C 方案。如果是筛选联动，**当前实现必须废弃**。
3. **明确程序定位**：POC（留在 demo 域、注明"框架行为实验"）还是要产品化（需要 `UPDATE` 落库 + `AUTHORITY-CHECK` + 变更凭证 + 消息与日志）。两者对代码的要求差距是数量级的。
4. **注意写入的持久性**：现状下用户编辑只存在于内存。若要落库，`BRGEW` 属于物料主数据字段，需走 `CALL FUNCTION 'BAPI_MATERIAL_SAVEGROUPS'` 或 `MODIFY mara ... IN DATABASE LTX`，并处理 `NO_MANUAL_INPUT` 之类的业务校验。

---

## 附录 A：符号 → 含义 → 行号速查

| 符号/语句 | 含义 | 行号 | 风险 |
|---|---|---|---|
| `TYPE-POOLS: slis` | 启用 SLIS 类型池 | 2 | 低 |
| `gt_mara` | ALV 数据源（`ztest_s` 表，**未填充**） | 4, 46 | **P0** |
| `gt_fieldcat` | 字段目录 | 5, 20-25 | — |
| `gt_events` | SLIS 事件表 | 6, 37 | 待确认 |
| `go_grid` | 全屏网格引用 | 7, 56-64, 76-109 | — |
| `gs_stable` | 刷新稳定参数 | 8, 99-109 | — |
| `gr_data` | 合计对象句柄 | 9, 87-90 | **P0** |
| `<gtr_sum_tab>` | 泛型表 FS | 11, 90-91 | **P0** |
| `_mara` | 隐式声明的取数结果（**废弃**） | 18 | **P0** |
| `i_structure_name = 'ZTEST_S'` | 字段目录来源 DDIC | 23 | 需确认类型 |
| `<gs_fcat>-edit / -do_sum` | 开启编辑与汇总 | 33-34 | P2-6 |
| `'DATA_CHANGED'` | 编辑事件注册 | 37 | 待确认 |
| `i_callback_pf_status_set` | **编辑能力前置开关** | 44 | — |
| `GET_GLOBALS_FROM_SLVC_FULLSCR` | 取 `go_grid` 的标准入口 | 54-56 | — |
| `register_edit_event` | 开通键盘编辑事件 | 58-64 | P2-2 |
| `CASE sy-ucomm` | PF-STATUS 阶段读用户命令（无效） | 68-71 | **P1-4** |
| `mt_mod_cells` | 变更单元格明细 | 78 | — |
| `ROW_ID → INDEX` | 行定位 | 79 | P2-7 |
| `get_subtotals` | 读框架合计对象 | 85-88 | **P1-1** |
| `ASSIGN COMPONENT 'BRGEW'` | 反射改写合计值 | 93 | **P1-2** |
| `REDUCE ... TYPE ntgew_15` | 自算合计（**类型选择正确**） | 95 | P1-3（口径） |
| `stbl row/col` + `soft_refresh` | 刷新不跳行 | 99-109 | P3-1（注释） |
| `finished`/`OTHERS` 空处理 | 吞异常 | 110-111 | P2-5 |

## 附录 B：一句话记住这个程序的"技术点"

> **可编辑 ALV 的四个开关**（`EDIT` → `REGISTER_EDIT_EVENT` → `DATA_CHANGED` → 回写+刷新）本程序都点齐了；
> 但**喂数据的管子没接**（`_mara` → `gt_mara` 断开），
> 而它试图证明的那个"技巧"（改写 `GET_SUBTOTALS` 返回对象）本身是**未文档化的框架内存写入**，
> 且它的合计口径（全表 `REDUCE`）与 ALV 的筛选语义天然冲突。
>
> **结论：作为 POC，它的思路值得记录；作为代码，它需要的是重构，而不是修补。**
