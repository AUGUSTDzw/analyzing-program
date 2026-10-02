# ZCL_PRICE_WATCH 价格监控事件类 — 源码分析报告

| 项 | 值 |
|---|---|
| 分析对象 | `zcl_price_watch.clas.abap`（CLASS-POOL，119 行） |
| 类形态 | 全局 FINAL 类，`CREATE PUBLIC`，内含 2 个本地类 + 1 个全局接口 |
| 核心机制 | `CLASS-EVENTS` 广播价格下跌事件，2 个订阅者各自响应 |
| 分析重点 | 事件机制原理、发布/订阅链路的完整性与遗漏风险 |

---

## 0. 结论先行

事件机制本身**写法正确**——声明、`SET HANDLER`、`RAISE EVENT` 三点齐全，接口签名与事件参数逐字匹配，`FOR` 省略时的事件源绑定也是对的。

但订阅链路是**半个闭环**，漏掉的东西比写错的东西多：

1. 两个订阅者**都只 `WRITE`**，没有持久化——`lcl_audit` 叫审计却一行 DB 都没写，`lcl_alert` 在后台/批处理里等于没发。
2. **没有驱动源**：`check` 完全被动，没有定时作业也没有价格变更钩子，事件可能永不发生。
3. **没有注册/退订入口**：订阅者挂在构造函数里，外部无法注册、无法 mock、无法解绑。
4. **没有幂等**：同物料连续低于阈值会重复广播；**没有恢复事件**：告警永远无法自动关闭。
5. 源码本身**缺一个 `ENDCLASS.`**，照此激活会语法报错。

---

## 1. 组件地图

| 组件 | 位置 | 角色 |
|---|---|---|
| `zcl_price_watch` | L11–13 定义 / L77–120 实现 | **事件发布者**，兼阈值与关注清单的持有者 |
| `CLASS-EVENTS price_dropped` | L17–19 | 事件声明，`EXPORTING` 两个参数 |
| `constructor` | L79–84 | 隐式注册两个订阅者（事件源 = `me`） |
| `watch` / `forget` | L87–98 | 维护 `mt_watched` 关注清单 |
| `check` | L101–112 | 阈值判定 + `RAISE EVENT price_dropped` |
| `count_watched` | L115–117 | 返回清单行数 |
| `lcl_alert` | L43–53 | 订阅者 1（本地类），`INTERFACES if_price_listener` |
| `lcl_audit` | L56–66 | 订阅者 2（本地类），同上 |
| `if_price_listener` | L69–74 | 订阅契约，`FOR EVENT price_dropped OF zcl_price_watch` |

依赖方向是**环形**的：`zcl_price_watch` 声明事件 → `if_price_listener` 把该事件标记为可处理 → `lcl_alert` / `lcl_audit` 实现接口 → 构造函数把实现注册回 `zcl_price_watch`。这个环靠"三者都写在同一份 class pool 源码里"才成立，也正因为如此，调整任意一处的顺序都可能引发激活错误（见 §7）。

---

## 2. ABAP 事件机制到底是怎么工作的

`CLASS-EVENTS` 是 ABAP 的**同步、进程内、纯内存回调**。它和 SAP 消息中间件（ALE/IDoc、BAPI Business Event、ALE 端的 Business Event、MQ、集成引擎）**没有任何关系**。它就是一次函数指针调用——没有持久化、没有重投递、没有跨进程能力。理解这一点，后面所有"遗漏"才讲得通。

一个事件要真正跑起来，必须同时满足三个条件：

### 2.1 声明（发布者侧）

```abap
CLASS-EVENTS price_dropped
  EXPORTING iv_matnr TYPE mara-matnr
            iv_netpr TYPE marc-netpr.
```

`EXPORTING` 表示**同步按值传出**：发布者必须给值，订阅者按值接收，双方都不持有对方的状态，也没有返回值通道。

### 2.2 绑定（订阅者侧）

```abap
SET HANDLER lcl_alert=>on_price_dropped.
SET HANDLER lcl_audit=>on_price_dropped.
```

省略 `FOR` 子句时，事件源**隐式取当前对象 `me`**。这里写在 `constructor`（L82–83），意味着**每个实例都会为自己注册一套 handler**；在实例方法 `check` 里省略 `FOR` 时，事件源同样是 `me`——**谁调 `check`，就只通知那个实例的 handler**。

三条容易搞错的语义：

- **重复 `SET HANDLER` 是覆盖，不是叠加。** 对同一事件源 + 同一 handler 再次注册，前一次被替换。所以"构造两次就会收到两条 alert"这个担心不成立。
- **`lcl_alert=>on_price_dropped` 是用类静态引用调用一个实例方法。** 这在 ABAP 里合法，前提是该方法**不使用 `me`**。当前实现里只有 `WRITE`，无状态依赖，所以能跑。一旦它需要属性，就必须改成对象引用形式 `lo_alert->on_price_dropped`。
- **两个本地类从未被 `CREATE OBJECT`。** 事件机制对它们只要求方法可被静态调用，不要求实例存在。

### 2.3 触发（发布者侧）

```abap
IF iv_netpr < mv_threshold.
  RAISE EVENT price_dropped
    EXPORTING iv_matnr = iv_matnr
              iv_netpr = iv_netpr.
ENDIF.
```

### 2.4 订阅方法必须被标记为 handler

```abap
INTERFACE if_price_listener PUBLIC.
  METHODS on_price_dropped
    FOR EVENT price_dropped OF zcl_price_watch
    IMPORTING iv_matnr TYPE mara-matnr
              iv_netpr TYPE marc-netpr.
ENDINTERFACE.
```

`FOR EVENT ... OF ...` 是硬性要求。参数名、类型、顺序、`EXPORTING`/`IMPORTING` 方向必须与事件声明**逐字一致**，否则激活期就报错。这一处写对了（L70–73 vs L17–19）。

### 2.5 完整时序

```abap
" 外部调用
zcl_price_watch=>check( iv_matnr = 'MAT-01' iv_netpr = '9.90' )
  └─ READ TABLE mt_watched …            " 未命中 → sy-subrc<>0 → 直接 RETURN（静默）
  └─ iv_netpr < mv_threshold ?          " 否 → 返回，无事件
  └─ RAISE EVENT price_dropped EXPORTING …
       ├─ lcl_alert=>on_price_dropped   " WRITE: / 'ALERT: price drop for' …
       └─ lcl_audit=>on_price_dropped   " WRITE: / 'AUDIT entry created for' …
  └─ 两个 handler 在同一调用栈、同一 LUW 内同步跑完，check 才返回
```

---

## 3. 发布侧逐点解读

**`constructor`（L79–84）**
只做两件事：存阈值、注册两个 handler。注意它**不做任何初始化校验**——`iv_threshold` 传 initial 也能建出实例，此后 `iv_netpr < 0` 永远不成立，监控静默失效。

**`watch`（L87–93）**
`iv_matnr IS INITIAL → RETURN` 静默失败；`APPEND` 前不查重。`mt_watched` 是 `STANDARD TABLE OF mara-matnr WITH EMPTY KEY`（L40），**非唯一表** → 同一物料可以 watch 多次。

**`forget`（L96–98）**
`DELETE mt_watched WHERE table_line = iv_matnr` 语义正确（一次删掉所有重复项），但在 EMPTY KEY 表上要全表扫描。

**`check`（L101–112）**
- L102 `READ TABLE … WITH TABLE KEY table_line =` —— 对 EMPTY KEY 表这个写法能跑（逐行比对），但没利用唯一性。
- L103–105 未关注的物料**完全静默返回**，不留任何痕迹。
- L107 只有 `<`，**没有和"上一次价格"比较** → 无去重，见 §5。
- L108–110 `RAISE EVENT` 无异常边界，两个 handler 串行同步。

**`count_watched`（L115–117）**
`lines( mt_watched )` 会把重复 watch 的条目一并计入 → 计数虚高。

**数据语义风险**
`marc-netpr` 是 **CURR 类型（15 位、5 位小数、允许负号）**。SAP 业务中 `netpr` 为负表示返利/折扣，而 `iv_netpr < mv_threshold` 对负价**恒成立** → 只要关注了带返利的物料，每次 `check` 都会误报"价格下跌"。这是价格监控类最容易踩的坑。

---

## 4. 订阅侧逐点解读

`lcl_alert`（L50–52）与 `lcl_audit`（L63–65）结构完全对称，差别只有一行 `WRITE`：

| | `lcl_alert` | `lcl_audit` |
|---|---|---|
| 是否实现接口 | ✅ | ✅ |
| 是否需要实例 | ❌ 静态引用即可 | ❌ |
| 是否用 `iv_matnr` | ✅ | ✅ |
| 是否用 `iv_netpr` | ❌ **收了不用** | ✅ |
| 实际效果 | 屏幕上打印一行 | 屏幕上打印一行 |
| 可否持久化 | ❌ | ❌（**名字叫 audit，但一表未写**）|

两个类都是 `FINAL`、无属性、无构造方法，职责上本应"一个报警、一个留痕"，实现却退化成了两个 `WRITE`。订阅者之间没有任何差异化能力（例如按阈值分级、抑制重复、失败重试）。

---

## 5. 发布/订阅的遗漏清单

### P0 — 订阅链路实质断裂

**5.1 两个订阅者都不产生任何持久效果。**
`lcl_alert` 用 `WRITE`：在后台批处理、RFC 调用、ALV 网格内，输出要么被重定向到 spool（无人查看），要么根本不显示——**告警等于没发**。`lcl_audit` 一行 DB 都没写——**审计等于没做**。事件"广播成功"，下游是空的。

**5.2 没有驱动源，事件可能永远不发生。**
`check` 是纯被动方法：必须有人显式调用并把价格传进来。代码里**没有定时作业、没有价格主数据变更钩子**（`MARC-NETPR` 的 BAPI/ALE 变更）、没有后台调度。监控系统上线后大概率长期处于"永不报警"状态，而代码不会给出任何提示。

**5.3 没有注册/退订入口，生命周期绑死在构造函数。**
事件本身是公开的（`CLASS-EVENTS` 在 `PUBLIC SECTION`，`if_price_listener` 在 class pool 中声明为 `PUBLIC` 全局接口），所以外部代码技术上可以写 `INTERFACES if_price_listener` 再注册。但每个外部订阅者都得自己解决两件事：

- 自己的实例必须挂在某个全局引用上（LOCAL CLASS 的静态引用 / class attribute / 单例），否则注册后实例被 GC，**handler 静默失效**；
- 只能自己写 `SET HANDLER … OFF` 来解绑，**发布者不提供对称的退订能力**。

同时 `lcl_alert` / `lcl_audit` 作为本地类，**外部无法引用、无法 mock、无法替换、无法被单元测试观测**。发布者应该把 handler 生命周期收进自己手里。

**5.4 无异常隔离，一个订阅者炸掉会连累另一个和发布者。**
ABAP 的 `RAISE EVENT` 是**串行同步**调用，**不会**为每个 handler 建立异常边界。若 `lcl_audit` 后续加入 DB 写入并抛出异常：

- 异常直接冒泡出 `check`，调用方拿到一个完全不属于"价格监控"的异常类型；
- **注册在其后的 handler 不会被调用**；
- 发布者无法区分"价格没跌"和"订阅者挂了"。

顺序同样不可依赖：ABAP 未对多个 handler 的调用顺序给出可依赖的契约，实际观察通常是注册顺序（先 alert 后 audit），但业务逻辑不能建立在这个假设上——尤其当一个要写 DB、一个要发外部消息时。

**5.5 没有兜底订阅者。**
生产上通常需要三层：即时告警（邮件/消息类）+ 审计落库 + 降级补偿（进队列/写待办/进集成引擎）。目前只有 2 个且都只 `WRITE`，任意一个扩展失败就没有第三条路。

### P1 — 会造成误报、重复或信息不足

**5.6 没有幂等/去重。**
事件只在"本次价格 < 阈值"时发，没有"上一次价格"的概念。同一物料连续 3 次 `check` 都低于阈值 → **收到 3 次广播** → 告警刷屏、审计表重复行。应把 `mt_watched` 升级为带 `last_alerted_netpr` 的结构，只在价格**真正下破**时发一次（迟滞 / hysteresis）。

**5.7 没有恢复事件。**
价格回升到阈值以上时**什么都不发**。订阅者无法知道告警该关闭，监控系统里会留下一堆永远"未闭环"的告警。

**5.8 关注状态变化没有事件。**
`watch` / `forget` 改变监控范围时不广播任何事件，审计侧无从知道"某人从何时起开始监控这个物料"。

**5.9 事件参数不足以支撑订阅者。**
只带 `matnr` + `netpr`：

- 不带**币种** → 订阅者要显示价格必须回查 `MARC`（而 `lcl_alert` 连价格都没显示）；
- 不带**旧价格** → 无法算跌幅；
- 不带**阈值** → 不知道报警线；
- 不带**触发时间/物料描述/严重级别** → 审计行没有自解释能力。

**5.10 没有耗时与规模护栏。**
`RAISE EVENT` 的耗时全部计入 `check` 的 LUW。若后续一个实例关注数千物料、每条走 3 个 handler 且任一做 RFC/写 DB，`check` 总耗时会线性叠加，容易撞工作进程超时。ABAP OO 事件本身**不支持真正异步**，要异步必须走 `IN UPDATE TASK` / 单据流 / 集成引擎。

### P2 — 数据与并发

**5.11 `mt_watched` 用 EMPTY KEY 表**：允许重复 watch → `count_watched` 虚高；`forget` 与 `check` 都要全表扫描。应改为 `SORTED TABLE … WITH UNIQUE KEY table_line`，并在 `watch` 里用 `INSERT …` 的 `sy-subrc` 判重。

**5.12 无并发保护。** 若该类被当作服务并发调用，`mt_watched` 与 `mv_threshold` 的读写没有任何锁，`SET HANDLER` 本身也不提供"仅首次注册"的语义保护。

**5.13 无日志。** 事件触发与否都不留日志，事后无法审计、无法定位"为什么没报警"。

**5.14 阈值无校验。** `constructor` 接受任意 `netpr`，initial 或负阈值都能建出"永不报警"的实例，且无任何告警。

---

## 6. 源码本身的两个结构问题（会影响激活）

**6.1 主类定义缺少 `ENDCLASS.`。**
class pool 的主类定义从 L11 `PUBLIC` 开始，到 L37 `PRIVATE SECTION.` 的两个 `DATA`（L39–40）之后**没有 `ENDCLASS.`**，L43 直接就是 `CLASS lcl_alert DEFINITION FINAL.`。ABAP 不允许类定义嵌套，按此源码直接激活会在这一行报语法错误。**修复：在 L40 之后补一行 `ENDCLASS.`。**

**6.2 接口在实现它的类之后才声明。**
`lcl_alert`（L45）与 `lcl_audit`（L58）都 `INTERFACES if_price_listener`，但 `INTERFACE if_price_listener PUBLIC` 出现在 L69。class pool 中这些虽是全局对象，处理仍按源码顺序，稳妥做法是把接口整体上移到 L43 之前。

> 如果这份文件是从 SE24 导出的编辑副本，6.1 / 6.2 可能是复制过程丢掉的内容；但按真实源码风险排查，成本极低。

---

## 7. 建议的修法

### 7.1 修结构（必须，优先级最高）
在 L40 之后补 `ENDCLASS.`；把 `if_price_listener` 上移到两个本地类定义之前。

### 7.2 补注册/退订 API，把 handler 生命周期收归发布者

```abap
" PUBLISHING SECTION
METHODS register_listener
  IMPORTING io_listener TYPE REF TO if_price_listener.

METHODS unregister_listener
  IMPORTING io_listener TYPE REF TO if_price_listener.

" IMPLEMENTATION
METHOD register_listener.
  SET HANDLER io_listener->on_price_dropped
    FOR zcl_price_watch~price_dropped.
ENDMETHOD.

METHOD unregister_listener.
  SET HANDLER io_listener->on_price_dropped
    OFF FOR zcl_price_watch~price_dropped.
ENDMETHOD.
```

改用**对象引用形式** `io_listener->…`（而不是现在的 `lcl_alert=>…`），这样有状态的订阅者才能拿到 `me`；构造函数里对内置的 alert/audit 也应相应改成持有对象引用。

### 7.3 让订阅产生真实效果

```abap
" zcl_price_audit_sink 实现
METHOD if_price_listener~on_price_dropped.
  DATA ls_entry TYPE zprice_audit.
  ls_entry-matnr     = iv_matnr.
  ls_entry-netpr     = iv_netpr.
  ls_entry-currency  = get_currency_for( iv_matnr ).   " 事件没带币种，只能回查
  ls_entry-timestamp = sy-datum && sy-uzeit.
  MODIFY zprice_audit FROM ls_entry.
  IF sy-subrc <> 0.
    MESSAGE e000(zprice_watch) WITH iv_matnr.          " 至少让失败可见
  ENDIF.
ENDMETHOD.
```

告警侧把 `WRITE` 换成消息类 `MESSAGE` / `soami` 邮件 / 后台日志，而不是屏幕输出。

### 7.4 补幂等、恢复事件与状态事件

```abap
CLASS-EVENTS price_recovered   EXPORTING iv_matnr TYPE mara-matnr
                                      iv_netpr TYPE marc-netpr.
CLASS-EVENTS watch_added       EXPORTING iv_matnr TYPE mara-matnr.
CLASS-EVENTS watch_removed     EXPORTING iv_matnr TYPE mara-matnr.

" mt_watched 升级为带上次价格的唯一键排序表
TYPES ty_watch TYPE SORTED TABLE OF ty_watch_line WITH UNIQUE KEY table_line.

" check 中：只在下破时广播，回升时广播恢复
IF iv_netpr < mv_threshold AND iv_netpr < ls_watch-last_netpr.
  ls_watch-last_netpr = iv_netpr.
  MODIFY TABLE mt_watched FROM ls_watch.
  RAISE EVENT price_dropped EXPORTING iv_matnr = iv_matnr iv_netpr = iv_netpr.
ELSEIF iv_netpr > ls_watch-last_netpr AND ls_watch-alerted = abap_true.
  ls_watch-alerted = abap_false.
  MODIFY TABLE mt_watched FROM ls_watch.
  RAISE EVENT price_recovered EXPORTING iv_matnr = iv_matnr iv_netpr = iv_netpr.
ENDIF.
```

### 7.5 补驱动源，让监控闭环
用 `START-SELECTION` 接后台定时作业，或直接挂在价格变更的 BAPI/ALE 侧，由它从 `MARC-NETPR` 取实际价格调 `check`。同时在 `check` 里对 `iv_netpr <= 0`（返利/异常价）单独走一条判断分支，规避 §3 的负价误报。

### 7.6 拆判定与广播，提升可测试性
把"是否该报警"抽成不触发事件的纯函数 `is_drop( iv_matnr iv_netpr ) RETURNING VALUE(rv_drop) TYPE abap_bool`，单测只需断言返回值，不必真的构造发布者——这正是当前结构最大的可测性障碍。

---

## 8. 自测清单

| # | 场景 | 期望 | 现状 |
|---|---|---|---|
| 1 | 未 `watch` 的物料 `check` | 无事件、静默返回 | ✅ |
| 2 | 已 `watch`，价格 > 阈值 | 无事件 | ✅ |
| 3 | 已 `watch`，价格 < 阈值 | alert + audit 各 1 次 | ✅ |
| 4 | 同一实例重复 `SET HANDLER` | 不重复触发（覆盖语义）| ✅ |
| 5 | 实例 A 调 `check`，实例 B 的 handler | 不应触发 | ✅（事件源 = `me`）|
| 6 | 连续 3 次低于阈值 | **只应 1 次** | ❌ 触发 3 次 |
| 7 | 价格回升到阈值以上 | **应发恢复事件** | ❌ 无任何事件 |
| 8 | `watch` 同物料 2 次后 `count_watched` | **应为 1** | ❌ 返回 2 |
| 9 | 负价格（返利）物料 | 不应报警 | ❌ 每次都报 |
| 10 | 阈值 initial 的实例 | 应报错或告警 | ❌ 静默永不报警 |
| 11 | 后台批处理触发 | 告警应落日志/发消息 | ❌ 只进 spool |
| 12 | 订阅者抛异常 | 另一个订阅者仍应执行 | ❌ 后续 handler 被跳过 |
| 13 | 外部程序想订阅 | 应有 `register_listener` 入口 | ❌ 需自建全局引用，无法退订 |
| 14 | 单元测试 mock 监听器 | 可注入 | ❌ 本地类不可见 |
| 15 | 按此源码激活 | 应能通过语法检查 | ❌ 缺 `ENDCLASS.` |

---

## 9. 代码位置索引

| 关注点 | 位置 |
|---|---|
| 事件声明 | `zcl_price_watch.clas.abap:17` |
| 接口声明（handler 标记）| `zcl_price_watch.clas.abap:69` |
| 订阅者 1 | `zcl_price_watch.clas.abap:43` / `:50` |
| 订阅者 2 | `zcl_price_watch.clas.abap:56` / `:63` |
| 订阅注册点 | `zcl_price_watch.clas.abap:82` |
| 阈值判定与事件触发 | `zcl_price_watch.clas.abap:107` |
| 关注清单表定义（EMPTY KEY）| `zcl_price_watch.clas.abap:40` |
| 缺失的 `ENDCLASS.` | `zcl_price_watch.clas.abap:40` 之后 |