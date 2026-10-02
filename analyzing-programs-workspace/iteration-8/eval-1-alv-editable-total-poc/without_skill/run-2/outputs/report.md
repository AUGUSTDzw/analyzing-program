# ztest7 分析报告 —— ALV 可编辑合计行 POC

> 源文件：`ztest7.abap`（115 行，`REPORT`，非 OO、非 PERFORM 封装的经典报表程序）
> 依赖：`TYPE-POOLS: slis`（经典 ALV FM 层）+ `cl_gui_alv_grid` / `lvc_s_stbl`（OO 层）
> 数据来源：MARA（前 10 行），编辑目标结构：`ZTEST_S`

---

## 一、这程序解决什么问题

### 1.1 一句话结论

**这不是一个业务程序，是一条技术验证（POC）**。它要证明一件事：

> 在一个全屏 ALV Grid 上，让某个数值列"可直接编辑"，并且**在用户还没按保存、还没回写数据库时**，合计行就能跟着实时重算并刷新到屏幕上。

作者挑的验证场景是"物料毛重（BRGEW）"——一个天然带合计语义、又能被业务人员在表格里改数的字段，用来观察 ALV 编辑 + 合计联动的完整链路。

### 1.2 它实际想攻克的两个技术点

| # | 技术难点 | 程序的解法 | 位置 |
|---|---------|-----------|------|
| A | 如何捕获**单个单元格**的修改，而不是等整行回车？ | `DATA_CHANGED` 事件 + `it_data_changed->mt_mod_cells` | `get_data_changed` |
| B | 合计行如何不查 DB 就地重算并显示，且**光标不跳行**？ | `get_subtotals` + `REDUCE` 重算 + `is_stable` + `i_soft_refresh` | `get_data_changed` |

### 1.3 必须先说清楚的边界

代码里**没有任何写数据库的动作**。用户改掉的 BRGEW 只写回内存表 `gt_mara`，程序退出即丢失。

所以它证明的是**机制**，不是**业务事务**：
- ✅ 证明 ALV 可编辑、事件链路通、合计能重算、显示能刷新
- ❌ 没有校验、没有消息、没有持久化、没有权限、没有撤销

---

## 二、整体架构

### 2.1 分层视图

```
┌──────────────────────────────────────────────────────────────┐
│  L1  数据获取层   START-OF-SELECTION                          │
│      SELECT matnr, brgew FROM mara UP TO 10 ROWS → _mara     │
├──────────────────────────────────────────────────────────────┤
│  L2  描述层      REUSE_ALV_FIELDCATALOG_MERGE                │
│      反射本程序 SELECT 语句 + DDIC: ZTEST_S → gt_fieldcat     │
│      随后程序化改写 BRGEW 列属性: edit = 'X' / do_sum = 'X'   │
├──────────────────────────────────────────────────────────────┤
│  L3  装配层      REUSE_ALV_GRID_DISPLAY                       │
│      绑定 fieldcat / events / PF-STATUS 回调 / t_outtab       │
├──────────────────────────────────────────────────────────────┤
│  L4  控制层      FORM set_pf_status                           │
│      GET_GLOBALS_FROM_SLVC_FULLSCR → 拿到 go_grid             │
│      register_edit_event: mc_evt_modified / mc_evt_enter      │
│      (预留 sy-ucomm 的 CASE 分支，目前是空壳)                   │
├──────────────────────────────────────────────────────────────┤
│  L5  事件层      FORM get_data_changed                        │
│      ① 写回 gt_mara  ② 读 subtotals  ③ REDUCE 重算  ④ 刷新   │
├──────────────────────────────────────────────────────────────┤
│  L6  呈现一致性   gs_stable(row/col = 'X') + i_soft_refresh    │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 三个架构特征（决定了后面的问题清单）

**特征一：SLIS FM 门面 + OO 控件的"双层混血"**

界面通过函数模块 `REUSE_ALV_GRID_DISPLAY` 建立，但回调里立刻转成 OO 类操作（`go_grid->register_edit_event`、`go_grid->get_subtotals`、`go_grid->refresh_table_display`），并且引用了 `lvc_s_stbl`（OO 层结构）却声明了 `TYPE-POOLS: slis`（FM 层类型池）。

这是 SAP 现场代码里极常见的形态，也是维护上最容易踩坑的形态：同一个 ALV 有两套 API、两套事件语义、两套类型体系，必须同时在脑内维护。`GET_GLOBALS_FROM_SLVC_FULLSCR` 这个"反射拿引用"的技巧，正是双层架构必须付出的代价。

**特征二：全局变量充当共享状态（隐式单例）**

六个全局对象 `gt_mara / gt_fieldcat / gt_events / go_grid / gs_stable / gr_data` 全部跨过程共享。没有"传参"也没有"返回值"，所有子程序靠读写全局量通信。后果是——**任何一个 FORM 都无法脱离 `START-OF-SELECTION` 单独调用或测试**。

**特征三：类型擦除换来灵活性，失去编译期保护**

`FIELD-SYMBOLS <gtr_sum_tab> TYPE table` + `ASSIGN gr_data->*` + `ASSIGN COMPONENT` + `REDUCE #`，全链路都在绕开静态类型。好处是不用为"合计结构"单独声明一个 DDIC 类型；代价是——**几乎所有错误都会在运行时才炸，而且当前代码几乎没有 CATCHING 兜底**。

---

## 三、执行流程

```
程序启动
   │
   ├─► START-OF-SELECTION
   │     │
   │     ├─ [1] SELECT matnr, brgew FROM mara INTO TABLE _mara UP TO 10 ROWS
   │     │        └─ 注意：目标是 host variable _mara，不是 gt_mara  ⚠️
   │     │
   │     ├─ [2] IF sy-subrc = 0
   │     │     │
   │     │     ├─ [3] REUSE_ALV_FIELDCATALOG_MERGE
   │     │     │       i_program_name = 'ZTEST7', i_structure_name = 'ZTEST_S'
   │     │     │       → gt_fieldcat（含 matnr / brgew 两列）
   │     │     │
   │     │     ├─ [4] READ TABLE gt_fieldcat ASSIGNING <gs_fcat> KEY fieldname='BRGEW'
   │     │     │       └─ 找到 → edit = 'X', do_sum = 'X'   ← 打开可编辑 + 可合计
   │     │     │
   │     │     ├─ [5] APPEND DATA_CHANGED → gt_events
   │     │     │
   │     │     └─ [6] REUSE_ALV_GRID_DISPLAY
   │     │            i_callback_pf_status_set = 'SET_PF_STATUS'
   │     │            t_outtab = gt_mara                     ⚠️ 空表
   │     │
   │     └─ ALV 进入全屏显示 ──► 触发 set_pf_status（仅一次）
   │              ├─ GET_GLOBALS_FROM_SLVC_FULLSCR → go_grid
   │              └─ register_edit_event(mc_evt_modified / mc_evt_enter)
   │
   └─► 用户在 BRGEW 单元格输入内容
          │
          └─► DATA_CHANGED 事件 ──► FORM get_data_changed
                 ├─ (a) LOOP mt_mod_cells WHERE fieldname = 'BRGEW'
                 │         └─ READ gt_mara INDEX <gs_changed>-row_id
                 │              └─ <gs_tab>-brgew = <gs_changed>-value   ⚠️ row_id 基准
                 ├─ (b) go_grid->get_subtotals( ep_collect00 = gr_data )
                 ├─ (c) ASSIGN gr_data->* → READ INDEX 1 → ASSIGN COMPONENT 'BRGEW'
                 │         └─ 用 REDUCE # 全表求和覆盖进去            ⚠️ 自我否定
                 ├─ (d) gs_stable-row/col = 'X'
                 └─ (e) go_grid->refresh_table_display( is_stable, i_soft_refresh )
```

**关于流程的关键判断：** 从 `[1]` 到 `[6]` 之间存在一个**数据断链**——`SELECT` 写进的是局部 host variable `_mara`，而 ALV 展示与后续所有处理用的是全局 `gt_mara`。`gt_mara` 自始至终是空的。因此 `[6]` 之后，网格是一张**空表**，`get_data_changed` 里 `READ TABLE gt_mara` 必然 `sy-subrc = 4`，整条回写链路从未真正跑通过。

---

## 四、按子程序分组讲解

程序只有三个顶层执行单元（一个 `START-OF-SELECTION` + 两个 `FORM`），按职责分成三组。

---

### 组 A：数据准备与主控 —— `START-OF-SELECTION`（第 13–48 行）

**职责**：取数 → 生成字段目录 → 打开可编辑/可合计开关 → 注册事件 → 启动 ALV。整条链路是"自顶向下一次性装配"，中间没有任何状态回读。

**要点逐条：**

1. **`SELECT ... INTO TABLE _mara UP TO 10 ROWS`**
   ABAP SQL 的现代写法，把结果直接写进 host variable 而非 `INTO TABLE @DATA(...)`。`UP TO 10 ROWS` 是**客户端限制**：数据库会先返回全部满足条件的行，再由 ABAP 层截断为 10 行，没有下推。对 MARA 这种超大表来说，这不是筛选，是"全表搬回内存再扔掉 99.99%"。作为演示数据凑合能用，作为真实查询是不可接受的。
   另注：变量名 `_mara` 会让人误以为它是 MARA 结构，而字段目录合并用的却是 `ZTEST_S`——两者字段定义一旦不一致，写回时会出现静默截断（见问题 P2-2）。

2. **`REUSE_ALV_FIELDCATALOG_MERGE`**
   这个 FM 的工作方式是：**反解析本程序的 `SELECT` 语句**，把 SELECT 列表中的字段名与类型转成 field catalog，再用 `i_structure_name` 指向的 DDIC 结构补齐编辑掩码、搜索帮助、转换例程等引用属性。
   - `i_program_name = sy-repid` → 告诉它"去反解析 ZTEST7 的 SELECT 列表"
   - `i_structure_name = 'ZTEST_S'` → 提供字段的 DDIC 引用信息
   - 异常 `inconsistent_interface` / `program_error` / `OTHERS` 声明完整，`sy-subrc` 判断位置正确（FM 的 `EXCEPTIONS` 正常回填 `sy-subrc`）。

3. **`READ TABLE ... ASSIGNING FIELD-SYMBOL` 改列属性**
   ```abap
   READ TABLE gt_fieldcat ASSIGNING FIELD-SYMBOL(<gs_fcat>) WITH KEY fieldname = 'BRGEW'.
   IF sy-subrc EQ 0.
     <gs_fcat>-edit   = 'X'.
     <gs_fcat>-do_sum = 'X'.
   ENDIF.
   ```
   这是**声明式转命令式**的经典手法：字段目录由 FM 反射生成，程序只对关心的那一列做差异化增强。用 `ASSIGNING` 拿引用而不是 `INTO` 拷贝，改动直接落回内表，无需回写。
   注意这里是**按键查非键表**（`fieldname` 非 `gt_fieldcat` 的 key），会走线性查找；两列的小表无所谓，但同样的写法在几十列的表上会退化。
   同时 `IF sy-subrc EQ 0` 意味着：**一旦 `BRGEW` 列不存在（例如有人改了 SELECT 列表），可编辑和可合计会静默失效，屏幕上一个字都不会提示。**

4. **`APPEND VALUE #( name = 'DATA_CHANGED' form = 'GET_DATA_CHANGED' )`**
   用 table constructor 直接追加，语法漂亮。但缺少 `CLEAR gt_events.`，依赖"报告程序只跑一次"的隐含前提。

5. **`REUSE_ALV_GRID_DISPLAY`**
   关键参数 `i_callback_pf_status_set = 'SET_PF_STATUS'`：告诉 SLIS "PF-STATUS 要我自己拼，别用默认的"。这条参数在**全屏模式下只会被调用一次**（见组 B 的详细讨论）。
   `t_outtab = gt_mara` 传的是**引用语义**，ALV 直接操作这块内存——这正是编辑型 ALV 能"所见即所改"的原因。

---

### 组 B：界面装配回调 —— `FORM set_pf_status`（第 51–72 行）

**职责**：把全屏 ALV 的 FM 门面"翻译"成 OO 控件句柄，完成事件注册，并预留用户命令分发的位置。名字叫"设状态栏"，实际干的是"拿引用 + 注册事件"。

**要点逐条：**

1. **`GET_GLOBALS_FROM_SLVC_FULLSCR`**
   SLIS 层从不把 grid 对象暴露给调用方，所以业界约定俗成地造了一个"后门"FM：从当前动态工作区里把 `cl_gui_alv_grid` 的引用掏出来赋给 `e_grid`。这是全屏 ALV 做 OO 操作的**唯一入口**，也是本程序双层架构的咽喉。

2. **`IF go_grid IS BOUND` 保护**
   存在性判断是对的：ALV 退回 listviewer 模式或初始化异常时 `go_grid` 可能未绑定。但这里有个**静默失败风险**——如果首次回调时控件尚未完全 realize，`go_grid` 就是 unbound，`register_edit_event` 被跳过，后续 `DATA_CHANGED` **永远不触发**，程序表现为一列能编辑却没有任何联动。代码不会报错，只是"没反应"。
   更稳妥的写法：若未绑定则抛消息或 `MESSAGE`，别让用户猜。

3. **`register_edit_event` 注册两个事件**
   - `mc_evt_modified`：单元格内容变化即触发（松手就触发，响应快）→ 对应 SLIS 的 `DATA_CHANGED`
   - `mc_evt_enter`：回车确认触发 → 对应 SLIS 的 `DATA_CHANGED_F`（`DATA_CHANGED` 家族）
   两者都注册意味着**同一个单元格会触发两次事件**，`get_data_changed` 会被调用两次，合计重算两遍。对 POC 无所谓，对真实程序是浪费，也容易让"防抖"逻辑写错。

4. **`CASE sy-ucomm. WHEN OTHERS. ENDCASE.`**
   **这段是死代码，而且是结构性地错的。**
   原因：全屏模式下 `i_callback_pf_status_set` 只在 ALV 初始化时调用**一次**，此刻 `sy-ucomm` 为空（通常是 `INITIAL`）。想响应工具栏按钮点击，正确的位置是：
   - `i_callback_user_command`（每次用户操作都触发，`sy-ucomm` 有效），或
   - `i_callback_toolbar`（每次重绘工具栏时触发，还能动态改按钮）

   所以这个空的 `CASE` 表达了一个**意图**（以后要挂按钮功能），但放在了一个**永远不会再次进入**的 FORM 里。下次有人来加功能，会发现逻辑写了不生效。

---

### 组 C：变更处理与重算 —— `FORM get_data_changed`（第 74–115 行）

**职责**：整个程序真正干活的地方，也是全部技术含量和全部 bug 集中的地方。五个动作：

#### C-1 回写用户输入（核心）

```abap
LOOP AT io_data_changed->mt_mod_cells ASSIGNING FIELD-SYMBOL(<gs_changed>) WHERE fieldname = 'BRGEW'.
  READ TABLE gt_mara ASSIGNING FIELD-SYMBOL(<gs_tab>) INDEX <gs_changed>-row_id.
  IF sy-subrc EQ 0.
    <gs_tab>-brgew = <gs_changed>-value.
  ENDIF.
ENDLOOP.
```

- `WHERE fieldname = 'BRGEW'` 把处理范围限定在唯一可编辑列，做得对。
- `ASSIGNING` 拿引用直接改，不拷贝，效率好。
- **`row_id` 基准问题（重点）**：`cl_alv_changed_data_protocol` 里有两张表，`MT_DATA_CHANGED` 的 `ROW_ID` 是 **1 基**（等于内表行号），而 `MT_MOD_CELLS` 的 `ROW_ID` 是 **0 基**。这里用 `mt_mod_cells` 却直接 `INDEX <gs_changed>-row_id`，会出现**整体错位一行**：编辑第 1 行 → `INDEX 0` 报 `sy-subrc = 4`，写入被 `IF` 吞掉；编辑第 2 行 → 值被写进第 1 行。**静默数据错位，不报错。**
- 修法（二选一）：
  ```abap
  READ TABLE gt_mara ASSIGNING <gs_tab> INDEX <gs_changed>-row_id + 1.
  ```
  或改用官方推荐的"整表替换"方式：
  ```abap
  LOOP AT io_data_changed->mt_data_changed INTO FIELD-SYMBOL(<ls_dc>).
    READ TABLE gt_mara ASSIGNING <gs_tab> INDEX <ls_dc>-row_id.  " 1 基
    ...
  ENDLOOP.
  ```
- **赋值无任何类型防护**：`<gs_changed>-value` 是泛型字段，若 ALV 交来 `'1,234.50'`（带千分位逗号）或 `'ABC'`，直接赋给 `ZTEST_S-BRGEW`（NUMC/QUAN）会触发转换异常或静默置零。这里既没有 `CATCHING cx_sy_conversion_error`，也没有合法性校验。
- `gt_mara` 现在是空表，所以这整段**从未被真正执行过**——bug 一直被空表掩盖。数据一接上，症状立刻显形。

#### C-2 读 ALV 已算好的合计（转折点）

```abap
go_grid->get_subtotals( IMPORTING ep_collect00 = gr_data ).
```

`EP_COLLECT00` 取的是**总体合计**集合：一个只有一行的表，结构与数据表一致，但只有 `do_sum = 'X'` 的列被填了值。
这一步本身是**合理的**——ALV 只在已排序且列 `do_sum = 'X'` 时才会填总，是省掉自己写排序分组逻辑的捷径。

#### C-3 又把合计推翻重算（自相矛盾）

```abap
ASSIGN gr_data->* TO <gtr_sum_tab>.
READ TABLE <gtr_sum_tab> ASSIGNING FIELD-SYMBOL(<l_sum>) INDEX 1.
IF sy-subrc EQ 0.
  ASSIGN COMPONENT 'BRGEW' OF STRUCTURE <l_sum> TO FIELD-SYMBOL(<lg_val>).
  IF <lg_val> IS ASSIGNED.
    <lg_val> = REDUCE #( INIT lv_i TYPE ntgew_15
                       FOR <ls_t> IN gt_mara NEXT lv_i = lv_i + <ls_t>-brgew ).
  ENDIF.
ENDIF.
```

这一段在逻辑上有三层问题，从表到里：

1. **为什么要推翻 ALV 的结果？** 最合理的解释是：ALV 的合计只统计**当前可见/过滤后**的行，而 POC 想演示"全量重算"。如果确实要这个语义，注释里一个字都没写，后来者无法判断是有意还是写错了。
2. **算出来的值送不到屏幕上。** `get_subtotals` 的 `ep_collect00` 是 `IMPORTING`，返回的是 ALV 内部集合的引用。修改它之后，程序**没有调用** `set_subtotals`、也没有 `modify_cell`、也没有再次触发合计计算——ALV 下一次绘制时用的仍是它自己算的数。**屏幕上显示的合计和 `<lg_val>` 里被改过的值毫无关系**，这段计算是纯粹的无效功。
3. **类型隐患**：
   - `ASSIGN gr_data->* TO <gtr_sum_tab>`：`gr_data` 若未绑定或不是表类型，会抛运行时异常，而这里**没有 `CATCHING`**，直接 dump。
   - `ASSIGN COMPONENT 'BRGEW'` 若结构里没有该组件，ASSIGN 失败，`<lg_val>` 未赋值，被 `IF ... IS ASSIGNED` 挡下——又是一次**静默失效**。
   - `REDUCE` 的累加器硬编码 `ntgew_15`，若 `ZTEST_S-BRGEW` 定义为 `NETGEW`（QUAN 13,3）或其他长度，赋值时截断/异常。

#### C-4 稳定化刷新（唯一做对的部分）

```abap
gs_stable-col = 'X'.
gs_stable-row = 'X'.
go_grid->refresh_table_display(
  EXPORTING is_stable = gs_stable  i_soft_refresh = 'X'
  EXCEPTIONS finished = 1  OTHERS = 2 ).
```

这是这段代码里**最有价值的设计**：编辑单元格后如果不加 `is_stable` 刷新，ALV 会重排视图，**用户的输入光标会跳到别的行**，连续录入体验极差。`is_stable` 固定行列位置 + `i_soft_refresh = 'X'` 保留当前排序过滤状态，是对的标准解法。
但有两个瑕疵：
- `gs_stable` 是全局变量，每次进来都重设成同样的 `'X'`，其实应设为局部变量；且 `row_cnt` 用了默认值 1，语义不明确（到底固定 1 行还是更多？应显式写 `row_cnt = 1`）。
- `EXCEPTIONS finished = 1` 是**正常情况**：ALV 被导出/打印/跳转清屏时 `refresh_table_display` 就会抛 `FINISHED`。把它和 `OTHERS` 一起塞进一个**空的** `IF sy-subrc <> 0. ENDIF.`，等于把所有异常都吞了。空异常处理块是明确的坏味道。

---

## 五、问题清单

按严重程度排序。P0 = 程序当前不可用/数据错误；P1 = 真实环境会出事；P2 = 维护性与规范；P3 = 优化项。

| ID | 级别 | 位置 | 问题 | 后果 |
|----|------|------|------|------|
| **P0-1** | 致命 | L18 | `SELECT ... INTO TABLE _mara` 写入 host variable，而 ALV 展示与回写都用全局 `gt_mara` | **数据断链**：ALV 显示空表，`get_data_changed` 全部逻辑从未执行，整条链路不可用 |
| **P0-2** | 致命 | L79 | `mt_mod_cells` 的 `ROW_ID` 是 0 基，直接 `INDEX <gs_changed>-row_id` | **静默错行写值**：首行写入被 `IF` 吞掉，次行及以后的值落到上一行。无异常、无提示 |
| **P1-1** | 高 | L85–97 | 读 ALV 合计后又用 `REDUCE` 全表重算覆盖回去，但**没有任何回推机制** | 计算结果永远到不了屏幕，是无效逻辑；同时掩盖"合计是否正确"的真实判断 |
| **P1-2** | 高 | L81 | `<gs_changed>-value`（泛型）直接赋给数值 DDIC 字段，无转换异常捕获、无数字校验 | 非法输入触发 dump 或静默置零 |
| **P1-3** | 高 | L68–71 | 全屏模式下 `i_callback_pf_status_set` 只触发一次，`CASE sy-ucomm` 是死代码 | 预留的命令分发逻辑永远不会执行；后续加功能的人会踩坑 |
| **P1-4** | 高 | L90 | `ASSIGN gr_data->* TO <gtr_sum_tab>` 无 `CATCHING` | `gr_data` 未绑定/类型不符时运行时 dump |
| **P1-5** | 高 | L57 | `IF go_grid IS BOUND` 保护把"控件未就绪"变成静默跳过 | 编辑事件可能从未注册，表现为"能编辑但无联动"，极难排查 |
| **P1-6** | 高 | L18 | `UP TO 10 ROWS` 是客户端截断，不可下推 | 全表扫描 MARA 后丢弃 99.99%，生产环境是性能事故 |
| **P2-1** | 中 | L1–2, 8–9 | SLIS FM 层与 OO 层混用（`TYPE-POOLS: slis` + `lvc_s_stbl` + `cl_gui_alv_grid`） | 两套 API/两套事件语义/两套类型，认知负担与维护成本翻倍 |
| **P2-2** | 中 | L18 vs L23 | 数据取自 MARA（host variable `_mara`），字段目录引用 `ZTEST_S`，写回也写 `ZTEST_S` | 两个结构 BRGEW 定义若不一致，写回时静默截断；命名 `_mara` 误导读者 |
| **P2-3** | 中 | L58–64 | 同时注册 `mc_evt_modified` 与 `mc_evt_enter`，且 SLIS 侧已通过 `it_events` 注册 `DATA_CHANGED` | 同一单元格可能触发 2 次事件，合计重复计算；事件来源难追溯 |
| **P2-4** | 中 | L110–111 | `IF sy-subrc <> 0. ENDIF.` 空异常处理块，吞掉 `finished`（正常情况）与所有 `OTHERS` | 出错时完全无感，故障排查只能靠 ST22 |
| **P2-5** | 中 | L4–9 | 六个全局对象充当跨过程共享状态 | 无过程可独立测试；任何改动都需全程序回归 |
| **P2-6** | 中 | 全局 | 无消息类、无错误提示 | 字段目录合并失败 → 空白屏幕，用户无法判断是数据为空还是程序坏了 |
| **P3-1** | 低 | L37 | `APPEND` 到 `gt_events` 前未 `CLEAR` | 依赖"只执行一次"的隐含前提，回归/多选屏场景会重复注册事件 |
| **P3-2** | 低 | L99–100 | `gs_stable` 用全局，且 `row_cnt` 取默认值 1 未显式声明 | 语义不清，后续若要"固定当前行"需额外猜测 |
| **P3-3** | 低 | L31 | `READ TABLE gt_fieldcat ... WITH KEY fieldname` 按非键字段线性查找 | 列数少时无所谓，多列场景退化 |
| **P3-4** | 低 | L95 | `REDUCE` 累加器硬编码 `ntgew_15`，无溢出保护 | 结构定义变更时静默截断；极端数据溢出 |
| **P3-5** | 低 | — | 无 STYLING/单元格样式、无 F4、无 `SET_TITLEBAR`、无导出 Excel 的业务字段说明 | POC 阶段可接受，投产前需补 |

---

## 六、改进建议

### 6.1 立即修复（让它先跑起来）

**① 打通数据链路**

```abap
DATA gt_mara TYPE TABLE OF ztest_s.

START-OF-SELECTION.
  SELECT matnr, brgew
    FROM mara
    INTO TABLE @gt_mara
    UP TO 10 ROWS.
```

或者保留 host variable 写法，但必须显式搬运一次（不推荐，只是过渡）：

```abap
  SELECT matnr, brgew FROM mara INTO TABLE @DATA(lt_host) UP TO 10 ROWS.
  gt_mara = lt_host.
```

**② 统一数据结构口径**：SELECT 的目标结构、字段目录引用结构、内表类型必须是**同一个** `ZTEST_S`，不要出现 MARA 与 ZTEST_S 混用。把 host variable 名字从 `_mara` 改成 `_zs`。

**③ 修 `row_id` 基准**（改用官方推荐的 `MT_DATA_CHANGED` 整表语义，或显式 `+ 1`）：

```abap
LOOP AT io_data_changed->mt_mod_cells
     ASSIGNING FIELD-SYMBOL(<gs_changed>)
     WHERE fieldname = 'BRGEW'.

  READ TABLE gt_mara
       ASSIGNING FIELD-SYMBOL(<gs_tab>)
       INDEX <gs_changed>-row_id + 1.                 " mt_mod_cells 的 ROW_ID 是 0 基
  IF sy-subrc <> 0.
    CONTINUE.
  ENDIF.

  " 带校验与异常捕获的写回
  TRY.
      <gs_tab>-brgew = <gs_changed>-value.
    CATCH cx_sy_conversion_error.
      MESSAGE e000(ztest) WITH '重量格式非法' DISPLAY LIKE 'E'.
      go_grid->refresh_table_display( i_soft_refresh = 'X' ).
      RETURN.
    CATCH cx_sy_move_cast_error.
      RETURN.
  ENDTRY.
ENDLOOP.
```

**④ `UP TO 10 ROWS` 换成真实条件**

```abap
SELECT matnr, brgew
  FROM mara
  INTO TABLE @gt_mara
  WHERE matnr LIKE 'Z%'.
```

真正的性能控制要靠 `WHERE`、合适的索引，以及必要时在 `WHERE` 里带 `PACKAGE SIZE`（包大小）分批处理，而不是客户端截断。

### 6.2 合计逻辑：二选一，别两头都要

**方案 A（推荐，简单可靠）**——完全信任 ALV，删掉 `get_subtotals` + `ASSIGN COMPONENT` + `REDUCE` 整段：

```abap
FORM get_data_changed USING io_data_changed TYPE REF TO cl_alv_changed_data_protocol.

  LOOP AT io_data_changed->mt_mod_cells
       ASSIGNING FIELD-SYMBOL(<gs_changed>)
       WHERE fieldname = 'BRGEW'.
    " ... 写回 gt_mara（同 6.1 ③）
  ENDLOOP.

  " ALV 依据 do_sum = 'X' 自动重算合计行，这里只需保持视图稳定
  go_grid->refresh_table_display(
    EXPORTING is_stable      = VALUE lvc_s_stbl( row = 'X' row_cnt = 1 col = 'X' )
              i_soft_refresh = 'X' ).

ENDFORM.
```

**方案 B**——业务上确实需要"不受排序/过滤影响的全量合计"：

```abap
DATA lv_total TYPE ngeuw_15.

" 1) 自己算全量合计，写到独立的全局变量，供工具栏显示或导出使用
lv_total = REDUCE #( INIT lv = VALUE ngeuw_15( )
                     FOR <ls_t> IN gt_mara NEXT lv = lv + <ls_t>-brgew ).

" 2) 如需推给 ALV，必须显式调用 modify_cell，而不是改 get_subtotals 的返回值
"    go_grid->modify_cell( i_row_id = ... i_fieldname = 'BRGEW' i_data = lv_total ).
```

无论选哪个，都请在代码里写清注释：**合计的口径是什么（可见行 / 全量行）**。这是这类需求最常见的歧义来源。

**③ 事件去重**：确认 `DATA_CHANGED` 与 `register_edit_event` 不重复触发，二者只留一处（推荐统一走 SLIS 的 `it_events`，只在需要 OO 能力时才手动 `register_edit_event`）。

### 6.3 架构层面：终结双层混用

选一条路走到底，不要中间态。

**路径一：全 OO（推荐，SAP 官方现行方向）**

```abap
DATA go_grid     TYPE REF TO cl_gui_alv_grid.
DATA go_container TYPE REF TO cl_gui_custom_container.
DATA gr_data     TYPE REF TO data.

" 1) 自建屏幕 100，在 SCREEN 事件里放 container，把 grid attach 上去
" 2) go_grid->set_pf_table_by_xxx / go_grid->register_edit_event( cl_gui_alv_grid=>mc_evt_modified )
"    go_grid->set_event_ready( )                      " ← 必须有这一步！
" 3) go_grid->display( ) 或 set_data( )->refresh( )
```

好处：`set_pf_status_lvc` 的 `sy-ucomm` 每帧有效、事件语义单一、类型统一（全是 `lvc_*`）、可以直接 `modify_cell` 推值。代价：失去 `REUSE_ALV_GRID_DISPLAY` 的便利，要自己管 screen 和 layout。

**路径二：全 SLIS（保守，改造成本低）**

去掉 `TYPE-POOLS: slis` 之外的所有 OO 引用，`lvc_s_stbl` 换成 `slis_stablay`，合计刷新交给 ALV 自身 + `CALL FUNCTION 'ALV_CHANGE_TABLE_WITH_ID'`，事件只用 `it_events`。这条路上 `set_pf_status` 里的 `sy-ucomm` 依然不可靠，命令分发仍应走 `i_callback_user_command`。

### 6.4 把可测试的核心逻辑抽出来

现在的"合计计算"被埋在 FORM 里，和 UI 事件耦合死了。抽成一个**纯函数式**的 FORM，让它能被 `PERFORM` 单独调用、单独验证：

```abap
FORM calc_total
  USING    it_rows  TYPE ztest_s_tt
  CHANGING ev_total TYPE ngeuw_15.
  CLEAR ev_total.
  LOOP AT it_rows INTO DATA(ls_row).
    ev_total = ev_total + ls_row-brgew.
  ENDLOOP.
ENDFORM.
```

`get_data_changed` 里只需 `PERFORM calc_total USING gt_mara CHANGING gv_total.`。这样合计口径变更时可以单独测，UI 层出问题也不影响计算验证——对这种"能编辑 + 联动合计"的功能，可测性比什么都值钱。

### 6.5 稳健性与规范

- **补消息类**（如 `ZTEST`，维护 `000` 消息号）：字段目录合并失败、找不到 `BRGEW` 列、`go_grid` 未绑定、输入格式非法——都应给出明确的 `MESSAGE`，而不是静默 `IF` 跳过。
- **异常处理要有内容**：`refresh_table_display` 至少区分 `finished`（正常，静默返回）与 `OTHERS`（异常，记日志 + 提示）。
- **`ASSIGN` 全部加保护**：`ASSIGN gr_data->* TO <gtr_sum_tab> CATCHING cx_root`，`ASSIGN COMPONENT` 失败时至少 `MESSAGE`。
- **局部化状态**：`gs_stable` 改为 `VALUE lvc_s_stbl( ... )` 内联构造，`gr_data` 改局部变量；只保留真正需要跨过程共享的（`gt_mara`、`go_grid`）。
- **`CLEAR gt_events.`** 后再 `APPEND`，不依赖单次执行假设。
- **`SET_TITLEBAR` + `STYLING`**：至少给 BRGEW 列加语义色（可编辑单元格淡黄底），让用户一眼看出哪些格能改。
- **投产前补齐业务要件**：数字格式校验（`nmbm` / 正则）、允许范围、保存/放弃按钮（`i_callback_user_command`）、消息提示、以及——如果要落库——用 `MODIFY mara ...` 加更新锁和 `SY-MANDT` 校验。

### 6.6 修复优先级

```
第一步（让它能跑）      ①数据链路  ②row_id 基准  ③UP TO 10 → WHERE
第二步（让它可信）      ④合计逻辑二选一  ⑤输入校验与异常捕获  ⑥消息类
第三步（让它可维护）    ⑦统一 SLIS 或 OO  ⑧抽离 calc_total  ⑨事件去重
```

---

## 附录：逐行速查

| 行号 | 内容 | 评价 |
|-----|------|------|
| 1–2 | `REPORT` + `TYPE-POOLS: slis` | 经典 ALV 报表 |
| 4–9 | 6 个全局对象 | 共享状态过多（P2-5） |
| 11 | `<gtr_sum_tab> TYPE table` | 类型擦除，运行时风险 |
| 15–18 | `SELECT ... UP TO 10 ROWS → _mara` | **断链 + 不可下推（P0-1 / P1-6）** |
| 20–29 | `REUSE_ALV_FIELDCATALOG_MERGE` | 用法正确，异常声明完整 |
| 31–35 | 改写 BRGEW 的 `edit` / `do_sum` | 手法正确；失败静默 |
| 37 | 追加 `DATA_CHANGED` 事件 | 缺 `CLEAR`（P3-1） |
| 39–46 | `REUSE_ALV_GRID_DISPLAY` | 主装配点 |
| 54–56 | `GET_GLOBALS_FROM_SLVC_FULLSCR` | 双层架构的咽喉 |
| 58–64 | 注册 `modified` / `enter` | 重复注册风险（P2-3） |
| 68–71 | 空 `CASE sy-ucomm` | **死代码（P1-3）** |
| 78–83 | `mt_mod_cells` 回写 | **错行写值（P0-2）**；无类型保护 |
| 85–88 | `get_subtotals` | 本身合理 |
| 90–97 | `ASSIGN` + `ASSIGN COMPONENT` + `REDUCE` | **自相矛盾且无效（P1-1 / P1-4）** |
| 99–105 | `is_stable` + `i_soft_refresh` | **全程序最正确的一段** |
| 110–111 | 空异常处理块 | 吞异常（P2-4） |

**总体评价**：骨架（`get_subtotals` 拿合计、`is_stable` 稳定刷新、字段目录反射后差异化改列属性）体现了对 ALV 的一定理解，是一份方向正确的 POC 草稿；但存在 **2 个 P0 级缺陷**使其当前完全不可用，且大量静默 `IF` 吞掉了本该暴露的信号，真实环境上线风险很高。按 6.6 的三步优先级修复后，可作为生产级"可编辑合计行"方案的起点。
