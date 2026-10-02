# `ZVENDOR_NOTIFY` 走读：锁时机与消息类用法的体检报告

## 先给结论

这个程序有两件事做得对：**锁在读之前加**（顺序正确）、**用 `MESSAGE ID/NUMBER` 而不是硬编码字符串**（形式正确）。但围绕这两件对的事，几乎所有的"周边"都写错了：

1. **加锁范围 ⊊ 读取范围** —— `ENQUEUE` 只锁 `s_lifnr-low`，`SELECT` 却按整个 `s_lifnr` 区间读。锁了个寂寞。
2. **选择屏非必填** —— 空选择屏时 `LOOP AT s_lifnr` 依然执行一次，程序会对**全量供应商**跑逻辑。
3. **任何一次异常终止都会泄漏锁** —— 异常路径上没有统一解锁，`CONTINUE` 是死代码。
4. **这个程序根本不写 LFA1** —— 只读程序加写锁，是纯粹的负收益。
5. **消息类 `'ZVND'` 是 4 位** —— `T100-ARBGB` 只有 3 位，这条语句在运行时找不到消息类。
6. `MESSAGE ... TYPE 'S'` 被用来报"没查到数据"，`TYPE 'W'` 被塞在 `LOOP` 里逐条报，消息行最终只会剩下最后一条。

---

## 一、这个程序到底在做什么

流程很短，主链是四步：

```abap
START-OF-SELECTION.

  PERFORM lock_records.
  PERFORM read_vendors.
  PERFORM notify_by_email.
  PERFORM release_lock.
```

意图很清楚：从选择屏拿一批供应商号 → 加锁 → 查 LFA1 → 发邮件通知 → 解锁。

但把四个 `FORM` 的实际动作摊开看：

| 子程序 | 声称职责 | 实际动作 |
|---|---|---|
| `lock_records` | 给供应商加锁 | 只对 `s_lifnr-low` 加锁，错误直接 `E` 消息终止 |
| `read_vendors` | 读取供应商 | 按完整 `s_lifnr` 区间 SELECT；空结果报 `S` 消息但不 return；`W` 消息在 LOOP 里逐条发 |
| `notify_by_email` | 发邮件 | `lt_recipients` 声明后从未填充，邮件从未发出；只把内表 `status` 标成 `'X'` |
| `release_lock` | 解锁 | 按 `s_lifnr-low` 解锁，无异常处理；末尾 `gv_dummy = 1` 凑数 |

**净效果 = 加一堆锁 + 读一堆数据 + 弹几条消息 + 把结果丢进一个进程结束就消失的内表 + 解锁。** 没有 DB 写入，没有列表输出，没有真正的邮件。报表名和头注释都说"maintenance（维护）"，但代码里没有任何 `MODIFY lfa1` / `INSERT` / `UPDATE`。

这个"名不副实"不是小事——它直接决定了下面锁这一节的所有判断：**一个只读程序，是不该加锁的。**

---

## 二、锁：加锁时机

### 2.1 对的地方

`PERFORM lock_records` 在 `PERFORM read_vendors` **之前**执行，这个顺序是对的。锁的目的就是保证"我读到的那一刻起，别人改不了我正在用的这批记录"；先读后锁等于什么都没保证。同理，如果将来真的要在程序里 `MODIFY lfa1`，标准模式也一定是 **ENQUEUE → 重新 SELECT 校验 → MODIFY → DEQUEUE → COMMIT WORK**，而不是先读后锁。

### 2.2 问题一：锁的范围小于读的范围（最严重）

```abap
FORM lock_records.

  LOOP AT s_lifnr.

    CLEAR gv_locked.

    CALL FUNCTION 'ENQUEUE_ZLFA1'
      EXPORTING
        iv_lifnr         = s_lifnr-low
      IMPORTING
        ev_locked        = gv_locked
      EXCEPTIONS
        conflict_lock    = 1
        OTHERS           = 2.

    IF sy-subrc <> 0.
      MESSAGE ID 'ZVND' TYPE 'E' NUMBER '002' WITH s_lifnr-low.
      CONTINUE.
    ENDIF.

  ENDLOOP.

ENDFORM.                       "lock_records
```

而读取是：

```abap
  SELECT lifnr name1 ort01 waerk eikto
    FROM lfa1
    INTO TABLE gt_vendor
    WHERE lifnr IN s_lifnr.
```

`s_lifnr` 是 `SELECT-OPTIONS`，是一个**区间集合**，不是单值。对着典型输入看一下：

| 用户输入 | `lock_records` 实际锁了谁 | `read_vendors` 实际读了谁 |
|---|---|---|
| `100000`（单值） | `100000` | `100000` |
| `100000-100010` | **只有 `100000`** | `100000` ~ `100010`（11 个） |
| `A..`(排除区间) | **只有 `A`** | 排除 `A` 之外的全部供应商 |
| 多行输入 3 行 | 每行各锁 1 个 | 每行的整个区间 |

也就是说，**只要用户填了区间或排除区间，绝大多数被读取的记录根本没有处于锁定状态**。锁带来的"一致性"承诺从一开始就是假的：别的用户可以在你读的同时改掉 `100010` 的数据，而你的邮件通知（如果将来真发出去）用的是旧值。

另外两个衍生问题：

- **`LOCK OBJECT` / 强制检查的思路**。区间加锁在 ABAP 里不能靠 `iv_lifnr` 传区间，标准做法是：先 `SELECT lifnr FROM lfa1 WHERE lifnr BETWEEN lv_low AND lv_high` 拿到**该范围内真实存在的**供应商号，再对每一个真实的号调 `ENQUEUE`。这样加锁集合和读取集合天然一致，也不会去锁那些数据库里根本不存在的号。
- **排除区间（`SIGN = 'N'`）被当成了包含区间处理**。`'A'` 的 `low = high = 'A'`，`ENQUEUE` 锁了一个用户明确表示"不要"的供应商。

### 2.3 问题二：选择屏没做非空校验 → 全量风险

`s_lifnr` 没有 `OBLIGATORY`，程序里也没有 `AT SELECTION-SCREEN` 校验空值。而 `SELECT-OPTIONS` 有个著名特性：**空选择屏时 `gt_selopt` 里有一行，`low`/`high` 都是初始值，`LOOP AT` 会执行一次**。

于是用户什么都不填直接 F8 时的实际行为：

1. `LOOP` 执行一次，`ENQUEUE` 一个初始（空白）的 `LIFNR` —— 大概率**不会**产生锁冲突，因为没有别的会话锁"供应商 0000000000"，于是 `sy-subrc = 0`，静默通过；
2. `read_vendors` 里 `WHERE lifnr IN s_lifnr` 等价于**不带任何条件**，读出该 Client 下**全部供应商**；
3. `notify_by_email` 对全量供应商逐条走逻辑（将来就是全量发信）。

一个本意是"通知一批供应商"的报表，被一次回车变成了全量数据遍历 + 全量通知。`IF gt_vendor IS INITIAL. MESSAGE ... TYPE 'S'` 这里挡不住——全量结果恰恰不为空。

修法很简单，两个都要做：

```abap
SELECT-OPTIONS s_lifnr FOR gs_sel-lifnr OBLIGATORY.
```

```abap
AT SELECTION-SCREEN ON VALUE-REQUEST FOR s_lifnr-low.
  " 视需要在此做供应商号有效性校验

AT SELECTION-SCREEN ON CHECK-ERROR.
  MESSAGE ID c_msg-class TYPE 'E' NUMBER '006'.
```

`OBLIGATORY` 是第一道防线，`AT SELECTION-SCREEN ON VALUE-REQUEST` 里拒绝超出允许范围的供应商号是第二道防线（针对的是"合法但超范围"的批量选择）。

### 2.4 问题三：自定义锁 FM 很可能根本不是有效的 LFA1 锁

```abap
CALL FUNCTION 'ENQUEUE_ZLFA1' ...
CALL FUNCTION 'DEQUEUE_ZLFA1' ...
```

SAP 表锁生效的前提是：该锁对象在 **`TLOCK01`** 里注册，且调用的 ENQUEUE/DEQUEUE FM 与注册名匹配（标准约定是 `ENQUEUE_E_<对象名>`，LFA1 的注册锁对象是 **`E_LFA1`**，所以标准 FM 是 **`ENQUEUE_E_LFA1`** / `DEQUEUE_E_LFA1`）。

`ENQUEUE_ZLFA1` 这个名字，如果是为 ZLFA1 自动生成的，那它对应的是 ZLFA1 这张**自定义表**的锁，跟标准 LFA1 的锁**互相不冲突**；如果是手写的，那它不会走标准锁的注册机制，同样不产生冲突。两种情况下结论一样：**这个"锁"不会挡住任何标准 MM 主数据维护会话，纯粹是给人看的心理安慰。** 这是最需要立刻确认的一件事——去 `TLOCK01` 查一下，或者直接问一句"这个 Z 模块是谁生成的、锁对象是什么"。

### 2.5 问题四：只在 LFA1 加锁，本来也不够

真要做供应商主数据维护，涉及的表至少有 `LFA1`（通用数据）、`LFUK`（公司代码数据）、`LFBK`（银行）、`LFGK`（税务）、地址相关表。只锁 `LFA1` 能挡住 80% 的并发场景，但挡不住"别人正在改这家供应商的银行信息"。如果这个程序后续真的会写入，锁对象清单要一起设计，而不是只锁主数据表。

### 2.6 问题五：只读程序加锁，是纯负收益

这是最值得跟需求方摊开讲的一条。表锁不是免费的：

- 它**挡住其他用户的正常操作**——别的 ABAP 顾问想改这批供应商时，会收到"已被用户 XXX 锁定"的报错；
- 它占用对话/模态 SAP 内存中的锁对象，占用工作进程；
- 而这个程序**一行数据库都没写**，所以它防不住任何东西。

结论：**如果程序保持只读，直接删掉 `lock_records` / `release_lock` 两个 `PERFORM`，把程序改成一次纯 `SELECT`。** 这才是当前代码的正确解。等哪天真要写 LFA1，再把锁加回来，而且要加得比现在严得多。

如果确实要发邮件，那也应该在锁**之外**发：邮件发送慢、还可能调 RFC/外部服务，把锁窗口撑到"读 → 邮件 → 释放"这段时间毫无收益。

### 2.7 加锁时机的理想形态（如果保留锁）

```abap
DATA: gt_locked  TYPE ty_vendor_tab,
      gt_conflict TYPE ty_vendor_tab.

FORM lock_records.
  DATA: lv_lifnr  TYPE lfa1-lifnr,
        lv_locked TYPE abap_bool,
        lv_exists TYPE ty_vendor_tab.

  LOOP AT s_lifnr INTO DATA(ls_range).

    "① 只处理包含区间；排除区间不锁（也不该被处理）
    IF ls_range-sign = 'N'.
      CONTINUE.
    ENDIF.

    "② 先解析出该区间内真实存在的供应商号，保证「加锁集合 = 读取集合」
    SELECT lifnr FROM lfa1 INTO TABLE @lv_exists
      WHERE lifnr BETWEEN @ls_range-low AND @ls_range-high.

    "③ 逐个加锁，把「拿到了」和「冲突了」分别记录
    LOOP AT lv_exists INTO DATA(ls_hit).
      CLEAR lv_locked.
      CALL FUNCTION 'ENQUEUE_E_LFA1'
        EXPORTING
          iv_lifnr        = ls_hit-lifnr
          iv_wait         = 'X'
        IMPORTING
          ev_locked       = lv_locked
        EXCEPTIONS
          conflict_lock   = 1
          OTHERS          = 2.
      CASE sy-subrc.
        WHEN 0.
          APPEND ls_hit TO gt_locked.
        WHEN 1.
          APPEND ls_hit TO gt_conflict.
        WHEN OTHERS.
          "④ OTHERS 不是「被占用」，不要伪装成 002
          PERFORM unlock_all.                 " 先还回去再报错
          MESSAGE ID c_msg-class TYPE 'E' NUMBER '007' WITH sy-msgid sy-msgno.
      ENDCASE.
    ENDLOOP.
  ENDLOOP.

  "⑤ 一次性汇总冲突，而不是遇到第一个就崩
  IF gt_conflict IS NOT INITIAL.
    PERFORM unlock_all.
    PERFORM build_conflict_text USING gt_conflict.
    MESSAGE ID c_msg-class TYPE 'E' NUMBER c_msg-lock_conflict WITH lv_text.
  ENDIF.
ENDFORM.                       "lock_records
```

注意 ⑤：原代码在 `LOOP` 里遇到冲突就 `TYPE 'E'` 直接终止，此时前面几次迭代**已经拿到的锁全部留在内存里**。正确模式是"要么全拿到，要么一个都不留"（原子获取）。

---

## 三、锁：解锁时机与泄漏路径

### 3.1 泄漏路径一：`E` 消息终止（最常见的泄漏源）

```abap
    IF sy-subrc <> 0.
      MESSAGE ID 'ZVND' TYPE 'E' NUMBER '002' WITH s_lifnr-low.
      CONTINUE.
    ENDIF.
```

ABAP 的 `MESSAGE ... TYPE 'E'` 是**消息终止语句**：它触发运行时错误、隐式 `ROLLBACK WORK`、把控制权交给 ABAP 运行时的错误处理，`CONTINUE` **永远不会执行**（这是典型的"看起来像容错、实际是死代码"）。而程序从抛出 `E` 到结束，中间没有任何解锁动作。

举例：选了 3 个供应商，第 2 个被别的用户锁着 → 第 1 个的锁被留在 SAP 内存里 → 程序 dump → 这个锁**一直存在**，直到对话超时被清掉（默认可以到小时级），或者等管理员在 `SM12`/`SM13` 里手工清。在这段时间里，所有正常的供应商维护动作都会撞上"记录被锁定"。

**唯一的兜底应该是异常处理块**，而不是"希望不报错"：

```abap
START-OF-SELECTION.

  PERFORM lock_records.
  PERFORM read_vendors.
  PERFORM notify_by_email.
  PERFORM release_lock.

  "任何未捕获的异常（短 dump、业务错误、用户中断）都要在此还锁
EXCEPTION WHEN OTHERS.
  PERFORM unlock_all.
  RAISING.
```

### 3.2 泄漏路径二：解锁对象来自"重新推导"而不是"实际持锁记录"

```abap
FORM release_lock.

  LOOP AT s_lifnr.
    CALL FUNCTION 'DEQUEUE_ZLFA1'
      EXPORTING
        iv_lifnr = s_lifnr-low.
  ENDLOOP.

  gv_dummy = 1.

ENDFORM.                       "release_lock
```

- 解锁时重新遍历 `s_lifnr` 推导键，而不是遍历"我实际成功锁了哪些键"的记录表。目前两边恰好都写成了 `s_lifnr-low`，所以**表面上对得上**——但这是两处相同错误逻辑的巧合，不是一致性保证。只要有人日后改了加锁那一段（比如按 §2.7 加了排除区间判断、或改成先 SELECT 再逐个加锁），解锁就会立刻不匹配并静默泄漏。
- **`DEQUEUE` 完全没有 `EXCEPTIONS`**。解锁失败（锁已经不存在、会话已被清理）会直接 dump，而这个 dump 发生在业务逻辑跑完之后、`release_lock` 中途——会出现"前几个解锁了、后面没解锁"的半吊子状态。
- `gv_dummy = 1;` 没有任何作用，属于填充代码。要么删掉，要么说明它原本想占位做什么。

正确形态：

```abap
FORM unlock_all.
  LOOP AT gt_locked INTO DATA(ls_locked).
    CALL FUNCTION 'DEQUEUE_E_LFA1'
      EXPORTING
        iv_lifnr = ls_locked-lifnr
      EXCEPTIONS
        others = 1.
    "解锁失败不应当让主流程失败：写日志 / ALERT 即可
  ENDLOOP.
  CLEAR gt_locked.
ENDFORM.                       "unlock_all
```

### 3.3 泄漏路径三：`DEQUEUE` 早于 `COMMIT WORK`

当前程序没有写数据，所以"解锁早于提交"暂时无害。但**这是个必须现在就写进规范的坑**：一旦按 §2.6 扩展成会 `MODIFY lfa1` 的版本，`COMMIT WORK` 一旦漏写或写在 `DEQUEUE` 之后，就会出现"记录已经解锁（别人能改了）+ 但改动还没提交（数据库里还是旧值）"的窗口。顺序永远是 `MODIFY → DEQUEUE → COMMIT WORK`。

### 3.4 时机小结

| 时机 | 是否正确 | 说明 |
|---|---|---|
| 加锁在读取之前 | ✅ 正确 | 顺序没问题 |
| 加锁范围 = 读取范围 | ❌ 错误 | `low` vs 整个 `s_lifnr` 区间 |
| 加锁前校验选择屏非空 | ❌ 缺失 | 空选择屏 = 全量 |
| 加锁原子性（全有或全无） | ❌ 缺失 | 遇首个冲突即终止，之前的锁泄漏 |
| 解锁对象来自持锁清单 | ❌ 错误 | 重新推导，隐性耦合 |
| 解锁有异常处理 | ❌ 缺失 | `DEQUEUE` 无 `EXCEPTIONS` |
| 异常路径统一解锁 | ❌ 缺失 | 无 `EXCEPTION WHEN OTHERS` 兜底 |
| 只读程序根本不该加锁 | ❌ | 最大的架构级问题 |

---

## 四、消息类：写法形式

先说好话。`MESSAGE ID 'ZVND' TYPE 'E' NUMBER '002' WITH s_lifnr-low.` 这种"消息类 + 消息号 + 参数"的写法，是正确的推荐做法：

- 文本写在 `T100`，业务方可以在不重新激活程序的情况下改文本；
- `WITH` 参数与 `T100` 里的 `&1..&4` 占位符对应，支持多语言；
- 比 `MESSAGE e002 WITH ...` 更容易被全文搜索定位。

作者在头注释里专门写了一句 "Uses MESSAGE ID / NUMBER as the positive pattern"，说明是有意识的选择。**形式上是对的，问题全在内容和周边。**

---

## 五、消息类：六个实际问题

### 🔴 问题 1：消息类 `'ZVND'` 是 4 位，运行时找不到消息类

```abap
MESSAGE ID 'ZVND' TYPE 'I' NUMBER '001'.
MESSAGE ID 'ZVND' TYPE 'E' NUMBER '002' WITH s_lifnr-low.
MESSAGE ID 'ZVND' TYPE 'S' NUMBER '003'.
MESSAGE ID 'ZVND' TYPE 'W' NUMBER '004' WITH ls_vendor-lifnr.
MESSAGE ID 'ZVND' TYPE 'W' NUMBER '005'.
```

`T100` 的消息类字段 `ARBGB` 长度是 **3**。`MESSAGE ID` 传入 4 位字面量时，运行时会截取前 3 位，即实际使用 **`'ZVN'`**。而 `T100` 里不会有 `'ZVN'` 的这 5 条消息——**程序从第一次弹消息开始就报"消息类未找到"**，对 `'E'`/`'I'`/`'W'` 而言这本身就是一次运行时错误终止。

而报表名叫 `ZVENDOR_NOTIFY`，惯例消息类取前 3 位正好是 **`ZVN`**。所以这极可能是 `ZVN` 手滑多打了一个 `D`。

**修法**（推荐顺手把字面量提成常量，正好防止同类笔误再发生）：

```abap
CONSTANTS:
  BEGIN OF c_msg,
    class         TYPE symsgid VALUE 'ZVN',      " 只有 3 位，别写成 'ZVND'
    no_data       TYPE symsgno VALUE '003',
    lock_conflict TYPE symsgno VALUE '002',
    no_currency   TYPE symsgno VALUE '004',
  END OF c_msg.
```

```abap
MESSAGE ID c_msg-class TYPE 'I' NUMBER c_msg-no_data.
```

用常量的额外收益：SEU 里搜不到字面量的情况消失、`/nend` 不再因为拼错一个字符而"消息类不存在"，且消息类一旦要改（拆成两个类、或与其他程序合并）只改一处。

### 🔴 问题 2：`TYPE 'S'` 被用来报"没查到数据"

```abap
  IF gt_vendor IS INITIAL.
    MESSAGE ID 'ZVND' TYPE 'S' NUMBER '003'.
  ENDIF.
```

`'S'` 是**成功消息**，语义是"操作成功完成"。用它来表达"查询无结果"，是把状态码用反了。而且这里有两个连带问题：

- **没有 `RETURN`。** 空结果时直接往下走，`notify_by_email` 会执行一遍空循环，然后再弹 `W 005`——用户先看到"成功"，紧接着看到一条警告，观感是自相矛盾的。空结果应当是提前返回：
  ```abap
  IF gt_vendor IS INITIAL.
    MESSAGE ID c_msg-class TYPE 'I' NUMBER c_msg-no_data.
    RETURN.
  ENDIF.
  ```
- **查到有数据的时候反而什么都不说。** 消息是对称的：有异常分支有提示，成功分支没提示。这不叫"简洁"，叫"没想清楚"。

### 🟠 问题 3：`TYPE 'W'` 放在 `LOOP` 里，只会留下最后一条

```abap
  LOOP AT gt_vendor INTO DATA(ls_vendor).

    IF ls_vendor-waerk IS INITIAL.
      MESSAGE ID 'ZVND' TYPE 'W' NUMBER '004' WITH ls_vendor-lifnr.
    ENDIF.

  ENDLOOP.
```

SAP 的消息行一次只保留**一条**消息，在循环里连续发消息，前面的会被直接覆盖丢弃。所以当 10 个供应商缺币种时，用户只会看到最后一个供应商号，且没有任何"还有 N 条未显示"的提示。这是新手最常见的消息误用。

正确做法是**聚合成一条**：

```abap
  DATA lv_cnt TYPE i.

  LOOP AT gt_vendor INTO DATA(ls_vendor).
    IF ls_vendor-waerk IS INITIAL.
      lv_cnt = lv_cnt + 1.
    ENDIF.
  ENDLOOP.

  IF lv_cnt > 0.
    MESSAGE ID c_msg-class TYPE 'W' NUMBER c_msg-no_currency WITH lv_cnt.
  ENDIF.
```

如果确实要逐条呈现给用户看，正确姿势不是靠消息机制，而是把明细收进一个内表，循环结束后走 `ALV` 或拼接成一条汇总消息。

### 🟠 问题 4：消息之间会互相冲掉

同一个程序里连着发 `003` → `004` → `005`，消息行只有一个位置，最终用户只看到**最后弹出的那一条**。所以"我明明写了成功提示为什么用户看不到"的答案通常是：被后面覆盖了。

规范做法：把过程中的所有提示收集到一个结果内表（`ty_vendor_tab` 已有 `status` 字段，正好可以承载"已通知/有警告"的标记），在程序末尾用**一条** `S` 消息汇总，同时输出一个 `ALV` 列表让用户看到全貌：

```abap
  DATA lv_summary TYPE string.
  lv_summary = |已通知 { lv_ok } 家，{ lv_warn } 家存在数据问题。|.
  MESSAGE ID c_msg-class TYPE 'S' NUMBER '008' WITH lv_summary.
```

### 🟡 问题 5：`'W'` 的检查对象和它的意图不匹配

```abap
  DATA lt_recipients TYPE STANDARD TABLE OF adr_email.
  DATA lv_body       TYPE string.

  CONCATENATE LINES OF lt_recipients INTO lv_body SEPARATED BY space.

  " ... 中间把 gt_vendor 全部标成 'X' ...

  IF lv_body IS INITIAL.
    MESSAGE ID 'ZVND' TYPE 'W' NUMBER '005'.
  ENDIF.
```

- 判断的应该是"有没有收件人"，即 `lt_recipients IS INITIAL`，而不是把收件人拼接出来的 `lv_body`。现在这个写法里 `lv_body` 在判断之后**再也没被用过**，将来有人改成"用 `lv_body` 组装正文"时，这条"无收件人"检查会**静默失效**——因为正文拼接出来几乎不可能为空。
- `CONCATENATE LINES OF` 用在地址上也是类型味道：多个收件人地址应该是**多条收件人记录**（邮件类接口的 recipient 结构），而不是拼进正文字符串里。真要发信，得用 `cl_bc_...` / Business Communication Suite 的收件人结构。
- 整段是死代码：`lt_recipients` 声明后从未 `SELECT adr6`，所以它恒为空，`lv_body` 恒为空，`W 005` **每次执行都会弹**。这不是"数据质量告警"，这是"功能没写"。与其弹一个误导性的警告，不如直接把它写出来，或者干脆不做。

### 🟡 问题 6：`SET HANDLER 'ON_HELP_REQUEST'` 是无效代码

```abap
INITIALIZATION.
  SET HANDLER 'ON_HELP_REQUEST'.
```

这个程序是纯 `REPORT`/`FORM`，没有任何类定义、没有任何全局方法，`ON_HELP_REQUEST` 这个处理器在程序里不存在；而且 `SET HANDLER` 通常写在过程化程序的初始化段里，也不是这个位置。**这条语句要么激活时报语法错、要么是句无效的废代码**，两种都得删。

F1 帮助用 `AT SELECTION-SCREEN ON HELP-REQUEST` 事件块实现已经是标准做法，原代码在这个事件块里用 `'I'` 消息占位是可以的（会替代标准帮助弹窗），但更好的做法是给选择屏字段挂真正的 F1 文本，而不是弹一条消息。

顺带一提：`T100` 的文本要按语言维护。至少要维护 `1`（系统语言）和用户登录语言，否则报"消息类/消息号未在当前语言下找到"，这在多语言生产系统上同样会变成运行时终止——和 §5 问题 1 叠加。

---

## 六、顺手发现的其他问题

| 位置 | 问题 | 严重度 |
|---|---|---|
| 全局 | **完全没有授权检查**。读 LFA1（供应商主数据，含商业敏感信息）以及将来要读的 `ADR6`（地址管理，通常需单独授权对象）都不检查 AUTHORITY-CHECK，在大多数客户的 SoD 框架下会被审计直接记缺陷 | 🔴 |
| `MODIFY gt_vendor FROM ls_vendor` | 写的是一个进程结束就消失的内表，`status` 字段没有任何消费者，属于无效写入。真要改内表行，直接 `LOOP AT gt_vendor ASSIGNING FIELD-SYMBOL(<row>)` 即可，不需要 `MODIFY` | 🟡 |
| `SELECT ... eikto` | `eikto`（联系电话）取出来从头到尾没被使用，属于无效取数；`ADR6` 类型被引用却没被 SELECT | 🟡 |
| `gv_locked` | 声明为全局 `abap_bool`，在 `LOOP` 里 `CLEAR` 后接收 `ev_locked`，**判断的却是 `sy-subrc`，`gv_locked` 从未被读取**。全局命名 + 无消费者，纯粹是噪音 | 🟡 |
| `OTHERS = 2` 后仍报 002 | 把授权失败、类型转换失败等技术异常统一伪装成"记录被锁"。这类错误要区别对待，否则排查时会被带偏 | 🟠 |
| `ev_locked` 未使用 | 标准生成的锁 FM 用 `EV_LOCKED` 表达"记录已处于锁定状态"，`CONFLICT_LOCK` 异常表达"被**别人**锁"。两者语义不同，只看 `sy-subrc` 会漏掉自己重复加锁的场景 | 🟡 |
| `gv_dummy TYPE i` | 全程序无任何作用 | 🟢 |
| `gs_vendor` | 只被用作 `SELECT-OPTIONS` 的参照字段，与"当前供应商记录"这个直觉含义冲突，建议改名 `gs_sel` | 🟢 |
| 全局 | **无列表输出**。用户跑完只看到几条消息，看不到处理了哪些供应商；配合"报表名说 maintenance 但不写库"，整体行为不可预期 | 🟠 |
| 全局 | 无 `AT SELECTION-SCREEN ON VALIDATION`、无结果条数上限控制，大区间选择同样会拖出巨量数据 | 🟠 |

---

## 七、建议的最小改造顺序

按"投入产出比"排，前两步就能堵掉最要命的洞：

**第 1 步：删锁。** 保持只读的话，移除 `lock_records` / `release_lock` 的两个 `PERFORM` 和两个 `FORM`。零成本，直接消灭全部锁泄漏风险和对他人的干扰。

**第 2 步：修消息。**
- `'ZVND'` → `'ZVN'`，并提成 `CONSTANTS`；
- `003` 由 `'S'` 改 `'I'` 并加 `RETURN`；
- `004` 改为聚合计数；
- 在 `T100` 里补齐 5 条文本及所需语言；
- 末尾统一一条 `S` 汇总消息。

**第 3 步：选择屏加固。** `OBLIGATORY` + 供应商号有效性校验 + 结果条数上限。

**第 4 步：补授权检查。** 按客户 SoD 要求，对 LFA1 读取和 ADR6 读取分别加 AUTHORITY-CHECK。

**第 5 步（如果将来真的要写数据）：** 按 §2.7 重写加锁（先解析真实号再逐个加、冲突汇总、解锁走持锁清单），加 `EXCEPTION WHEN OTHERS` 兜底解锁，锁定 `COMMIT WORK` 的顺序，并把锁窗口压到最小——邮件发送一律放到锁外面。

---

## 八、一句话总结

锁的部分，**顺序对了、范围错了、时机没有兜底**，最合理的结论是"只读程序不该加锁"；消息的部分，**写法形式对了、语义和一致性错了**，一个 4 位消息类会让整段提示全部失效，而 `'S'` 用反、`'W'` 塞在循环里、成功路径无提示这三个问题叠加起来，实际效果是用户基本看不到这个程序想告诉他的任何事。

两处好习惯值得保留：**锁在读之前加**、**用 `MESSAGE ID/NUMBER` 而不是硬编码字面量**。剩下的问题都是在这两点周围缺少配套纪律造成的——锁缺清单、缺兜底、缺一致性；消息缺常量、缺对称、缺聚合。