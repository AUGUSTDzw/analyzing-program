# ZCL_PRICE_WATCH 分析报告 —— 局部类事件（CLASS-EVENTS）发布/订阅机制

> 源文件：`evals/zcl_price_watch.clas.abap`（119 行，全局类池 `CLASS-POOL`）
> 关注点：**广播价格下跌事件的机制如何工作**，以及**发布/订阅链条上遗漏了什么**。

---

## 0. 一句话结论

这套「发布/订阅」在**语法上根本编译不过**：`if_price_listener` 定义在第 69 行，而引用它的 `lcl_alert`（第 43 行）和 `lcl_audit`（第 56 行）声明在它前面 —— ABAP 不允许接口前向引用。修掉这行之后，机制本身能跑，但**订阅侧缺 6 项关键能力**（无法退订、无法区分实例、处理器无法报错、事件粒度只有单条、订阅者硬编码在发布者里、审计处理器名不副实）。

---

## 1. 代码地图

| 构件 | 行号 | 角色 |
|---|---|---|
| `CLASS-POOL zcl_price_watch` / `CREATE PUBLIC` | 7–13 | 全局类池壳，实例可被外部持有 |
| `CLASS-EVENTS price_dropped` | 17–19 | **静态事件**（无 `LATE`/`EARLY`），2 个 EXPORTING 参数 |
| `constructor` 里的两条 `SET HANDLER` | 82–83 | 注册两个订阅者 |
| `check` 里的 `RAISE EVENT` | 108–110 | 唯一的发布点 |
| `if_price_listener`（`FOR EVENT ... OF`） | 69–74 | 事件接口，把事件签名"锁"给订阅方 |
| `lcl_alert` / `lcl_audit` | 43–66 | 两个无状态 `FINAL` 局部类，只 `WRITE` |
| `mt_watched` / `mv_threshold` | 39–40 | **实例**属性（两个实例各有一份） |

一句话职责划分：实例属性决定**要不要发**，静态事件决定**谁会收到**，而 `check` 是二者唯一的交汇点。

---

## 2. 事件机制到底怎么工作

### 2.1 声明期：两条腿必须对齐

ABAP 的事件订阅是**声明式绑定**，靠三段代码的一致性：

```abap
" ① 发布侧：定义事件（本类是唯一合法的发布者）
CLASS-EVENTS price_dropped
  EXPORTING iv_matnr TYPE mara-matnr
            iv_netpr TYPE marc-netpr.

" ② 契约侧：接口方法声明"我要响应这个事件"
INTERFACE if_price_listener PUBLIC.
  METHODS on_price_dropped
    FOR EVENT price_dropped OF zcl_price_watch
    IMPORTING iv_matnr TYPE mara-matnr
              iv_netpr TYPE marc-netpr.
ENDINTERFACE.

" ③ 订阅侧：实现接口
CLASS lcl_alert DEFINITION FINAL.
  PUBLIC SECTION.
    INTERFACES if_price_listener.     "方法名可不同，实现的却是 ② 绑定的那个
ENDCLASS.
```

关键点：

- `CLASS-EVENTS` **没有** `LATE`/`EARLY`，所以它是**静态事件**，只有 `zcl_price_watch` 自己能 `RAISE`，外部不能伪造。这是对的，等于把发布权封装住了。
- `FOR EVENT ... OF` 里的参数必须与事件的 `EXPORTING` 列表**在名字、类型、传参方式上完全一致**，否则激活期报错。这是一条硬契约：以后给事件加第三个参数，接口、两个订阅类、三处签名必须同时改。
- `INTERFACES if_price_listener.` 只是"我实现了这个接口"的声明，真正的方法名由接口决定。所以 `lcl_alert` 里能写 `METHOD if_price_listener~on_price_dropped`，尽管它自己没声明这个方法。
- **`if_price_listener` 必须在任何 `INTERFACES` 引用它之前定义** —— 见第 4 节 P0。

### 2.2 注册期：`SET HANDLER` 的三个要素

```abap
SET HANDLER lcl_alert=>on_price_dropped.
SET HANDLER lcl_audit=>on_price_dropped.
```

不写 `FOR`，是因为这段代码在 `zcl_price_watch` 的方法里，**隐含的触发对象就是 `zcl_price_watch` 自己**，正好对应静态事件。

注册表是**类级别的全局列表**，与实例无关：

- 顺序被 ABAP 记录：先注册的 `lcl_alert` 先执行。
- 同一个处理器重复注册在运行时被视为同一项（幂等），但**没有任何注销路径**。

### 2.3 触发期：`RAISE EVENT` 的同步语义

```abap
METHOD check.
  READ TABLE mt_watched WITH TABLE KEY table_line = iv_matnr.
  IF sy-subrc <> 0.
    RETURN.
  ENDIF.

  IF iv_netpr < mv_threshold.
    RAISE EVENT price_dropped
      EXPORTING iv_matnr = iv_matnr
                iv_netpr = iv_netpr.
  ENDIF.
ENDMETHOD.
```

- 未写 `WAIT UP TO n SECONDS` ⇒ **同步触发**：两个处理器在 `RAISE EVENT` 的调用栈内、按注册顺序、紧接着执行完才返回 `check`。两条 `WRITE` 的输出顺序是确定的（ALERT 在 AUDIT 之前）。
- `RAISE EVENT` **不结束**当前方法，它就是一条普通语句；`check` 继续往下走并返回。
- 同步意味着**处理器共享 raiser 的 LUW 与事务上下文**：`lcl_alert` 里如果将来加 `COMMIT WORK`，`lcl_audit` 看到的是新 LUW；任一处理器抛异常，**不会被 `check` 的调用方捕获**（事件不像函数模块那样有 `EXCEPTIONS` 加词）。

### 2.4 完整执行时序

1. 外部 `CREATE OBJECT zcl_price_watch` → `constructor`：记下阈值，顺手把两个处理器挂到全局表上。
2. `watch('M-100')` → `mt_watched` 追加（**不查重**）。
3. 外部逐条调用 `check( iv_matnr = 'M-100', iv_netpr = 9.80 )`。
4. `check` 在 `mt_watched` 里线性查一次，找到且 `9.80 < 阈值` ⇒ 发布事件。
5. `lcl_alert` 打印一行，`lcl_audit` 再打印一行。
6. `check` 返回 —— 调用方**拿不到任何"有没有触发"的反馈**。

---

## 3. 发布/订阅的遗漏清单

### P0 — 阻断：`if_price_listener` 定义在使用之后（编译失败）

```abap
CLASS lcl_alert DEFINITION FINAL.   " 43 行
  PUBLIC SECTION.
    INTERFACES if_price_listener.   " ← 44 行：接口还不存在
ENDCLASS.
...
INTERFACE if_price_listener PUBLIC. " 69 行：太晚了
```

ABAP 全局类池**顺序解析、不支持前向声明**。激活时会报 `Interface IF_PRICE_LISTENER not found`（或等价的语法/语义错误）。修复方式只有一种——把接口整体上移到类池公共区之后、任何局部类之前：

```abap
CLASS-POOL zcl_price_watch.
PUBLIC FINAL CREATE PUBLIC.

  PUBLIC SECTION.
    CLASS-EVENTS price_dropped
      EXPORTING iv_matnr TYPE mara-matnr
                iv_netpr TYPE marc-netpr.
    METHODS constructor IMPORTING iv_threshold TYPE marc-netpr
                        RETURNING VALUE(ro_watch) TYPE REF TO zcl_price_watch.
    METHODS watch    IMPORTING iv_matnr TYPE mara-matnr.
    METHODS forget   IMPORTING iv_matnr TYPE mara-matnr.
    METHODS check    IMPORTING iv_matnr TYPE mara-matnr
                           iv_netpr TYPE marc-netpr
                     RETURNING VALUE(rv_dropped) TYPE abap_bool.
    METHODS count_watched RETURNING VALUE(rv_count) TYPE i.
    CLASS-METHODS subscribe.
    CLASS-METHODS unsubscribe.
ENDCLASS.

INTERFACE if_price_listener PUBLIC.            " ← 提到这里
  METHODS on_price_dropped
    FOR EVENT price_dropped OF zcl_price_watch
    IMPORTING iv_matnr TYPE mara-matnr
              iv_netpr TYPE marc-netpr.
ENDINTERFACE.

CLASS lcl_alert  DEFINITION FINAL.
  PUBLIC SECTION. INTERFACES if_price_listener.
ENDCLASS.
CLASS lcl_audit DEFINITION FINAL.
  PUBLIC SECTION. INTERFACES if_price_listener.
ENDCLASS.
```

### P1 — 静态事件 + 实例状态：订阅者收不到"是谁降的、降到多少以下"

事件是**全局的**，阈值和观察清单是**实例的**。后果：

```abap
DATA: lo_a TYPE REF TO zcl_price_watch,
      lo_b TYPE REF TO zcl_price_watch.
lo_a = #( iv_threshold = 5.00 ).   " 只关心跌破 5
lo_b = #( iv_threshold = 100.00 ). " 关心跌破 100
lo_b->check( iv_matnr = 'M-100'
             iv_netpr = 50.00 ).  " → 触发事件
```

两个订阅者会同时收到 `iv_netpr = 50.00`，**完全无法判断**这是"跌破 5"的严重事件还是"跌破 100"的边缘事件。载荷里缺 `iv_threshold` 和一个实例句柄：

```abap
CLASS-EVENTS price_dropped
  EXPORTING iv_matnr     TYPE mara-matnr
            iv_netpr     TYPE marc-netpr
            iv_threshold TYPE marc-netpr     " 补：阈值语义
            iv_handle    TYPE i.              " 补：哪个 watcher 发的
```

### P1 — 只有"订阅"，没有"退订"

`constructor` 里注册，**代码里找不到任何 `UNSET HANDLER`**，`forget` 也只删物料清单。后果：

- 只要这个类池被加载过一次，两个处理器就是**永久生效**的，没有任何业务语义能关掉告警。
- 订阅时机被迫与构造耦合：别人 `CREATE OBJECT` 一个实例，等于替所有人打开了开关。
- `lcl_alert` / `lcl_audit` 是局部类，没有 `CLEANUP` 生命周期钩子，运行时也不会因为"没有实例了"而摘掉它们。

```abap
METHOD unsubscribe.
  UNSET HANDLER lcl_alert=>on_price_dropped  FOR zcl_price_watch.
  UNSET HANDLER lcl_audit=>on_price_dropped FOR zcl_price_watch.
ENDMETHOD.
```

静态事件的 `UNSET HANDLER` **必须带 `FOR <全局类名>`**（实例事件才用 `FOR me`）。

### P1 — 处理器没有回传通道，也没有错误出口

- `RAISE EVENT` 不支持 `EXCEPTIONS` 加词。处理器里 `WRITE` 成功与否、审计条目是否真的落库，发布者和调用方**一个字都收不到**。
- 处理器抛的异常不在 `check` 的异常传播链上，**`check` 的调用方既捕不到也不会被告知**。
- `check` 也没有返回值，调用方无法 `IF lo_watch->check( ... ) = abap_true.`

建议：要么让 `check` 带 `RETURNING`，要么在类上放一个诊断属性 / 写应用日志（`bal_log_create`），把失败显式化。

### P2 — 事件粒度只有"单条"，缺少批量/聚合事件

一次全量比价 N 个物料 ⇒ N 次 `RAISE EVENT` ⇒ N×2 条同步 `WRITE`。没有：

- 批量事件 `price_dropped_batch`（一次抛一张表）；
- 一次性评估入口（现在没有任何 `refresh` / `evaluate_all`，观察清单是**被动**的，得由外部逐条调 `check`）；
- 去重/节流能力。订阅类是无状态 `FINAL`，没地方存"已告警集合"来做抑制。

```abap
TYPES: BEGIN OF t_drop,
         matnr TYPE mara-matnr,
         netpr TYPE marc-netpr,
       END OF t_drop,
       t_drops TYPE STANDARD TABLE OF t_drop WITH EMPTY KEY.

CLASS-EVENTS price_dropped_batch
  EXPORTING it_drops TYPE t_drops.
```

### P2 — `mt_watched` 不查重，`count_watched` 不可信

```abap
APPEND iv_matnr TO mt_watched.   " watch：完全没判重
DELETE mt_watched WHERE table_line = iv_matnr.  " forget：一次删光所有副本
```

连续 `watch('M-100')` 两次 ⇒ `count_watched( ) = 2`，但只有一个物料在被观察。`WITH EMPTY KEY` 表还让每次 `check` 都是 O(n) 线性扫描，全量比价退化成 O(n²)。最省事的修法是换表类型，顺带解决三件事：

```abap
DATA mt_watched TYPE HASHED TABLE OF mara-matnr WITH UNIQUE KEY table_line.
" watch:  READ TABLE mt_watched WITH TABLE KEY table_line = iv_matnr.
"          IF sy-subrc <> 0. INSERT VALUE #( table_line = iv_matnr ) INTO mt_watched. ENDIF.
" check :  READ TABLE mt_watched WITH TABLE KEY table_line = iv_matnr.  " O(1)
" count :  行数天然准确
```

### P2 — 订阅者硬编码在发布者内部（依赖方向反了）

`lcl_alert` / `lcl_audit` 是 `zcl_price_watch` 的内部实现细节，等于发布者**知道**自己的订阅者。后果：

- 想加第三个订阅者（发邮件、写接口、发 ALV）必须改发布者，破坏开闭原则。
- 单测发布者时无法隔离订阅者；发布者的行为永远受两个 `WRITE` 干扰。
- 好消息是事件和接口都是 `PUBLIC`，外部程序**可以**自己写 `SET HANDLER cl_xxx=>on_price_dropped FOR zcl_price_watch` 来扩展——但内置那两个把这条路堵死了。
- `constructor` 里做全局副作用，让这个类**不可安全地批量实例化**（典型：一次 ALV 循环里 `CREATE OBJECT` N 次）。注册应属于静态方法（`subscribe` / `unsubscribe`），或干脆下沉到调用方。

### P2 — `lcl_audit` 名不副实

```abap
METHOD if_price_listener~on_price_dropped.
  WRITE: / 'AUDIT entry created for', iv_matnr, iv_netpr.  " 什么都没创建
ENDMETHOD.
```

它没有写任何持久化对象，却宣称"AUDIT entry created"。真实后果：审计链是空的，业务上出问题时无法回溯。要么改名为 `lcl_notify`，要么真的落库（且要处理与 `lcl_alert` 的先后顺序：ABAP 保证注册顺序，所以 ALERT 一定先于 AUDIT，若 ALERT 里可能 `LEAVE` 或抛错，AUDIT 就永远不执行了 —— 这是同步事件里很典型的"半条链断掉"）。

同时，`WRITE` 出现在处理器里：后台作业时变成无用 spool、对话框里污染列表、条件里输出会被截断。生产环境应该用消息类 + `bal_log_create` + 消息号。

### P3 — 若干细节

| 项 | 问题 |
|---|---|
| `marc-netpr` | 是 `CURR13(15)` 带 2 位小数。跨币种阈值直接比较无意义，缺少 `CUCFM`/`CURX` 换算。 |
| DDIC 耦合 | 公开 API 直接暴露 `mara-matnr` / `marc-netpr`。将来若要监控 IPRKCOND 之类其他价来源，事件签名必须变，而签名一变，`if_price_listener` 和所有订阅类全部要改。建议先抽 `zif_price_key` / `zif_amount`。 |
| 并发 | `mt_watched` 无保护。在并行 RFC / 后台多进程场景下没有 `ENQUEUE` 或调用方串行约定。 |
| 构造函数无校验 | 传入 `0` 或负阈值不报错，`iv_netpr < 0` 恒假 ⇒ 静默永不告警。 |
| `check` 的 `WITH TABLE KEY` | 合法但 O(n)；且物料存在性/有效性未校验。 |
| 头部注释 | 写着 `Report ZCL_PRICE_WATCH`（实际是类池）和 "one subscriber class"（实际两个）——文档已与代码脱节。 |

---

## 4. 推荐的整改顺序

1. **把 `if_price_listener` 上移** —— 否则一切免谈。
2. `SET HANDLER` 从 `constructor` 挪到静态 `subscribe`，补 `unsubscribe`。
3. 事件载荷补 `iv_threshold`（和可选实例句柄），消除跨实例歧义。
4. `mt_watched` 换 `HASHED ... WITH UNIQUE KEY`；`watch` 改 `INSERT`，`count_watched` 随之可信。
5. `check` 加 `RETURNING rv_dropped`，或加应用日志作为处理器失败出口。
6. 决定 `lcl_audit` 的去留：真落库，或改名。把两处 `WRITE` 换成消息/日志。
7. （可选）加 `evaluate_all` + `price_dropped_batch`，把 N 次同步触发压成 1 次。

## 5. 自测问题（用来验证理解是否到位）

- 把 `if_price_listener` 移到文件末尾再激活，报什么错？为什么不是"运行时"才失败？
- `SET HANDLER` 写在 `constructor` 里但事件是静态的 —— 如果 `CREATE OBJECT` 两次，处理器被注册了几次？`RAISE EVENT` 会被触发几次？
- 处理器里 `RAISE EXCEPTION cx_sy_no_handler`，调用 `check` 的地方能 `CATCH` 到吗？
- `check` 里 `RAISE EVENT` 之后还有代码，它会执行吗？
- 实例 A（阈值 5）和实例 B（阈值 100）都观察 M-100，价格降到 50：事件触发几次？订阅者知道是哪个阈值吗？

---

### 附：几个容易记错的 ABAP 事件细节

- 静态事件（无 `LATE`/`EARLY`）只能由本类 `RAISE`，且**不需要**写 `FOR`（在同类方法内），`UNSET HANDLER` 则**必须**写 `FOR`。
- 不带 `WAIT UP TO` 的 `RAISE EVENT` 是**同步**的：处理器按注册顺序在当前调用栈内执行完才返回；加 `WAIT UP TO n SECONDS` 才是异步，且需要 `WAIT FOR EVENT ... ` 才等结果。
- `RAISE EVENT` 没有 `EXCEPTIONS` 加词，处理器异常不会传回发布者。
- 事件处理器方法的签名由 `FOR EVENT ... OF` 决定，与发布者事件的 `EXPORTING` 列表强耦合。