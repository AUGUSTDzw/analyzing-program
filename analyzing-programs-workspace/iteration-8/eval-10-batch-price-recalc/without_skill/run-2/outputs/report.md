# 夜间调价程序 `zprice_batch` 分析报告

> 分析对象：`D:\Workspace\Skills\analyzing-programs\evals\zprice_batch.abap`（108 行）
> 分析重点：取数（`read_prices`）、调价（`recalculate`）、提交（`finalize`）、后台运行风险
> 结论速览：**该程序在前台与后台运行时会采用不同的调价系数（1.05 vs 1.02），这是本程序最严重的业务风险；此外全量 MARC 读入内存、逐行 UPDATE、提交依赖参数与隐式提交、错误全部被吞掉，四个问题叠加后不适合直接作为无人值守的夜间作业运行。**

---

## 1. 程序骨架

### 1.1 结构一览

| 区块 | 行 | 作用 |
| --- | --- | --- |
| 类型定义 | 8-18 | `ty_job`（近似 MARC 的行结构 + 一个 `status` 字段）、`ty_job_tab`（STANDARD TABLE，WITH EMPTY KEY） |
| 全局变量 | 20-25 | `gt_jobs` 工作表、`gv_run/gv_ok/gv_failed` 计数器、`gv_batch` 后台标志、`gv_commit` **声明后从未使用** |
| 选择屏幕 | 27-31 | `s_matnr`（SELECT-OPTIONS，可多值/范围）、`p_test`、`p_commit` 两个 CHECKBOX |
| INITIALIZATION | 33-34 | 只做 `gv_run = 1` |
| START-OF-SELECTION | 36-44 | 判定 `sy-batch` → 顺序 `PERFORM` 三段，无任何错误处理 |
| FORM read_prices | 47-60 | 从 MARC 读价格 |
| FORM recalculate | 63-89 | 逐行加系数、写回 MARC、计数 |
| FORM finalize | 92-108 | 测试模式返回 / 可选 COMMIT / 后台提示 |

### 1.2 主流程

```abap
INITIALIZATION.
  gv_run = 1.                       "← 计数器初值放在 INITIALIZATION，语义不清

START-OF-SELECTION.

  IF sy-batch = 'X'.
    gv_batch = abap_true.
  ENDIF.

  PERFORM read_prices.              " 取数
  PERFORM recalculate.              " 调价 + 直接写库
  PERFORM finalize.                 " 提交（可选）
```

三个 FORM 之间**没有返回值、没有异常传递、没有成功标志**，`START-OF-SELECTION` 里也没有 `sy-subrc` 检查。三段是典型的"顺序脚本"，不是可复用的子程序。

---

## 2. 取数逻辑（`read_prices`）

```abap
FORM read_prices.

  SELECT matnr werks netpr waers eintr datnr
    FROM marc
    INTO TABLE gt_jobs
    WHERE matnr IN s_matnr
      AND waers <> ' '.

  IF gt_jobs IS INITIAL.
    MESSAGE 'No price records found' TYPE 'S'.
    LEAVE TO CURRENT TRANSACTION.
  ENDIF.

ENDFORM.                       "read_prices
```

### 取数阶段的问题

1. **只按物料号过滤，不按工厂过滤（后台高危）**
   `matnr IN s_matnr` 不含 `werks`，一个物料若有 5 个工厂 View，SELECT 就会返回 5 行，逐行写回 5 次。功能上不算错（`MODIFY MARC` 用完整主键 MATNR+WERKS 定位，不会误更新），但会把处理量和锁持有时间放大数倍。

2. **`s_matnr` 留空 = 读全表 MARC（后台致命）**
   SELECT-OPTIONS 默认为空，`matnr IN <空范围>` 语义是"不过滤"。夜间作业如果调度参数没带物料范围，程序会把**整张 MARC 表**（生产系统通常数千万到上亿行）一次性 `INTO TABLE` 装入 ABAP 内存，后果是内存耗尽 / RESOURCE_EXCEEDED 转储，或跑数小时不结束被作业时限杀掉。

3. **`waers <> ' '` 是一条死条件**
   MARC-WAERS 在数据字典中为 NOT NULL，不存在初始值，该条件恒为真，不起任何过滤作用。

4. **缺少价格有效性过滤（业务逻辑缺陷）**
   `eintr`（有效期至）和 `datnr`（有效期起）被 SELECT 出来，却在 `recalculate` 里**从未被使用**。结果：已过期的价格和未来才生效的价格同样会被调价。价格有效期是这个程序的核心业务维度，代码里完全没有体现。

5. **缺少业务范围过滤**
   没有 `mvprt = 'X'`（价格相关视图）、没有 `mpro <> 'X'`（非预测）、没有排除统计价格/删除物料/停用工厂等必要限定，等于把所有 MARC 行都当"要调价的有效价格"。

6. **`LEAVE TO CURRENT TRANSACTION` 不适合后台**
   这是交互式事务特有的语句。在后台模式下它会直接终止整个程序（不是 `RETURN`），且规范上明确禁止在批处理中使用。空结果时后台会静默结束、不输出统计、不写日志，运维只会看到作业"成功完成但什么都没有"。

7. **选择屏幕引用了会被覆盖的字段**
   `SELECT-OPTIONS s_matnr FOR gt_jobs-matnr` 引用了 `gt_jobs` 的组件，而 `read_prices` 随即用 `INTO TABLE gt_jobs` 整表覆盖。这里不会出错（`s_matnr` 是独立对象），但它暗示了一种"屏幕绑定工作表"的错误心智模型，属于应当消除的坏味道。

---

## 3. 调价逻辑（`recalculate`）

```abap
FORM recalculate.

  DATA lv_factor TYPE p DECIMALS 4.

  LOOP AT gt_jobs INTO DATA(ls_job).        " ← INTO 的是副本，不改源表

    gv_run = gv_run + 1.                     " ← 计数器 off-by-one

    lv_factor = COND #( WHEN sy-batch = 'X' THEN 1.02 ELSE 1.05 ).   " ← 前后台不同系数

    ls_job-netpr  = ls_job-netpr * lv_factor.
    ls_job-status = 'X'.                     " ← 永远 'X'，无实际意义

    MODIFY gt_jobs FROM ls_job.              " 把结果写回内存表

    IF p_test IS INITIAL.
      MODIFY marc FROM ls_job.               " ← 逐行 UPDATE，无 sy-subrc 检查
      gv_ok = gv_ok + 1.
    ELSE.
      gv_failed = gv_failed + 1.             " ← 测试模式全记为 failed
    ENDIF.

  ENDLOOP.

  WRITE: / 'run', gv_run, 'ok', gv_ok, 'failed', gv_failed.

ENDFORM.
```

### 3.1 调价阶段的问题

1. **【P0】调价系数依赖运行方式 —— 前后台结果不可复现**
   `sy-batch = 'X'` 时涨价 2%，否则涨价 5%。这意味着：

   - 夜间作业涨 2%，运维/业务在 SA38 里"手动跑一次看看效果"，实际涨 5% 并直接写库；
   - 同一批数据在开发/测试（前台）与生产（后台）结果不同，问题无法用"复现"来定位；
   - 后台作业重跑一次仍是 2%，前台重跑一次变 5%，**没有任何提示能区分**；
   - `gv_batch` 在 `START-OF-SELECTION` 里已经算好了，`recalculate` 却绕过它直接读 `sy-batch`，形成两个真相来源（`finalize` 又用 `gv_batch`），代码自相矛盾。

   这是典型的"调试手段污染业务逻辑"，必须改成外部可配置参数（Customizing 表 / 变式 / 授权对象参数），而不是靠 `sy-batch` 猜。

2. **【P0】逐行 `MODIFY marc`，无 `sy-subrc` 检查**
   - 循环内对 MARC 发 N 次单行 UPDATE。上百万行会产生上百万次数据库往返，夜间作业跑几小时是必然的。
   - `MODIFY marc FROM ls_job.` 的 `sy-subrc` **完全没有检查**。主键不存在、数据库更新失败（如 `SAPSQL_UPDATE_LOCK`、字段长度溢出、更新冲突）都会被静默吞掉，并且照样 `gv_ok + 1`。**日志显示 ok=999999，实际可能只有一半成功。**
   - `status` 字段永远写死 `'X'`，本该承载成功/失败标记，实际是死字段。

3. **【P1】`MODIFY marc FROM ls_job` 的字段副作用**
   `ls_job` 含 `waers/eintr/datnr`，这些字段会以原值被写回数据库，等于把不变字段也纳入 UPDATE 语句。更重要的是：**`MODIFY MARC FROM wa` 只更新工作区里包含的字段，所以 `MARC-ERNAM/ERDAT` 不会被更新** —— 这既是好事（不污染审计字段），也是坏消息：**谁在什么时候把价格调了多少，没有任何痕迹**（见 §6.5）。

4. **【P1】价格计算缺少精度与合理性控制**
   - `netpr * lv_factor` 直接落到 `MARC-NETPR`（CURR 15,3），靠目标字段的小数位隐式舍入，未做显式 `ROUND` 到 SAPLC/NTC 价格单位；
   - 未校验 `netpr = 0`、负价格、超高倍数；调价后是否触及价格上限也未检查；
   - 没有金额上下限、没有"单次最大涨幅"熔断，任何配置写错都会直接落到生产价格上。

5. **【P1】`gv_run` 计数器 off-by-one**
   `INITIALIZATION` 置 1，循环内先 `+1` 再处理，于是结束时 `gv_run = 行数 + 1`。输出 `run 500001` 而真实处理 500000 行。测试模式下会输出 `run 500001 ok 0 failed 500000` 这种自相矛盾的行，直接误导运维判断。

6. **【P2】`MODIFY gt_jobs FROM ls_job` 是无效代码**
   `LOOP AT ... INTO` 拿到的是副本，`ls_job-status/netpr` 只存在于 `ls_job` 里；`MODIFY gt_jobs` 按主键（MATNR+WERKS）写回，虽然能跑通，但这一步只是为了把算完的价格留在内存表里，而该表此后再也不被读取（`finalize` 只看 `p_test/p_commit/gv_batch`）。既无用途，又让读者误以为后面还会用到调价结果。若确实需要保留结果，应改用 `ASSIGNING`：

   ```abap
   LOOP AT gt_jobs ASSIGNING FIELD-SYMBOL(<job>).
     <job>-netpr = <job>-netpr * lv_factor.
     ...
   ENDLOOP.
   ```

7. **【P2】`p_test` 的计数语义反了**
   测试模式下所有记录计入 `gv_failed`，测试跑 10 万条就打印 `failed 100000`，看起来像"全军覆没"。测试模式应该单独用 `simulated/skipped` 计数，或干脆输出"待处理条数"。

---

## 4. 提交逻辑（`finalize`）

```abap
FORM finalize.

  IF p_test EQ 'X'.
    MESSAGE 'Test mode - no data written' TYPE 'S'.
    RETURN.
  ENDIF.

  IF p_commit EQ 'X'.
    COMMIT WORK.                       " 一次性提交，无中间提交
    WRITE: / 'committed'.
  ENDIF.

  IF gv_batch EQ abap_true.
    WRITE: / 'batch run finished'.      " 与是否真正提交无关
  ENDIF.

ENDFORM.
```

### 4.1 提交阶段的问题

1. **【P0】提交由勾选框决定，默认靠"程序正常结束时隐式 COMMIT"**
   调度时若漏勾 `p_commit`，程序仍会跑完并打印 `batch run finished`，真正的落库依赖 `START-OF-SELECTION` 正常退出时的隐式 `COMMIT WORK`。这意味着**提交成败与作业状态无关**：只要中途转储（DUE/TSV/内存/更新冲突），整个 LUW 被回滚，夜间工作**全部丢失且只留下一条转储日志**。反过来讲，运维从作业日志里完全看不出"数据到底落没落库"。

2. **【P0】全量数据在单个 LUW 内，单次提交**
   假设 200 万行更新全部在一个数据库 LUW 中：

   - 回滚段/UNDO 表空间压力巨大，可能触发 `ORA-01555`/SQL Server 日志膨胀或 SAP 表空间不足；
   - 从第一次 `MODIFY` 起就持有 MARC 行锁，直到程序结束。若夜间时段有用户（或另一个批处理）在 MM03 里改同一物料价格，就会锁超时/更新冲突；
   - 作业时限（`rdisp_max`）或 `time_limit` 一旦触发，进程被杀 → 全量回滚 → 一晚上白跑。

   正确做法是**分批提交**（按 `PACKAGE SIZE` 或按工厂/物料段），让每批成为独立的 LUW。

3. **【P1】`COMMIT WORK` 是不可逆的，且没有任何提交前校验**
   `finalize` 不检查 `gv_failed`、`gv_ok` 是否合理，也不检查是否有行处理失败，直接提交。即使一半行更新失败，落库的部分照样生效，事后无法区分。

4. **【P1】提交后没有留下任何可核对的输出**
   `WRITE: / 'committed'` 只说明执行到了 `COMMIT WORK` 语句，不说明写了多少行。**没有行数、没有耗时、没有成功/失败清单、没有消息号**。夜间作业出问题后基本无法复盘。

5. **【P2】`MESSAGE ... TYPE 'S'` 在后台不合适**
   成功消息写进作业日志（勉强可接受），但错误路径里**没有任何** `TYPE 'E'/'A'` 或 `ABORT`，因此无论数据是否写入，作业在 SM21/SM37 里都是"成功结束"。这是最容易被忽略、也最危险的一点：**作业状态不能反映业务结果**。

6. **【P2】`gv_commit` 声明未使用** —— 说明原本设计里对提交控制有想法，但实现没跟上（死变量）。

7. **【P2】`p_test EQ 'X'` 与 `p_test IS INITIAL` 两种判空风格混用**（`finalize` 用 `EQ 'X'`，`recalculate` 用 `IS INITIAL`）。语义等价但风格分裂，修改时容易出错。

---

## 5. 后台运行风险清单（按优先级）

| # | 等级 | 风险 | 触发条件 | 后果 |
| --- | --- | --- | --- | --- |
| R1 | **P0** | 前后台调价系数不同（1.02 / 1.05） | 任何前台复跑、调试、开发系统验证 | 价格被错误调高 5%，且无提示 |
| R2 | **P0** | `s_matnr` 为空 → 全表 MARC 读入内存 | 调度参数漏传物料范围 | `RESOURCE_EXCEEDED` 转储 / 跑数小时被杀 |
| R3 | **P0** | 全量更新在单个 LUW，仅在勾选 `p_commit` 时显式提交 | 任意中途转储或作业被取消 | 夜间结果全量回滚，且日志显示"成功" |
| R4 | **P0** | 无 `sy-subrc` / 无 `TRY-CATCH`，DB 更新失败被静默吞掉并计入 `gv_ok` | 锁冲突、主键异常、字段溢出 | 数据部分更新但日志报告全成功 |
| R5 | **P1** | 无时间有效性过滤（`datnr`/`eintr` 读出未用） | 每晚运行 | 已过期/未来价格被调价，业务口径错乱 |
| R6 | **P1** | 缺 `MESSAGE TYPE 'E'` / ABORT，作业状态恒为成功 | 任何异常 | 监控无法发现失败，无告警 |
| R7 | **P1** | 无 `AUTHORITY-CHECK` | 任何持有 SA38/SAA1 的用户 | 任意人可改全系统价格 |
| R8 | **P1** | 逐行 `MODIFY`，长事务持锁 | 大数据量 + 白天有 MM03 操作 | 运行数小时、行锁与业务操作冲突、超时 |
| R9 | **P1** | 无应用日志（`BAL_LOG_API`）、无变更原因、无操作人记录 | 日常运行 | 无法审计"谁在何时把价格调了多少" |
| R10 | **P2** | 空结果用 `LEAVE TO CURRENT TRANSACTION` | 后台查不到数据 | 后台静默退出，违反批处理规范 |
| R11 | **P2** | 计数器 off-by-one + 测试模式记为 failed | 任何一次运行 | 运维被日志误导 |
| R12 | **P2** | `status` 死字段、`gv_commit` 死变量、无效 `MODIFY gt_jobs` | — | 维护者误判程序行为 |

### 后台运行的三个"静默失败"场景

**场景 A：调度时忘了勾 `p_commit`**
程序跑完，打印 `batch run finished`，作业绿色。数据靠隐式提交落库，**这次是侥幸成功**。下一次作业中途超时被系统杀掉，进程退出 → LUW 回滚 → 作业日志里只有一条超时信息，没有任何"数据丢了"的提示。而运维无法区分这两种情况。

**场景 B：调试时前台跑了一把**
运维发现夜间价格"好像没涨够"，在 SA38 里前台执行一次同一变式。程序用 1.05 而不是 1.02，直接把生产价格写高了 3 个百分点，然后系统正常提示"已提交"。**没有任何机制能告诉运维他跑错了模式。**

**场景 C：部分行更新失败**
前 30 万行成功，第 30 万零 1 行因为行锁超时失败（`MODIFY` 的 `sy-subrc <> 0` 被忽略），剩余行继续成功。日志显示 `ok 1000000 failed 0`，实际数据库里 999999 行已改、1 行没改，且已整体提交。**错误被永久掩盖。**

---

## 6. 需要业务方确认的疑点

1. **改 `MARC-NETPR` 是否真的等于改了销售价？**
   `MARC-NETPR` 是"记录价格/参考价"，实际对外销售价通常来自条件记录（`PRICING` / `KKDAT`/`KCOND`，或 `COND` 体系）。如果条件记录是手工维护或由其它价格过程生成的，那么这个夜间程序改完 MARC-NETPR 之后，**客户看到的售价可能根本没变**。请先确认业务诉求到底落在哪一层，否则这个作业可能是一个跑了很久却不生效的"空转"程序。

2. **`MARC-NETPR` 与 `MARC-STDAF`/定价相关的 `STDAB`、含税/不含税口径（`MARC-NETPR` 通常为不含税）**是否需要同步调整。

3. **1.02 / 1.05 的差异是业务有意为之，还是遗留的调试代码？** 若是有意为之，必须写进配置并留下文档；若是遗留，必须删除。

4. **调价的适用物料范围、工厂范围、是否区分价格组/销售视图**应从选择屏幕或配置中读取，而不是硬编码"全量 MARC"。

---

## 7. 修改建议

### 7.1 后台模式强制前置校验（P0）

```abap
START-OF-SELECTION.

  gv_batch = COND #( WHEN sy-batch = 'X' THEN abap_true ELSE abap_false ).

  IF sy-batch = 'X' AND s_matnr[] IS INITIAL.
    MESSAGE '后台运行必须通过 s_matnr 限定物料范围，禁止全量 MARC' TYPE 'E'.
    RETURN.
  ENDIF.

  IF NOT AUTHORITY-CHECK 'MARC' OBJECT 'MARC' ID 'MATNR' DUMMY.
    " 或改用自定义授权对象，控制"调价"动作
  ENDIF.
```

### 7.2 取数：加业务过滤、只取必要字段

```abap
FORM read_prices.

  SELECT matnr werks netpr waers eintr datnr
    FROM marc
    WHERE  matnr IN s_matnr
      AND  werks IN s_werks            " 增加工厂选择
      AND  mvprt  = 'X'                " 仅价格相关视图
      AND  mpro  <> 'X'
      AND  datnr >= sy-datum            " 只调价已生效价格
      AND  eintr >= sy-datum            " 未过期的价格
    INTO  TABLE @gt_jobs.

  IF sy-subrc <> 0.
    MESSAGE '取数失败，请检查选择条件与表锁' TYPE 'E'.
    LEAVE LIST-PROCESSING.
  ENDIF.

  IF gt_jobs IS INITIAL.
    MESSAGE '没有符合条件的调价记录' TYPE 'S'.
    RETURN.                            " 后台不用 LEAVE TO CURRENT TRANSACTION
  ENDIF.

ENDFORM.
```

### 7.3 调价：系数外置 + 分批 + 检查 sy-subrc

```abap
FORM recalculate.
  DATA: lv_factor TYPE p DECIMALS 4,
        lv_budget  TYPE i.

  " 系数来自配置/自定义表，不再依赖 sy-batch
  READ TABLE tc_price_factor INTO DATA(ls_f) WITH KEY ftype = 'NIGHT'.
  IF sy-subrc <> 0.
    MESSAGE '未配置夜间调价系数，程序终止' TYPE 'E'.
    RETURN.
  ENDIF.
  lv_factor = ls_f-factor.             " 例如 1.02

  LOOP AT gt_jobs ASSIGNING FIELD-SYMBOL(<job>).

    <job>-netpr = ROUND( <job>-netpr * lv_factor, 3 ).   " 显式舍入到 NETPR 的 3 位小数

    IF <job>-netpr <= 0 OR <job>-netpr > ls_f-max_price.
      <job>-status = 'E'.              " 越界不写库
      gv_failed = gv_failed + 1.
      CONTINUE.
    ENDIF.

    IF p_test IS INITIAL.
      MODIFY marc FROM <job>-*.
      IF sy-subrc = 0.
        <job>-status = 'X'.
        gv_ok = gv_ok + 1.
      ELSE.
        <job>-status = 'E'.
        gv_failed = gv_failed + 1.
      ENDIF.
    ELSE.
      <job>-status = 'S'.              " 测试模式：simulated，不要记成 failed
    ENDIF.

  ENDLOOP.

  " 结果落应用到日志，便于事后审计
  " CALL FUNCTION 'BAL_LOG_API' ...

ENDFORM.
```

> 注意 `MODIFY marc FROM <job>-*`：如果改为 `MODIFY marc FROM TABLE` 的写法，内部表结构必须与 MARC 字段一一对应，不能直接用带 `status` 的 `ty_job`。稳妥做法是定义一个只含 `matnr/werks/netpr` 的独立结构作为写库工作区。

### 7.4 分批提交（后台必做）

```abap
FORM write_db.

  LOOP AT gt_jobs ASSIGNING FIELD-SYMBOL(<job>) PACKAGE SIZE 2000.
    IF <job>-status = 'E'.
      CONTINUE.
    ENDIF.
    MODIFY marc FROM <job>-*.
  ENDLOOP.

  IF sy-subrc <> 0.                    " PACKAGE 循环结束后的 sy-subrc
    " 处理最后不足一包的部分
  ENDIF.

  COMMIT WORK.                         " 分包提交：每包独立 LUW
  WRITE: / 'committed rows:', gv_ok.

ENDFORM.
```

每 2000 行一个 LUW，可以：把回滚段压力降到可接受范围、显著缩短锁持有时间、避免"一错全丢"，并且天然支持断点续跑。

### 7.5 提交与作业状态（P0）

```abap
FORM finalize.

  IF gv_failed > 0 AND gv_ok = 0.
    MESSAGE '全部记录处理失败，程序终止' TYPE 'E'  ID 'ZY001'.
    RETURN.
  ENDIF.

  IF gv_failed > 0.
    MESSAGE '部分记录处理失败，请查看应用日志' TYPE 'W'  ID 'ZY002'.
  ENDIF.

  COMMIT WORK.
  WRITE: / gv_ok ' rows committed, ' gv_failed ' rows failed, at ' sy-datum sy-time.

  IF gv_failed > 0.
    MESSAGE '调价完成但存在失败行' TYPE 'A'  ID 'ZY003'.   " 置红：让 SM37 能看到
  ENDIF.

ENDFORM.
```

同时把 `MESSAGE` 文本抽到 Message Class `ZY`（SE63）以便维护；把 `p_commit` 这个勾选框**从生产变式中移除**，改为程序内始终按包提交（是否提交不该由勾选框决定）。

---

## 8. 上线前验证清单

1. 在测试系统用**后台作业**跑一次，与前台跑一次对比，确认两者调价系数完全一致（这是当前最大的隐患）。
2. 用一个**明确的物料范围**跑全量 MARC 之外的数据，验证大数据量下的内存占用与运行时长。
3. 人为制造一条失败（改一个 `netpr` 为 0 或越界），确认日志能报出失败行并让作业置红。
4. 在两行之间插入 `MESSAGE ... TYPE 'A'` 制造中途终止，确认分包提交后**已提交部分不会丢失**。
5. 核对一批物料的 `MARC-NETPR` 与实际销售价（条件记录），确认这个程序改的确实是生效价格（§6.1）。
6. 确认夜间时段不会有 MM03/其他价格程序并发修改同一批物料，或通过分包提交 + 重跑机制缓解。
7. 补上授权对象，禁止非授权用户执行全量调价。

---

## 9. 一句话总结

`zprice_batch` 结构简单、逻辑直白，但把"调试手段"（`sy-batch` 决定系数）写进了业务逻辑，把"提交"交给了一个勾选框和隐式提交，又对所有数据库错误保持沉默——**在前台跑错了不会报错，在后台跑崩了不会留痕**。在把调价系数外置、加 `sy-subrc` 检查、改为分批提交、并给作业一个真实的成功/失败状态之前，不建议把它继续当作无人值守的夜间作业。