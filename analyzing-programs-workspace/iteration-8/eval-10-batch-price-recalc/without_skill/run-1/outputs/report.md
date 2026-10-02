# ZPRICE_BATCH 夜间调价程序分析报告

**分析对象**：`zprice_batch.abap`（108 行，REPORT 报表程序）
**执行场景**：前台对话框 + SM36 后台作业（同一份代码，双模式运行）
**核心结论**：程序的骨架（三段式 FORM：取数 → 调价 → 提交）是教科书式的，结构清晰；但存在 **3 个高危后台风险**：① 调价系数按 `sy-batch` 静默切换（后台 +2% / 前台 +5%）；② 重复运行会**复利式累涨**，无幂等保护；③ 整个选区被塞进**单个数据库事务**，且提交动作被一个勾选框控制。后台空结果还会被记成"成功"，形成静默空跑。

---

## 一、程序结构速览

```abap
REPORT zprice_batch.

INITIALIZATION.
  gv_run = 1.

START-OF-SELECTION.
  IF sy-batch = 'X'.
    gv_batch = abap_true.
  ENDIF.

  PERFORM read_prices.      " 取数
  PERFORM recalculate.      " 逐行调价 + 逐行 MODIFY
  PERFORM finalize.         " 判定是否 COMMIT + 日志
```

| 块 | 行 | 职责 | 是否写库 |
|---|---|---|---|
| `INITIALIZATION` | 33-34 | 计数器初始化 | 否 |
| `START-OF-SELECTION` | 36-44 | 模式判定 + 三段调度 | 否 |
| `FORM read_prices` | 47-60 | `SELECT ... INTO TABLE marc` | 否 |
| `FORM recalculate` | 63-89 | 逐行改价 + `MODIFY marc` | **是** |
| `FORM finalize` | 92-108 | 测试/提交/结束日志 | 提交事务 |

程序是**单 LUW、无分批、无异常捕获、无错误日志表**的最小可用形态。

### 全局对象

```abap
TYPES: BEGIN OF ty_job,
         matnr   TYPE mara-matnr,
         werks   TYPE marc-werks,
         netpr   TYPE marc-netpr,
         waers   TYPE marc-waers,
         eintr   TYPE marc-eintr,
         datnr   TYPE marc-datnr,
         status  TYPE char1,
       END OF ty_job.

TYPES ty_job_tab TYPE STANDARD TABLE OF ty_job WITH EMPTY KEY.

DATA gt_jobs   TYPE ty_job_tab.   " 同时是选区参数 s_matnr 的参照对象
DATA gv_run    TYPE i.
DATA gv_ok     TYPE i.
DATA gv_failed TYPE i.
DATA gv_batch  TYPE abap_bool.
DATA gv_commit TYPE i.           " 声明后从未使用（死变量）
```

- `ty_job` 是 `MARC` 的**投影结构体**（非 DDIC 结构），因此 `MODIFY` 的语义完全由字段顺序无关的"同名字段写入"决定。
- `status` 是纯本地字段，`MARC` 中不存在，`MODIFY marc` 时被忽略；它只写进了内部表，且**从未被读取**——纯粹的死字段。
- `gv_commit` 声明后从未赋值/读取——死变量（见第七节）。
- `gt_jobs` 同时承担"结果集"和"选区参数参照对象"两个角色，属于过度耦合。

### 选择屏幕

```abap
SELECTION-SCREEN BEGIN OF BLOCK b.
  SELECT-OPTIONS s_matnr FOR gt_jobs-matnr.
  PARAMETERS p_test AS CHECKBOX.
  PARAMETERS p_commit AS CHECKBOX.
SELECTION-SCREEN END OF BLOCK b.
```

| 参数 | 含义 | 后台默认值风险 |
|---|---|---|
| `s_matnr` | 物料号范围 | **非必填**。留空 = 全表 MARC，见 3.1 |
| `p_test` | 测试模式，不写库 | 变体里是否勾选由人决定 |
| `p_commit` | 是否 `COMMIT WORK` | **勾了才提交**，漏勾 = 全部回滚却显示成功 |

---

## 二、取数逻辑（`FORM read_prices`，行 47-60）

```abap
SELECT matnr werks netpr waers eintr datnr
  FROM marc
  INTO TABLE gt_jobs
  WHERE matnr IN s_matnr
    AND waers <> ' '.

IF gt_jobs IS INITIAL.
  MESSAGE 'No price records found' TYPE 'S'.
  LEAVE TO CURRENT TRANSACTION.
ENDIF.
```

### 2.1 取数范围 = 全量 MARC 记录，无业务过滤

`MARC` 是 SAP 中最大的次级表之一（生产系统通常数千万至上亿行），一行 = 物料 × 工厂 × 价格区。程序只用了两个条件：

- `matnr IN s_matnr`：物料范围（前端可留空）
- `waers <> ' '`：**等于没有过滤**。`MARC-WAERS` 是 NOT NULL 的必填字段，永远不等于空格，这个条件是无操作条件（no-op），既挡不住任何数据，也优化不了任何东西。它传达的"只要有币种"这一业务意图实际上是不成立的。

**缺失的过滤维度**（都会直接影响改价覆盖面）：

| 缺失条件 | 后果 |
|---|---|
| `werks` 限定 | 无法按工厂分批调价，无法做工厂白名单；跨工厂全改 |
| 有效价日期 `datnr` | 已过期的价（如 `MEINS='1'` 暂停或失效价）也被上调 |
| 有效期类型 `eintr` | 与上面配套，`eintr = ' '` 表示永久价，逻辑上应显式处理 |
| 标准价 `MARC-STPR` | 只改 `NETPR` 不改 `STPR`，两者会**分叉**，依赖 `STPR` 的下游（差异分析、DB 计划价、成本）拿不到新价 |
| `LOKLM`（价格控制标记）/ 价格视图 | `MARC-LOKLM = 'X'`（锁定价）通常不允许被程序改，这里未拦 |

**取数用 `MARC` 而不是条件记录**：`MARC-NETPR` 是"物料的采购参考价"，它在很多场景下由价格条件（`EKKP`/`EKKN`/`COND`）自动确定计算带出。程序直写 `MARC`，**不会同步条件记录**——如果后续的价格确定（自动确定价格、框架协议价）仍然从条件记录取价，那么这次批量调价在采购订单上"看不到效果"。这是需要与业务确认的**集成口径问题**，不是语法问题。

### 2.2 全表风险（`s_matnr` 留空）

```abap
WHERE matnr IN s_matnr   " s_matnr 未填 → IN 条件为空选区 → 不加限制
```

`s_matnr` 没有 `OBLIGATORY`，也没有 `AT SELECTION-SCREEN` 校验。若后台变体丢失、或有人手工 `SM36` 启动后直接回车：

1. 一次性 `SELECT ... INTO TABLE` 拉取**全系统 MARC** → 应用服务器工作进程内存被抽干（典型 dump：`TSV_TNEW_PAGE_ALLOC_FAILED`）；
2. 物理内存装不下 → 换到扩展工作进程 → 仍然装不下 → 直接短路 dump；
3. 交互式前台跑同一份代码，卡在取数阶段 30 分钟，界面无响应，用户强杀 → 产生 5 秒/10 秒短时工作进程，扰动整个应用服务器；
4. 数据库侧：单条超大查询占用大量临时表空间 / undo。

**这是前台与后台共有的最高危项**，且触发条件是"一个 Enter 键"。

### 2.3 空结果在后台的处理（`MESSAGE 'S'` + `LEAVE`）

```abap
IF gt_jobs IS INITIAL.
  MESSAGE 'No price records found' TYPE 'S'.
  LEAVE TO CURRENT TRANSACTION.
ENDIF.
```

这是本报告中**最隐蔽的后台缺陷**：

- `MESSAGE ... TYPE 'S'` 是**状态消息**，不抛异常、不置消息号、不让程序 ABORT。
- 后面 `LEAVE TO CURRENT TRANSACTION` 正常退出报告程序。
- 结果：SM37 里这个作业状态是 **"已完成 / Completed"，无错误**，业务日志末尾只有一行 `No price records found` 的软消息。

**运维视角的失败形态**：物料范围被错误地填成不存在的前缀、参数类型位（PARA）配置丢了、变体被删——作业照常"绿"，但昨晚的价格**一夜之间没调**。如果这台机器上价格还关联着运费/汇率/成本加成，那么下游的成本核算、报价、差异分析**继续使用昨天的价**，误差会在几天后才被发现。

**修复方向**：后台模式下必须让作业"红"。例如

```abap
IF gt_jobs IS INITIAL.
  MESSAGE 'No price records found' TYPE 'S'.
  IF sy-batch = 'X'.
    MESSAGE ID 'ZBATCH' TYPE 'E' NUMBER '001'.   " 或 RAISING / ABORT 模式
  ELSE.
    LEAVE TO CURRENT TRANSACTION.
  ENDIF.
ENDIF.
```

或统一改成"后台一律 `MESSAGE ... TYPE 'A'`（可 ABORT）"，让作业状态落到 `Cancelled`，接入作业失败告警。

另外，`LEAVE TO CURRENT TRANSACTION` 本身在**纯报表的后台上下文**中并非官方推荐用法：它面向对话式事务的环境切换，在无事务上下文的批处理执行中，行为随程序类型/调用入口而变（可能被忽略，也可能触发运行期错误）。稳妥写法是 `LEAVE PROGRAM.`（配合 message）或直接 `RETURN.`——但当前 `FORM read_prices` 不是事件块，用 `RETURN` 只退出 FORM，所以需要配合 `MESSAGE ... TYPE 'E'` 抛出异常或改写为事件块中的 `MESSAGE TYPE 'A'`。

---

## 三、调价逻辑（`FORM recalculate`，行 63-89）

```abap
FORM recalculate.

  DATA lv_factor TYPE p DECIMALS 4.

  LOOP AT gt_jobs INTO DATA(ls_job).

    gv_run = gv_run + 1.

    lv_factor = COND #( WHEN sy-batch = 'X' THEN 1.02 ELSE 1.05 ).

    ls_job-netpr  = ls_job-netpr * lv_factor.
    ls_job-status = 'X'.

    MODIFY gt_jobs FROM ls_job.

    IF p_test IS INITIAL.
      MODIFY marc FROM ls_job.
      gv_ok = gv_ok + 1.
    ELSE.
      gv_failed = gv_failed + 1.
    ENDIF.

  ENDLOOP.

  WRITE: / 'run', gv_run, 'ok', gv_ok, 'failed', gv_failed.

ENDFORM.
```

### 3.1 【高危】调价系数按运行模式静默切换

```abap
lv_factor = COND #( WHEN sy-batch = 'X' THEN 1.02 ELSE 1.05 ).
```

同一段业务规则，写出了**两个不同的结果**：

| 运行模式 | 系数 | 效果 |
|---|---|---|
| 后台作业（`sy-batch = 'X'`） | `1.02` | +2% |
| 前台对话框 | `1.05` | +5% |

这是本程序最严重的设计问题，原因有四：

1. **业务规则不可审计**。审计/内审问"这批物料 3 月加价比例是多少"，答案取决于当时是谁点的运行按钮（后台变体 2%，白天有人手工补跑 5%）。同一个 `NETPR` 值无法反推出用了哪个系数——`MARC` 里没有存"本次调价比例"。
2. **前端"验证"无效**。业务人员习惯性先在前台用小范围试跑一遍看结果，但前台跑出来是 +5%，后台实际执行是 +2%。**试跑结论不能外推到正式执行**，这是最隐蔽的坑。
3. **边界不一致**。如果只跑一部分（例如白天只补了 3 个工厂），那么这批数据里同时存在 +2% 和 +5% 两种口径，混合后无法拆分归因。
4. **每次因子在循环内重算**（虽然值恒定），把一个"运行级参数"放进了"行级计算"，属于作用域错误，也让将来改成"按工厂差异化系数"时容易漏改。

**正确做法**：系数必须是**输入参数**，并且由选定的变体显式携带，写进作业日志：

```abap
PARAMETERS p_factor TYPE p DECIMALS 4 DEFAULT 1.02.
```

如果业务上确实要"后台自动、系数按工厂维护"，那系数应当来自一张配置表（按工厂/物料组维护调价率），而不是靠运行方式隐式决定。

### 3.2 【高危】重复执行 = 复利累涨，无幂等保护

```abap
ls_job-netpr = ls_job-netpr * lv_factor.
```

调价基准是**当前价**（读-改-写闭环），而不是某个"基准价/原价"。因此：

| 执行次数 | 相对原始价 |
|---|---|
| 1 次 | ×1.02 |
| 2 次（当晚误重跑） | ×1.0404 |
| 3 次 | ×1.0612 |

真实的触发场景比"手滑点两次"多得多：

- **作业失败后 `SM37` 点"Restart"** —— 这是运维最常见的操作。作业在改价到一半时因某个 DB 锁 dump，运维重启作业，**已经写入并提交的部分被再乘一次**。因为没有分批、没有提交检查点，重启等于从头再来。
- **同一晚两个日历/两台 Job Scheduler 都在触发**（应用服务器迁移后旧触发器未清理）。
- **上一晚作业其实成功但响应超时**，运维认为失败而手动重跑。
- **`spool` 被删后"重打"作业**（`SM61` 风格的重跑）。

**后果**：价格单向漂移，且**没有任何字段能识别"这条价被调过几次"**。事后只能靠对比合同价（`EKKP`）、标准价（`STPR`）、移动平均价（`MBEW-SLPR`）反推，误差不可逆。

**幂等保护方案（任选其一或组合）**：
- 增加一张调价流水表 `ZPRICE_LOG`，记录 `matnr / werks / old_netpr / new_netpr / factor / run_id / timestamp`，以 `run_id` 做唯一性约束；重复执行前先查"该物料是否已在本次 run_id 中处理过"。
- 用业务日期做运行头锁：表里存"最后成功执行的调价日期"，若当日已成功则直接 `ABORT`（`SELECT ... FROM zlock FOR UPDATE`）。
- 更彻底：用**增量基准**——`new = old_base * factor^n`，把基准价快照到扩展字段，而不是就地取当前价。
- 最低成本的护栏：调价前后记录 `netpr` 的汇总值（`SUM`），若发现 `SUM(新) > SUM(旧) * factor * 1.001`，说明已重复执行，dump 退出。

### 3.3 【中危】`MODIFY marc` 逐行下发 → N 条 UPDATE，单事务

```abap
MODIFY marc FROM ls_job.
```

`MODIFY dbtab FROM wa`（`wa` 为结构体而非内表）是**单行 MODIFY**。也就是说 10 万条记录 = **10 万条独立的 UPDATE 语句**，全部发生在**同一个数据库事务（LUW）里**，直到 `finalize` 的 `COMMIT WORK` 才提交。

代价：

- **数据库负载**：10 万条单行 UPDATE 远慢于 `MODIFY marc FROM TABLE itab`（一次 DML 批下发）。这是最容易想到的性能改造点。
- **锁持有时间**：所有 `MARC` 行锁从第一条一直持到最后一小时。期间任何并发采购定价、`ME21` 建单、`MK01` 建物料、`MARC` 的价格确定过程都会撞锁甚至死锁。
- **回滚段/undo 膨胀**：单事务累积千万级字节的 undo，Oracle 上表现为 `ORA-01555 snapshot too old`、DB 批处理尖峰；HANA 上表现为 delta/undo 存储暴涨。
- **一次 dump 全盘皆输**：任何一行失败（锁冲突、超时、表空间满），整个程序短时 dump，前面所有工作被整体回滚——**跑了两小时，结果归零**。
- **`MODIFY marc FROM ls_job` 未带字段列表**：会把 `waers / eintr / datnr` 原样回写（值未变，无害），但这属于"整结构回写"，将来若 `ty_job` 扩了字段，容易出现非预期的字段被写入。
- **MARC 二级索引影响**：`MARC` 上有多个二级索引（含 BW 相关派生索引），大规模更新会使其统计信息失真、增量标记异常，BW 增量抽取可能出现 delta 链断裂，需检查 `RSDDELTA` 状态。

### 3.4 【中危】逐行 `MODIFY` 无异常捕获 = 一错全崩

循环体内没有任何 `TRY/CATCH`。`MODIFY` 常见的失败点：

| 失败原因 | 典型 dump |
|---|---|
| 表锁/行锁冲突（有人开着 `MM02` 改同物料价） | `SAPDB__RC_STOREDPL` / DB 死锁 dump |
| enqueue/更新超时 | `TIMEOUT` / `UPDATE_TIMEOUT` |
| 数据库存储参数超限 | `ORA-01555` / HANA 内存保护 |

后台程序 dump = 作业状态 `Aborted`，且（因为没有分批提交）**已完成的改价全部丢失**。日志里只有一行 ABAP 运行时错误，**不知道是哪个物料、哪个工厂触发的**（`MODIFY` 没有带 `MARC` 主键的可读描述，且没有任何自定义日志）。

**正确做法**：把写库动作包上异常处理，逐行记录失败原因，落盘日志表；成功/失败分开统计，作业结尾输出失败清单。

### 3.5 【中危】无锁、无排他、无与并发作业的互斥

程序既没有 `LOCK OBJECT`（如 `LOCK OBJECT ZMARC_LOCK IN SHARE MODE`），也没有工厂级排他。夜间它与以下动作并发跑在同一个表上：

- 采购订单自动定价、条件记录价格确定（`EKPO` 建单时回写）；
- `MSEG`/`MB01` 收货时的价格校验、`MK01` 建物料；
- 月末/季度末的标准价重估 `MR21/CK24/CK40`（这一条尤其致命，见 5.4）；
- 同一 `MARC` 行被两个 `ZPRICE_BATCH` 实例同时处理（多应用服务器 + 手工补跑）→ **丢失更新（lost update）**：两个会话都读到 100，各自 ×1.02 后各写 102.04，最后写者胜，实际只调了一次；更糟的是两者读到不同的中间值时会产生非预期的最终价。

### 3.6 【低危】逻辑冗余与计数缺陷

- **`MODIFY gt_jobs FROM ls_job` 在 `LOOP AT gt_jobs` 内部是多余的**。标准表 + `EMPTY KEY`，`MODIFY` 只改了当前行——而后续循环读的每一行都是原始行（本次循环内没有任何别的逻辑依赖 `gt_jobs` 的写回），所以这个语句**对外没有任何可观察的业务效果**，只对循环结束后的整表状态有影响，而整表状态又没有任何地方使用。它会误导读者以为"逐行落库到内部表是有意义的"。
- **`gv_run` 计数错位**：`INITIALIZATION` 里 `gv_run = 1`，循环内 `gv_run = gv_run + 1`，N 行后 `gv_run = N + 1`。日志里的 `run` 值永远比实际行数大 1，对账时会误导。
- **`gv_ok / gv_failed` 语义反了**：测试模式下所有记录都进 `gv_failed`，于是 dry run 的输出是 `ok 0 failed 120000`。实际上**没有任何一条失败**，只是没写库。作业日志里出现 `failed 120000` 会让运维误判为事故，久而久之对失败计数脱敏。
- **`status = 'X'` 语义不明且无人读取**，测试模式下也被置 `X`——"已处理"到底指"已算"还是"已写库"无法区分。
- **无进度输出**：整个取数阶段和大部分循环没有任何输出，作业日志在几十分钟内完全空白。只在最后 `WRITE` 一次。超过作业最大运行时（默认 8h/可配）或被监控盯上超时，无法判断是"卡住"还是"在跑"。
- **无时间戳、无系数、无工厂/币种维度汇总**：调价是一次财务口径的价格调整，但日志里没有"本次系数 = 1.02""执行时间 = 2026-10-02 01:03:11""分工厂影响行数"，**事后无法重建当晚到底改了什么**。

---

## 四、提交逻辑（`FORM finalize`，行 92-108）

```abap
FORM finalize.

  IF p_test EQ 'X'.
    MESSAGE 'Test mode - no data written' TYPE 'S'.
    RETURN.
  ENDIF.

  IF p_commit EQ 'X'.
    COMMIT WORK.
    WRITE: / 'committed'.
  ENDIF.

  IF gv_batch EQ abap_true.
    WRITE: / 'batch run finished'.
  ENDIF.

ENDFORM.
```

### 4.1 【高危】"是否提交"由一个勾选框决定

```abap
IF p_commit EQ 'X'.
  COMMIT WORK.
ENDIF.
```

后台运行的 LUW 在对话步结束时由框架隐式提交。也就是说：

- **勾选 `p_commit` → 显式提交**（正常路径）。
- **未勾选 `p_commit` → 对话步结束，框架仍会隐式 `COMMIT WORK`**。

也就是说 `p_commit` 在后台模式下**几乎不起"不提交"的作用**，却让人误以为它是一个安全开关——它真正的语义变成了"**是否打一行 `committed` 日志**"。这是一个危险的语义错位：维护者以为"忘了勾 = 保险不落库"，实际后台照样落库；反过来，前台运行时 `COMMIT WORK` 是**真实阻断式提交**，前台未勾选则依赖对话步结束提交，行为与后台不一致。

更隐蔽的一种情况：如果这个报表未来被嵌进一个 SM36 **作业步骤链**（Job Steps）中，`COMMIT WORK` 会**终止后续所有步骤**，且无法通过 SM37 正常处理。

**建议**：把"提交"从用户可见参数里拿掉，改为显式的运行模式参数（`p_mode ∈ {TEST, DRY, COMMIT}`），或者用 `COMMIT WORK AND BACKJOB` 在分批后台模式下提交，且把"本次调价是否已提交"作为一条**程序自己写入的运行头状态**记录在案，而不是靠参数推演。

### 4.2 【高危】无分批 = 单事务巨型 LUW

配合 3.3：`COMMIT WORK` 是全程序**唯一一次**提交点。这意味着：

- 原子性上"要么全改要么全不改"，看起来安全；但代价是**长事务**（数小时级锁 + 海量 undo + 提交阶段尖峰）；
- 后台作业的最大运行时一旦被触发，或 DB 在提交前重启，**全部回滚**；
- 没有"断点续跑"能力：作业重启必然从头开始，配合 3.2 的累涨 = 灾难。

标准改法（牺牲全局原子性，换取可运行性）：

```abap
DATA lv_done TYPE i.

LOOP AT gt_jobs INTO DATA(ls_job).
  ...
  MODIFY zprice_log FROM ls_log.   " 逐行留痕，失败可追溯
  IF sy-unix MOD 1000 = 0.          " 每 1000 行一个提交点
    COMMIT WORK.
    lv_done = lv_done + 1000.
  ENDIF.
ENDLOOP.
COMMIT WORK.
```

同时把 `lv_done` 写进日志表头，使作业重启后可以从断点继续而不是重复计利。

### 4.3 提交阶段的其它问题

- `p_test EQ 'X'` 与 `recalculate` 里 `p_test IS INITIAL` **判断风格不一致**（同一参数两种写法）。虽等价（checkbox 是 `c` 型，空即 `' '`），但同一份 108 行代码里两种风格并存，是维护性隐患。
- **`gv_batch` 判定后只做了一件事：打印一行日志**。整个"识别后台并相应行为"的设计，实际内容只有"因子不同 + 多打一行字"。没有后台该有的保护（消息类型、强制错误日志、禁止交互、拆分批次）。而且 `gv_batch` 与 `sy-batch` 是**同一事实的两个来源**（行 38 判定 `sy-batch`，行 71 又直接用 `sy-batch`），双真值源必然在后续维护中走偏。
- `COMMIT WORK` 之后没有输出提交影响行数、提交耗时，没有做提交后的结果自检（例如重新读一条确认已落库）。

---

## 五、后台运行风险专章

按"发生概率 × 影响"排序。

### 风险 1 —— 空结果被记为成功（概率高 / 影响高）

已见 2.3。触发条件：物料范围写错、变体丢失、SAP 上物料已停用。作业"绿"，价格未调。**必须改为后台抛错**。

### 风险 2 —— 调价系数随运行模式变化（概率 100% / 影响高）

已见 3.1。后台 2%、前台 5%。**必须把系数外化为参数或配置表**。

### 风险 3 —— 重复执行复利累涨（概率中 / 影响极高且不可逆）

已见 3.2。**必须有幂等键 + 运行头锁 + 流水表**。

### 风险 4 —— 参数留空导致全表扫描（概率中 / 影响高：拖垮应用服务器）

已见 2.2。缓解：`OBLIGATORY` + `AT SELECTION-SCREEN` 校验 + 后台从变体取数并在 `INITIALIZATION` 断言非空 + 限定工厂 + 对预估行数设上限。

### 风险 5 —— 单事务巨型 LUW / 一错全崩（概率中 / 影响中-高）

已见 3.3 + 3.4。缓解：批下发 `MODIFY ... FROM TABLE`、分批提交、`TRY/CATCH`、落盘失败清单。

### 风险 6 —— 与月末重估/价格确定的并发冲突（概率取决于排期 / 影响高）

月末 `CK24/CK40`、`MR21` 或标准价重算与本作业撞在一起：一条 `MARC-STPR` 重算，一条 `NETPR` 上调，两者并发还有**互相覆盖**与**标准价/参考价分叉**。缓解：给作业加"业务日期窗口"校验（后台模式下从变体取日期，月末期间拒绝执行并要求人工确认），以及与 `ZPRICE` 家族作业的作业级互斥锁。

### 风险 7 —— 锁冲突导致 dump、且无失败清单（概率中 / 影响中）

已见 3.4。缓解同上。

### 风险 8 —— 无日志、无审计轨迹（概率 100% / 影响中高）

日志只有 `run N ok N failed N`（且 `run` 还差 1）和 `committed`。缺：执行时间、系数、选区、影响行数按工厂/币种分布、失败明细、前后价格汇总。**财务口径的价格调整缺少可追溯记录，是审计缺陷。**

### 风险 9 —— 长时间无输出的"假死"（概率中 / 影响中）

见 3.6。加进度输出（`WRITE: /` 定期进度 或 spool 中的进度行）与运行时监控。

### 风险 10 —— 与价格确定（条件记录）口径不一致（概率视集成而定 / 影响高）

见 2.1。直写 `MARC-NETPR` 不同步 `EKKP/EKKN`。若采购侧价格仍来自条件记录，则本程序**改了但没生效**，或者更糟：改的是"影子价"，报表与实际采购价长期背离。**这是需要业务方书面确认的口径问题。**

### 风险 11 —— `STPR` 未同步导致成本口径分叉（概率 100% / 影响中）

同上，只改 `NETPR`。若后续成本核算取 `STPR`，则成本、差异、报价三者与采购价不一致。

### 风险 12 —— 币种/单位维度未处理（概率中 / 影响中）

`NETPR` 是"每价格单位"的价格。程序读取了 `waers` 但**从未使用**；也未读取 `MARC-UPEIN/UMREN`。若选区内存在不同价格单位（`PR00` vs `PR01`，如 `TOG`、`KG`、`L` 各异）的物料，按固定比例上调虽在数学上等价，但**审核人无法在日志中看到币种分布**，很难发现"某个币种/某个价格单位被误纳入了选区"。建议至少在日志里输出按币种、价格单位的分组行数。

---

## 六、代码质量与风格问题汇总

| # | 位置 | 问题 |
|---|---|---|
| 1 | 8-16 | 用 `ty_job` 投影结构替代 DDIC 结构/字典结构（`zprice_btch`），丧失 F1 帮助、类型联动与可维护性 |
| 2 | 8-18 | `ty_job_tab` 用 `STANDARD TABLE ... WITH EMPTY KEY`，本身没问题，但 `MODIFY` 在循环内毫无意义 |
| 3 | 25 | `gv_commit` 死变量 |
| 4 | 28 | `SELECT-OPTIONS ... FOR gt_jobs-matnr` 让参数依赖全局内表，与结果集耦合 |
| 5 | 49-53 | `waers <> ' '` 无操作条件；无 `werks`/`datnr` 过滤 |
| 6 | 56-57 | 后台空结果用 `TYPE 'S'` + `LEAVE TO CURRENT TRANSACTION`（见风险 1） |
| 7 | 65 | `lv_factor` 在 `FORM` 头声明但在循环内重复赋值（作用域错位） |
| 8 | 69-70 | `gv_run` 初值 1 + 循环加 1 → 计数偏移 |
| 9 | 71 | 因子依赖 `sy-batch`（见风险 2） |
| 10 | 73 | 就地取当前价做基准 → 累涨（见风险 3） |
| 11 | 76 | 循环内 `MODIFY gt_jobs` 冗余 |
| 12 | 78-83 | 无 `TRY/CATCH`；`gv_failed` 语义错误；逐行单条 MODIFY |
| 13 | 87 | 无时间/系数/分组维度，仅一行计数 |
| 14 | 94 vs 78 | `EQ 'X'` 与 `IS INITIAL` 两种判断风格混用 |
| 15 | 99-102 | 提交动作由参数控制，语义错位（见 4.1） |
| 16 | 104-106 | `gv_batch` 与 `sy-batch` 双真值源；后台分支仅打一行日志 |
| 17 | 全程序 | 无 `AT SELECTION-SCREEN` 输入校验、无 `LOCK OBJECT`、无应用日志（`BAL1_LOG`）、无后台模式消息规范 |

---

## 七、重构建议（含参考代码）

### 7.1 参数外化（消除风险 2）

```abap
TYPES: BEGIN OF ty_modo,
         mtok TYPE c LENGTH 1,   " T=test, R=run, C=run+commit
       END OF ty_modo.

PARAMETERS p_factor TYPE p DECIMALS 4 DEFAULT 1.02.
PARAMETERS p_mode   TYPE c LENGTH 1 DEFAULT 'C' NO-DISPLAY.
```

系数从此只来自变体/参数，前后台完全一致，且进日志可审计。

### 7.2 幂等 + 流水表（消除风险 3）

```abap
" 运行头：唯一性靠 PRIMARY KEY mandt + run_id
" 运行头：另存 CHAR10 last_success_date，做当日重复执行拦截
DATA ls_hdr TYPE zprice_log_hdr.
ls_hdr-mandt       = sy-mandt.
ls_hdr-run_id      = |{ sy-uname }{ sy-datum TIME sy-uzeit }|.
ls_hdr-factor      = p_factor.
ls_hdr-create_date = sy-datum.
ls_hdr-create_time = sy-uzeit.
ls_hdr-jobname     = SYSTEM-FIELD sy-batch.
INSERT zprice_log_hdr FROM ls_hdr.

" 明细：old/new/factor/run_id
DATA ls_det TYPE zprice_log_det.
ls_det-mandt       = sy-mandt.
ls_det-run_id      = ls_hdr-run_id.
ls_det-matnr       = ls_job-matnr.
ls_det-werks       = ls_job-werks.
ls_det-waers       = ls_job-waers.
ls_det-price_old   = lv_price_old.
ls_det-price_new   = lv_price_new.
ls_det-factor      = p_factor.
MODIFY zprice_log_det FROM ls_det.
```

配合运行头唯一键 + `SELECT ... FOR UPDATE`，重复执行会在第一行就 ABORT，杜绝累涨。

### 7.3 分批提交 + 异常捕获 + 批下发（消除风险 5、7、8）

```abap
DATA lt_upd  TYPE ty_job_tab.   " 待写入的 MARC 行
DATA lt_fail TYPE ty_job_tab.

LOOP AT gt_jobs INTO DATA(ls_job).
  lv_price_old = ls_job-netpr.
  ls_job-netpr = lv_price_old * p_factor.     " p_factor 在 FORM 头只算一次

  APPEND ls_job TO lt_upd.

  IF lines( lt_upd ) >= 1000.
    PERFORM flush CHANGING lt_upd lt_fail.
  ENDIF.
ENDLOOP.

PERFORM flush CHANGING lt_upd lt_fail.
COMMIT WORK.


FORM flush CHANGING ct_upd TYPE ty_job_tab
                  ct_fail TYPE ty_job_tab.
  DATA lt_keys TYPE ty_job_tab.
  lt_keys = CORRESPONDING #( ct_upd ( matnr werks ) ).

  TRY.
      MODIFY marc FROM TABLE ct_upd MATCHING KEY ( matnr werks ).
      COMMIT WORK.
    CATCH cx_root INTO DATA(lx_err).
      " 整批失败：退化为逐行重试，定位真正的问题行
      LOOP AT ct_upd INTO DATA(ls_bad).
        TRY.
            MODIFY marc FROM ls_bad.
          CATCH cx_root INTO DATA(lx_row).
            ct_fail = VALUE #( ( ( matnr = ls_bad-matnr
                                    werks = ls_bad-werks
                                    status = 'E' ) ) ).
            APPEND ls_bad TO ct_fail.
        ENDTRY.
      ENDLOOP.
      ROLLBACK WORK.
  ENDTRY.

  ct_upd = VALUE #( ( ) ).
ENDFORM.
```

### 7.4 输入校验与行数护栏（消除风险 4）

```abap
AT SELECTION-SCREEN ON VALUE-REQUEST FOR s_matnr.
  " 物料号 F4 帮助接入 MM_HMATNR / MM_MATERIAL（可选）

INITIALIZATION.
  IF sy-batch = 'X'.
    IF s_matnr[] IS INITIAL OR s_matnr-low IS INITIAL.
      MESSAGE 'Material range is mandatory in batch mode' TYPE 'E'.
    ENDIF.
  ENDIF.
```

并在取数后立即做行数上限判断，超过阈值直接 ABORT 而不是硬扛：

```abap
IF lines( gt_jobs ) > 200000.
  MESSAGE |Too many rows ({ lines( gt_jobs) }). Aborted.| TYPE 'E'.
ENDIF.
```

### 7.5 后台消息规范

- 所有异常路径：后台 → `MESSAGE ... TYPE 'E'` 或 `'A'`；前台 → `'S'` + `LEAVE PROGRAM.`
- 成功路径：后台 → 输出一行结构化摘要（时间/系数/行数/工厂数/币种数），并确保 SM37 能识别；
- 失败清单：落 `ZPRICE_LOG_DET`，作业日志给出前 20 条失败 + 完整清单的查询方法。

### 7.6 加锁与排期

```abap
LOCK OBJECT zprice_batch_lock IN SHARE MODE.
```

并让 `zprice_batch_lock` 与月末重估（`CK24/CK40/MR21`）互斥；作业变体里固定排期窗口并写入程序注释。

---

## 八、上线前验证清单

| # | 检查项 | 方法 |
|---|---|---|
| 1 | 后台与前台调价结果一致 | 同一选区两种模式各跑一次 test，比对 `gt_jobs`（需先把因子外化） |
| 2 | 重复执行不改变结果 | 连跑两次，比对价格；应被运行头锁 ABORT |
| 3 | 空选区在后台变红 | 用不存在的物料范围后台执行，确认 SM37 状态为失败 |
| 4 | 变体丢失时程序拒绝启动 | 删掉 `s_matnr` 后台启动，确认 ABORT 而非全表扫描 |
| 5 | 失败行不导致整体回滚 | 人工对一个物料加排他锁，执行，确认其余行落库且失败清单完整 |
| 6 | 10 万行规模下运行时长与内存 | 压测，记录运行时长、峰值内存、DB CPU |
| 7 | 提交与回滚行为符合预期 | 前台/后台各验证一次 `p_commit` 的真实语义 |
| 8 | `STPR` / 条件记录口径确认 | 与业务书面确认改哪张表、由谁同步 |
| 9 | 与月末重估不冲突 | 查作业排期，确认互斥 |
| 10 | 审计口径 | 确认日志/流水表能回答"某个物料某天被调了几次、每次比例多少" |

---

## 九、一句话总结

`zprice_batch` 是一个结构清爽、但**后台安全性和可审计性都不达标**的最小可用程序：它把业务规则（调价比例）藏在运行方式里，把事务边界押在一个勾选框上，把幂等性寄托在"作业不会跑第二遍"上，把审计寄托在"日志里有三个计数器"上。上线前至少要做三件事——**系数参数化、加运行头幂等锁与流水表、空结果/大结果让后台变红**；性能上则把逐行 `MODIFY` 改为分批 `MODIFY ... FROM TABLE` 并分批提交。