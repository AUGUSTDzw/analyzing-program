# ZCL_GRADE_CALC 继承与多态分析报告

## 0. 一句话结论

继承骨架和"模板方法 + 重定义点"的多态设计思路是对的，但**当前代码不能按预期工作**：`ratio_of` 的可见性设置会直接导致编译失败；`zcl_grade_strict` 重写 `calculate` 时既丢了返回结果、又把"分数"当"比率"传进评级方法，导致严格评级实际恒为 `'F'`；`reserve_seat` 存在字符串截断，所有座位号会被截成同一个值。评级判定全部用 `CASE` 等值匹配一个连续比率，本身就是错误的建模方式。

---

## 1. 类结构与继承链

### 1.1 类池的特殊语义

```abap
CLASS-POOL zcl_grade_calc.

PUBLIC
ABSTRACT
CREATE PUBLIC.
```

这是一个 **Class Pool（类池）**。类池里的全局类遵循一条 ABAP 特有规则：**没有写 `INHERITING FROM` 的全局类，隐式继承它所在的那个类池全局类**。所以 `zcl_grade_abc` 的父类是 `zcl_grade_calc`（源码里完全看不出来，这是最容易误读的一点）。

### 1.2 完整继承图

```
cx_static_check
      ▲
      │ INHERITING FROM
cx_grade_error                      (全局异常类, 位于类池中)
      ▲
      │ 隐式继承 (类池规则)
zcl_grade_calc        PUBLIC ABSTRACT  CREATE PUBLIC   ← 类池全局类
      ▲
      │ 隐式继承 (类池规则)
zcl_grade_abc         PUBLIC ABSTRACT  CREATE PUBLIC
      │
      ├── INHERITING FROM ──► zcl_grade_strict    FINAL   (具体)
      └── INHERITING FROM ──► zcl_grade_lenient   FINAL   (具体)
```

具体类只有 **2 个**（strict / lenient）。文件头注释写的 "one reference, three implementations"（一种引用、三种实现）**与代码不符**——第三个实现（`zcl_grade_calc->derive_grade`，第 261 行）因为基类是 `ABSTRACT`、子类又全部重写了 `derive_grade`，属于**永远不可达的死代码**。

### 1.3 可见性矩阵

| 成员 | 声明位置 | 段 | strict 可见 | lenient 可见 |
|---|---|---|---|---|
| `calculate` / `calculate_fee` / `reserve_seat` / `get_scale` | pool | PUBLIC | ✓ | ✓ |
| `mv_max_points` / `mv_errors` | pool | PROTECTED | ✓ | ✓ |
| `validate` / `derive_grade` / `lock_enrolment` | pool | PROTECTED | ✓ | ✓ |
| **`ratio_of`** | pool | **PRIVATE** | **✗** | **✗** |

`PRIVATE` 成员在 ABAP 中**会被继承但对子类不可见**。这直接引出第 5.1 节的 P0 缺陷。

### 1.4 重定义点（Polymorphic Hooks）

| 重定义点 | 基类实现 | strict | lenient |
|---|---|---|---|
| `derive_grade` (PROTECTED) | pool: `0.8→'B'`, else `'C'` | 重写：`0.9→'A+'`, `0.8→'A'`, else `'F'` | 重写：`0.6→'C'`, else `'D'` |
| `threshold` (PROTECTED, 定义在 abc) | abc: `0.5` | 重写：`0.7` | **未重写**（继承 0.5） |
| `calculate` (PUBLIC) | abc: 模板方法 | **整体重写并调 super** | 未重写，直接用模板 |
| `constructor` (PUBLIC) | pool | 重写，仅转调 super | 未重写 |

---

## 2. 多态是怎么生效的

多态在这里靠的是 ABAP 的 **动态绑定（late binding）**：方法体里写的是**静态引用**（编译期只记录"该类层次中存在这个方法"），运行时按 `this` 的**实际类型（Dereferencing 后的动态类型）**去找最具体的实现。前提是：

1. 父类方法 **不是 FINAL**；
2. 子类用 `REDEFINITION`（`zcl_grade_strict` 对 `derive_grade` / `threshold` 都写了）声明为重定义；
3. 调用点在 `PROTECTED`（或同一次调用的隐式 `this`）上下文中，静态可见性成立。

### 2.1 模板方法骨架（`zcl_grade_abc->calculate`，第 109-121 行）

```abap
METHOD calculate.
  validate( it_scores ).
  DATA lv_ratio TYPE p DECIMALS 4.
  lv_ratio = ratio_of( it_scores ).                        "← 私有方法，子类不可见（P0-1）

  rs_result-points  = lv_ratio * mv_max_points.
  rs_result-grade   = derive_grade( iv_ratio = lv_ratio ).  "← 动态绑定点 ①
  rs_result-passed  = COND #( WHEN lv_ratio >= threshold( iv_ratio = lv_ratio )   "← 动态绑定点 ②
                              THEN abap_true ELSE abap_false ).
ENDMETHOD.
```

这里 `derive_grade` 和 `threshold` 就是两个**重定义钩子（hook）**。abc 本身不决定评级规则和及格线，只规定"算出比率 → 问子类要等级 / 问子类要门槛"。

### 2.2 三条实际执行路径

**路径 A：`zcl_grade_lenient`（未重写 `calculate`，最干净的路径）**

```
lenient->calculate (继承自 abc)
  → validate        (pool, 无重定义)
  → ratio_of        (pool)                       ← 见 P0-1
  → derive_grade    动态命中 lenient → 'C' / 'D'
  → threshold       动态命中 lenient 未重写 → abc 的 0.5
```
`passed` = 比率 ≥ 0.5。

**路径 B：`zcl_grade_strict`（重写了 `calculate`，模板被绕过）**

```
strict->calculate
  → super->calculate  (= abc->calculate)
        → validate / ratio_of
        → derive_grade  动态命中 strict → 'A+' / 'A' / 'F'
        → threshold     动态命中 strict → 0.7   ★ 结果算完后被覆盖，等于白跑
  → 覆盖 grade / passed（用错误的入参，见 P0-2 / P0-3）
```

**路径 C：`get_scale`** —— 虽然是 `PUBLIC` 且可被子类重定义，但**没有任何子类重写它**，所以返回恒为硬编码的 `'A+ A F'`（第 227 行），和 lenient 的 `'C'/'D'`、pool 自己的 `'B'/'C'` 三者都对不上。这个方法本该是最典型的多态展示点，结果写成了常量。

### 2.3 多态未被验证

全文**没有任何一处客户端代码**，没有 `DATA go_calc TYPE REF TO zcl_grade_abc` 然后往里塞 `zcl_grade_strict` / `zcl_grade_lenient` 再调 `calculate` 的写法。也就是说多态机制**只是搭好了架子，从未被执行过一次**，也因此上面那些缺陷不会在语法层面暴露——"能编译"和"跑得对"在这里是两件事。

---

## 3. 严格评级（`zcl_grade_strict`）判定逻辑的问题

严格评级的核心代码只有这 12 行，但里面有 **4 个叠加的错误**：

```abap
METHOD calculate.
  super->calculate(
    IMPORTING it_scores    = it_scores
    RECEIVING rs_result    = DATA(ls_result)
    EXCEPTIONS cx_grade_error = 1 ).
  IF sy-subrc = 1.
    RAISING cx_grade_error.          " 无参 RAISING = 原样重抛，语义正确但属冗余转发
  ENDIF.

  rs_result-grade  = derive_grade( iv_ratio = rs_result-points ).          " ①
  rs_result-passed = COND #( WHEN rs_result-points >= mv_max_points * 0.7  " ②
                             THEN abap_true ELSE abap_false ).
ENDMETHOD.

METHOD derive_grade.
  CASE iv_ratio.
    WHEN 0.9. rv_grade = 'A+'.
    WHEN 0.8. rv_grade = 'A'.
    WHEN OTHERS. rv_grade = 'F'.
  ENDCASE.
ENDMETHOD.
```

### 问题①（致命）：返回结果整体丢失

`super->calculate` 的结果被接进了**内联变量 `ls_result`**，而 `rs_result`（本方法的 `RETURNING` 形参）**从未被赋值**。方法体里只写了 `rs_result-grade` 和 `rs_result-passed` 两个分量，`points` / `netwr` / `waers` 保持初始值。

```abap
" 错误：ls_result 与 rs_result 是两个独立的结构体
" 正确：
MOVE ls_result TO rs_result.  " 或 rs_result = ls_result.
```

后果：`calculate` 返回的 `points` 恒为 0。下游 `calculate_fee` 用它算金额：

```abap
lv_amount = is_result-points * is_fee-netpr.   "→ 恒为 0，账单金额恒为 0
```
**整条计费链路静默归零**，且不会报任何错。

### 问题②（致命）：单位错乱——把分数当比率传

第 ① 行传的是 `rs_result-points`，而 `super->calculate` 里 `points = 比率 × mv_max_points`（第 116 行），也就是**绝对分数**；但 `derive_grade` 的语义是**比率 0~1**（pool 版本用 `WHEN 0.8`，abc 的 `threshold` 也返回 0.5/0.7）。

`mv_max_points` 默认 100 时，满分对应 `points = 90.00`，`CASE` 拿 `90.00` 去比 `0.9` 和 `0.8`：

| 实际得分比例 | points | `derive_grade(90.00)` |
|---|---|---|
| 100%（满分） | 100.00 | `'F'` |
| 90% | 90.00 | `'F'` |
| 80% | 80.00 | `'F'` |
| 0.9% | 0.90 | `'A+'`（荒谬） |

**严格评级几乎恒为 `'F'**，且会和第 ② 行的判定自相矛盾：得到 80 分时 `passed = (80 >= 70) = abap_true`，最终输出 **"及格 + 等级 F"** 的组合。（正确写法应该是 `derive_grade( iv_ratio = ls_result-points / mv_max_points )`，或者干脆不要重写 `calculate`。）

### 问题③：`passed` 判定重复实现，绕过重定义点

第 ② 行用 `mv_max_points * 0.7` 硬编码了及格线，而 strict **已经**通过重定义 `threshold` 提供了 0.7。结果是 `threshold` 的重定义虽然在 `super->calculate` 里**被执行了**，但返回值立刻被覆盖——成为纯粹的无效计算。同一份业务规则（严格线 0.7）散落在两个地方，改一处必漏另一处。

顺带一个类型细节：`mv_max_points`（`p DECIMALS 2`）× `0.7`（1 位小数）得到 3 位小数，与 2 位小数的 `points` 比较，临界值上会再引入一层舍入歧义。

### 问题④（方法级根因）：用 `CASE` 等值匹配连续比率

这是三个类**共有的建模错误**，不只是 strict 的问题：

```abap
CASE iv_ratio.
  WHEN 0.9. ...      " 数值 CASE = 精确相等，不是区间
  WHEN 0.8. ...
  WHEN OTHERS. ...
ENDCASE.
```

比率是连续量，`WHEN 0.9` 要求它**恰好等于 0.9000**。而实际值还受两级精度挤压：

* `ratio_of` 的 `rv_ratio TYPE p`（未写 `DECIMALS`，默认 **2 位**）；
* `iv_ratio TYPE p` 形参同样是 **2 位**。

于是 0.895 被舍入成 0.90 → `'A+'`，而 0.806 被舍入成 0.81 → 落入 `OTHERS` → `'F'`。**0.1% 的分数差异会导致等级从 A+ 直接掉到 F**，评级完全抖动。

lenient 更离谱：`WHEN 0.6 → 'C'`、`OTHERS → 'D'`，所以 **0.95 的比率（学得最好）拿到 'D'**，而 `passed` 又因为阈值 0.5 是 `abap_true`——出现"及格但评级 D"。**"等级"和"及格"两个概念在实现里完全脱钩。**

正确建模应该是区间降序匹配，而不是等值：

```abap
METHOD derive_grade.
  CASE iv_ratio.
    WHEN lt 0.6. rv_grade = 'F'.
    WHEN lt 0.7. rv_grade = 'D'.
    WHEN lt 0.8. rv_grade = 'C'.
    WHEN lt 0.9. rv_grade = 'B'.
    WHEN OTHERS. rv_grade = 'A'.
  ENDCASE.
ENDMETHOD.
```

### 3.5 `validate` 自身的缺陷（会先一步掐死正确路径）

```abap
LOOP AT it_scores INTO DATA(lv_score).
  IF lv_score IS INITIAL OR lv_score IS INITIAL.   " 同一条件写了两遍
    mv_errors = mv_errors + 1.
  ENDIF.
ENDLOOP.
IF mv_errors > 0.
  RAISE EXCEPTION TYPE cx_grade_error.
ENDIF.
```

* **条件重复**：两个分支完全相同，高度怀疑是复制粘贴时丢了第二个条件（本意大概是 `lv_score > mv_max_points`，即上界校验）。结果是"**只要有一个 0 分就整批抛异常**"，而负分、超满分（比率 > 1）反而放行。
* **实例状态污染**：`mv_errors` 是实例属性且只增不减。第一次因 0 分失败后，该对象**此后再也无法成功计算**，构造函数里初始化的 0 也失去了意义。
* **异常无信息**：`cx_grade_error` 的构造函数把 `iv_text` 直接丢弃（见 5.3），所以抛出去的是**空文本、无消息类、无消息号**的异常。第几个成绩非法、非法值是多少，排查时无从得知。

---

## 4. 其余功能性问题

### 4.1 `reserve_seat`：座位号被截断成同一个值（P0）

```abap
DATA lv_next TYPE i.
...
rv_seat = |SEAT{ lv_next ALPHA = OUT }|.   " rv_seat TYPE char10
```

`lv_next` 是 4 字节整型，`ALPHA = OUT` 会把它转成 **10 个字符**（左补零），加上前缀 `SEAT` 共 **14 个字符**，而返回类型 `char10` **只保留最左边 10 个字符**。

对任何小于 1,000,000 的号码，截断后都是 `"SEAT000000"`——**所有座位号完全相同，并发下会互相覆盖**。这类"字符串模板长度溢出"的坑在 SE37 里不会报错，只有运行时数据暴露。

另外：`DO 5 TIMES` 对 `NUMBER_GET` 的 `internal_error` / `buffer_overflow` 重试 5 次，对确定性失败是纯粹的资源浪费；号段 `ZGRADE/ZSEAT` 若未在 SNRO 中配置，`lv_next` 可能返回初始值而 `sy-subrc = 0`，需要显式校验号码是否为 0。

### 4.2 `lock_enrolment`：锁失败被伪装成"未锁定"（P1，安全相关）

```abap
CALL FUNCTION 'ENQUEUE_ZGRADE_ENROL'
  EXPORTING  iv_student = iv_student
  IMPORTING ev_locked  = lv_locked
  EXCEPTIONS conflict_lock = 1
             OTHERS         = 2.

rv_locked = lv_locked.      " ← sy-subrc 从未被检查
```

* `conflict_lock` 或任何其他异常时，`lv_locked` 保持初始值 `abap_false`，**语义却是"未锁定 / 名额可用"**。真实情况是"锁被别人持有、状态未知"。调用方据此继续走选座流程 → **双重占座**。这是典型的"把失败映射成成功的否定态"，属于会造成数据事故的缺陷。
* 全类**没有任何解锁方法**（无 `DEQUEUE` 配对），`lock_enrolment` 也没有被任何地方调用——既可能泄漏锁，也可能是遗留死代码。
* `ENQUEUE_ZGRADE_ENROL` 是自定义 FM，`IMPORTING ev_locked` 这种签名不像标准 FM 的做法，需确认对象真实存在。

### 4.3 `calculate_fee`：币种错配 + 重复赋值（P1）

```abap
rs_bill-waers = is_fee-waers.          " ① 先赋文档货币
lv_amount     = is_result-points * is_fee-netpr.
rs_bill-netwr = lv_amount.             " 金额在 is_fee-waers 计价下算得
rs_bill-waers = is_fee-waerk.          " ② 又被本地货币覆盖，① 成了死代码
```

* `netpr` 是**文档货币价格**，算出的 `netwr` 天然是 `is_fee-waers` 口径；但最后 `waers` 被写成 `waerk`（**本地货币**），金额与币种**单位不匹配**——典型的隐式换算错误。要么保留 `waers`，要么做一次明确的汇率换算。
* `netwr` 也没有按货币小数位（通常 2 位）做 `ROUND`，只是靠类型转换隐式舍入。
* 方法签名声明 `RAISING cx_grade_error` 却**从不抛出**；`is_fee-netpr` 为负也没有校验。
* 语义上把 `ty_result`（成绩结果）**复用为账单结构**，把 `grade` / `passed` 塞进账单字段，模型被污染——应该单独定义 `ty_bill`。

### 4.4 `get_scale` 与死代码（P2）

```abap
METHOD get_scale.
  rs_scale = 'A+ A F'.      " 形参名叫 rs_（结构体惯例）却是 string
ENDMETHOD.
```

* 返回值只对应 strict 的刻度，与 lenient（`C`/`D`）、pool 自身（`B`/`C`）全部矛盾。
* 形参 `rs_scale` 用 `rs_` 前缀但类型是 `string`，命名误导。
* 本应作为多态展示点（各子类重写返回自己的刻度），现在是不可变的常量。

---

## 5. 缺陷清单（按严重度）

### P0 — 阻断 / 功能性完全失效

| # | 位置 | 问题 |
|---|---|---|
| P0-1 | `:114` vs `:76` | `ratio_of` 声明为 `PRIVATE`，却在子类 `zcl_grade_abc->calculate` 中调用 → **编译错误**（私有成员对子类不可见）。修复：改为 `PROTECTED`。 |
| P0-2 | `:151-166` | 重写 `calculate` 时结果只接进 `ls_result`，`rs_result` 未回写 → `points`/`netwr`/`waers` 全丢，计费金额恒为 0。 |
| P0-3 | `:162` | `derive_grade( iv_ratio = rs_result-points )` 把**绝对分数**当**比率** → 严格评级恒 `'F'`，并与 `passed` 自相矛盾。 |
| P0-4 | `:305` | `\|SEAT{ lv_next ALPHA = OUT }\|` 14 字符赋给 `char10` → 座位号被截成同一个值。 |

### P1 — 逻辑错误

| # | 位置 | 问题 |
|---|---|---|
| P1-1 | `:170-177` / `:199-205` / `:261-267` | 三处 `derive_grade` 都用 `CASE` **等值**匹配连续比率，且比率只有 2 位小数 → 评级剧烈抖动、满分拿 F、0.95 拿 D。 |
| P1-2 | `:233` | `IF lv_score IS INITIAL OR lv_score IS INITIAL.` 条件重复，疑似丢失上界校验；0 分被判非法、超满分放行。 |
| P1-3 | `:234` / `:222` | `mv_errors` 只增不减 → 实例被"毒化"，一次失败后续永不可用。 |
| P1-4 | `:211-215` | `cx_grade_error` 丢弃 `iv_text`，所有异常无文本、无消息类/号，线上不可诊断。 |
| P1-5 | `:163` | strict 重复实现 `passed` 判定，硬编码 0.7；`threshold` 重定义沦为无效死代码，规则双写。 |
| P1-6 | `:319-330` | `lock_enrolment` 不检查 `sy-subrc`，把"锁失败"映射为"未锁定" → 双重占座风险；且无配对解锁，锁会泄漏。 |
| P1-7 | `:275-283` | `waers` 双重赋值（后者覆盖前者），金额口径与币种不匹配；`netwr` 未按货币小数位舍入。 |
| P1-8 | `:261-268` | pool 的 `derive_grade` 永不可达（pool 抽象 + 两个子类都重写）；表头注释"三种实现"不实。 |

### P2 — 健壮性与可维护性

| # | 位置 | 问题 |
|---|---|---|
| P2-1 | `:221` / `:257` | `COALESCE( iv_max_points, 100 )` 把**显式传入的 0** 也当成未传；`mv_max_points = 0` 时 `ratio_of` 除零。 |
| P2-2 | `:245` | `lv_sum TYPE p DECIMALS 4`（默认长度 8 → 4 位整数）累加，分数总和 > 9999 即溢出报 dumps；未做溢出防护。 |
| P2-3 | `:292-310` | 对确定性错误重试 5 次无意义；未校验号码段未配置时 `number` 为初始值的情形。 |
| P2-4 | `:154` | `RECEIVING rs_result = DATA(ls_result)` 需 7.50+；低版本须预先声明内联变量（建议兼容性时改写）。 |
| P2-5 | `:47` | `calculate_fee` 声明 `RAISING cx_grade_error` 却从不抛出。 |
| P2-6 | `:154-160` | 捕获后仅 `RAISING cx_grade_error` 原样转发，属冗余；直接不捕获即可。 |
| P2-7 | `:226-228` | `rs_scale TYPE string` 命名与类型不符；`get_scale` 不参与多态。 |
| P2-8 | 全文 | 无客户端调用代码、无单元测试，多态机制从未被执行验证过。 |
| P2-9 | `:34-36`/`:146-148` | 构造函数三级链式转调，每个子类都手写一遍 `super->constructor`，新增子类极易漏调。 |

---

## 6. 风险与影响面

* **静默失败为主**：P0-2、P0-3、P1-1 全部不会抛异常、不会 dump，只会输出**看起来正常但业务上错误**的数据（等级 F、金额 0、及格却 F）。这类缺陷在 UAT 和生产都极难靠"跑一下看看"发现，只能靠断言和单元测试。
* **金额链路不可信**：`calculate_fee` 依赖 `calculate` 的 `points`，P0-2 使其恒为 0 → 账单金额恒为 0（若币种错配同时生效，还可能出现金额与币种不一致的脏数据）。
* **并发安全**：`lock_enrolment` 的失败映射 + 缺失解锁，是本类中唯一可能造成**跨用户数据事故**的问题。
* **可诊断性为零**：`cx_grade_error` 丢弃文本，异常路径上无法定位是第几条成绩、哪条锁失败。
* **多态的收益尚未兑现**：抽象层已经就位，但没有任何调用方通过基类引用使用它，因此"加一个评分体系只需新增子类"这个承诺目前只是结构上的，尚未被验证。

---

## 7. 修复建议

### 7.1 让 `ratio_of` 可见（P0-1）

```abap
PROTECTED SECTION.
  METHODS ratio_of
    IMPORTING it_scores TYPE STANDARD TABLE OF p WITH EMPTY KEY
    RETURNING VALUE(rv_ratio) TYPE p
    RAISING   cx_grade_error.
```

### 7.2 异常必须带上下文（P1-4）

```abap
CLASS cx_grade_error DEFINITION PUBLIC FINAL INHERITING FROM cx_static_check.
  PUBLIC SECTION.
    CONSTRUCTORS:
      constructor IMPORTING iv_text TYPE string OPTIONAL.
ENDCLASS.

CLASS cx_grade_error IMPLEMENTATION.
  METHOD constructor.
    super->constructor( ).
    IF iv_text IS SUPPLIED.
      text = iv_text.                       " 或构造 message = 'ZGRADE' id = '001'
    ENDIF.
  ENDMETHOD.
ENDCLASS.
```

### 7.3 评级改成区间降序匹配，参数统一为比率（P0-3 / P1-1）

```abap
" zcl_grade_strict
METHOD derive_grade.
  CASE iv_ratio.
    WHEN lt 0.6.  rv_grade = 'F'.
    WHEN lt 0.7.  rv_grade = 'D'.
    WHEN lt 0.8.  rv_grade = 'C'.
    WHEN lt 0.9.  rv_grade = 'B'.
    WHEN OTHERS.  rv_grade = 'A+'.
  ENDCASE.
ENDMETHOD.

METHOD get_scale.
  rs_scale = 'A+ A B C D F'.
ENDMETHOD.
```

### 7.4 `calculate` 不该重写——让模板方法自己跑完（P0-2 / P1-5）

最干净的修复是**删掉 strict 的 `calculate` 重写**，只保留 `derive_grade` + `threshold` 两个钩子；及格线自动复用重定义的 `threshold`，`points` 也不会丢：

```abap
CLASS zcl_grade_strict DEFINITION PUBLIC FINAL INHERITING FROM zcl_grade_abc CREATE PUBLIC.
  PUBLIC SECTION.
    METHODS get_scale REDEFINITION.
  PROTECTED SECTION.
    METHODS derive_grade REDEFINITION.
    METHODS threshold    REDEFINITION.
ENDCLASS.
```

若业务上确实需要"重写 `calculate` 追加逻辑"，则必须回写结果并只调钩子：

```abap
METHOD calculate.
  super->calculate(
    IMPORTING it_scores    = it_scores
    RECEIVING rs_result    = DATA(ls_result)
    EXCEPTIONS cx_grade_error = 1 ).
  IF sy-subrc = 1.
    RAISING cx_grade_error.
  ENDIF.
  rs_result = ls_result.                    " 关键：回写
  " 需要追加逻辑时也必须用比率，不是分数：
  " rs_result-grade = derive_grade( iv_ratio = ls_result-points / mv_max_points ).
  " passed 交给 threshold，不要在这里重写
ENDMETHOD.
```

### 7.5 精度对齐（P1-1）

统一比率的精度定义，避免 `p` 默认 2 位带来的抖动：在 `ratio_of` 的 `RETURNING` 与所有 `iv_ratio` 形参上统一写 `TYPE p DECIMALS 4`，并让 `mv_max_points` 明确 `DECIMALS 2`。同时对 `lv_sum` 的累加做溢出保护（或改用 `p LENGTH 15 DECIMALS 4`）。

### 7.6 `validate` 修正（P1-2 / P1-3）

```abap
METHOD validate.
  DATA lv_bad TYPE i.

  LOOP AT it_scores INTO DATA(lv_score).
    IF lv_score IS INITIAL OR lv_score > mv_max_points.
      lv_bad = lv_bad + 1.
    ENDIF.
  ENDLOOP.

  IF lv_bad > 0.
    mv_errors = mv_errors + lv_bad.
    RAISE EXCEPTION TYPE cx_grade_error
      iv_text = |成绩越界，共 { lv_bad } 条非法|.
  ENDIF.
ENDMETHOD.
```

（`lv_bad` 用局部变量统计，`mv_errors` 只做累计/观测，避免实例状态直接决定控制流。）

### 7.7 座位号长度（P0-4）

```abap
rv_seat = |SEAT{ lv_next ALPHA = IN }|.     " 或缩短为 RIGHT-pad / 调整返回字段长度
```
更稳妥的做法是把返回类型从 `char10` 改成 `char20`，或用 `|SEAT{ lv_next }|`（不做补零）配合调用方补位。

### 7.8 锁语义必须区分"未锁"与"锁失败"（P1-6）

```abap
METHOD lock_enrolment.
  CALL FUNCTION 'ENQUEUE_ZGRADE_ENROL'
    EXPORTING  iv_student = iv_student
    IMPORTING ev_locked  = DATA(lv_locked)
    EXCEPTIONS conflict_lock = 1
               OTHERS         = 2.
  CASE sy-subrc.
    WHEN 0.
      rv_locked = lv_locked.
    WHEN OTHERS.
      RAISE EXCEPTION TYPE cx_grade_error
        iv_text = |选座加锁失败，sy-subrc = { sy-subrc }|.
  ENDCASE.
ENDMETHOD.
```
并补一个配套的 `unlock_enrolment`（`DEQUEUE_ZGRADE_ENROL`），在异常路径上确保释放。

### 7.9 金额与币种（P1-7）

```abap
lv_amount = is_result-points * is_fee-netpr.
rs_bill-netwr = ROUND( lv_amount, waers-decimals ).   " 按币种小数位显式舍入
rs_bill-waers = is_fee-waers.                        " 与 netpr 保持同一口径
```
若业务确实要出本地货币金额，必须显式做 `netpr → waerk` 换算并注明汇率来源，不要靠覆盖币种字段"顺便"实现。

---

## 8. 建议补齐的验证

由于全文没有客户端代码，多态从未被执行，建议至少补上：

1. **单元测试（建议 `zcl_grade_test`）**：以 `REF TO zcl_grade_abc` 声明变量，分别装入 `zcl_grade_strict` 与 `zcl_grade_lenient`，对**同一组分数**（0.60 / 0.65 / 0.69 / 0.70 / 0.75 / 0.89 / 0.90 / 0.95 / 1.00，以及含 0 分、空表、负分、超满分）断言 `grade` 与 `passed`——这一步能一次性暴露 P0-3 / P1-1 / P1-2。
2. **断言而不是靠肉眼看输出**：`points`、`passed`、`grade` 三者必须自洽（`passed = abap_true` 时不应出现 `'F'`；`grade` 的刻度必须与 `get_scale` 返回值匹配）。
3. **边界用例**：`iv_max_points` 传 0 / 不传 / 传 1000000；`it_scores` 行数超过 100；`NUMBER_GET` 号段为空。
4. **并发用例**：两个会话同时对同一 `iv_student` 调 `lock_enrolment` + `reserve_seat`，验证不会产生相同座位号、且锁失败时能明确抛错。

---

## 9. 总结

这套代码展示的是标准的**模板方法（Template Method）+ 重定义点**多态范式，结构选型正确：abc 定义骨架，strict / lenient 只填 `derive_grade` 和 `threshold` 两个钩子，`FINAL` 防止子类再被扩展。问题几乎全部出在**实现细节而非设计意图**上，且集中在 strict 的 `calculate` 重写和共用的一段 `derive_grade`：

* 一处 `PRIVATE` 可见性错误让程序**编译不过**；
* 一处漏写回赋值让**返回值丢字段、账单金额恒为 0**；
* 一处单位混用让**严格评级恒为 `'F'`**；
* 一处字符串溢出让**座位号全部相同**；
* 一类"等值匹配连续比率"的写法让**三个类的评级全都不可信**。

优先级建议：先修 P0-1（否则无法编译）→ P0-2/P0-3（业务数据全错）→ P1-1/P1-5（删除 strict 的 `calculate` 重写，回归纯模板方法，一并解决）→ P1-6（并发安全）→ P2 健壮性。修完 P0-1 后建议立刻补上第 8 节的单元测试——这类缺陷只有在断言固定后才不会再退化。
