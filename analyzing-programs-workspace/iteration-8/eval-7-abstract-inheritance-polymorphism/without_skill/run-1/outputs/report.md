# ZCL_GRADE_CALC 类族分析报告

> 分析对象：`D:\Workspace\Skills\analyzing-programs\evals\zcl_grade_calc.clas.abap`（332 行，CLASS-POOL 单文件内含 5 个全局类）
> 关注点：继承结构、多态分发机制、严格评级（`zcl_grade_strict`）判定逻辑的正确性

---

## 0. 结论速览

继承结构本身是**教科书式的、写法标准的**：抽象基类 + 两个 FINAL 叶子类，用模板方法（`calculate` 调 `derive_grade`）承载多态，设计意图清晰。

问题全部出在**子类把模板方法又覆盖了一遍**。`zcl_grade_strict` 同时重定义了 `calculate`、`derive_grade`、`threshold`，结果：父类算好的正确结果被整段丢弃，`rs_result` 的三个输出字段在**任何输入下都是固定的 `points=0 / grade='F' / passed=abap_false`**。这不是"边界情况不对"，而是严格评级**功能完全失效**。

三处互相独立的缺陷叠加成这个结果，任何一处单独修好都不足以让功能恢复：

| # | 缺陷 | 位置 | 后果 | 级别 |
|---|---|---|---|---|
| P0-1 | `super->calculate` 的结果收进局部变量 `ls_result`，**从未回写** `rs_result` | zcl_grade_calc.clas.abap:162 | `points` 恒为 0，`passed` 恒 false，`grade` 恒 F | 阻断 |
| P0-2 | `derive_grade( iv_ratio = rs_result-points )` 把**分数**传给**比例**参数 | zcl_grade_calc.clas.abap:162 | 单位错配，`CASE WHEN 0.9` 永不命中 | 阻断 |
| P0-3 | `IF sy-subrc = 1. RAISING cx_grade_error.` 中的 `RAISING` 是**异常传播声明**，不是重新抛出 | zcl_grade_calc.clas.abap:158-160 | 校验异常被静默吞掉，用未初始化数据继续算 | 阻断 |
| P1-4 | `CASE iv_ratio. WHEN 0.9. ...` 对**连续量**做**精确相等**分级 | :171-177、:201-205、:263-267 | 只有恰好 0.9/0.8/0.6 才命中，其余全部落到 OTHERS | 高 |
| P1-5 | `passed` 阈值硬编码 `mv_max_points * 0.7`，`threshold` 的重定义成为死代码 | :163、:181-184 | 阈值两处维护，必然漂移 | 高 |
| P1-6 | `validate` 只查 `IS INITIAL`，缺上界/负值校验；`TYPE p` 默认仅 1 位小数 | :233、:76-79 | 分数 > 满分可通过（示例见 §4.4）；ratio > 9.99 触发运行时溢出而非 `cx_grade_error` | 高 |
| P1-7 | 校验错误计数存在**对象属性** `mv_errors` 上，只在构造函数重置 | :59、:220-223、:231-241 | 一次 CATCH 之后该对象**永久中毒**，重试必抛异常 | 高 |
| P1-8 | `\|SEAT{ lv_next ALPHA = OUT }|` 拼出的串超过 `char10` 被截断 | :288-312 | 任何小于 10^6 的号码都得到 `SEAT000000`，座位号冲突 | 高 |
| P1-9 | `ENQUEUE_ZGRADE_ENROL` 声明了 `IMPORTING ev_locked`，异常不判 `sy-subrc`，无对应 DEQUEUE | :315-330 | 疑似签名错误；锁泄漏、调用方无法区分冲突 | 高 |
| P2-10 | `calculate_fee` 二次给 `waers` 赋值、不校验 `passed`、不携带 `points`、声明 `RAISING` 却不抛 | :271-285 | 不及格也能开票；事务币种/记账币种语义被覆盖 | 中 |
| P2-11 | `get_scale` 硬编码 `'A+ A F'`，只描述 strict，base 与 lenient 完全不匹配 | :226-228 | 调用方无法依赖该契约 | 中 |
| P2-12 | `TYPE STANDARD TABLE OF p` 匿名内表当形参；`get_scale` 返回 `string` 而非值范围；`netwr`/`waers` 混入成绩结构 | :39、:53-54、:21-22 | 可维护性/类型安全/命名空间隐患 | 中 |
| P2-13 | 异常类命名 `CX_GRADE_ERROR`（客户对象须 Z/Y 开头）；三处 `RAISE` 都不传文本；基类异常构造丢弃 `iv_text` | :82、:213、:239、:250、:310 | 激活期命名空间报错风险；线上排障拿不到任何信息 | 中 |
| P2-14 | 三层 constructor 全是纯透传 | :104-106、:146-148 | 无意义 indirections | 低 |
| P2-15 | 上帝基类 + CLASS-POOL 单一继承树 | :89、:131、:189 | ISP 违反，无法组合"严格+另一种维度" | 低（设计债） |
| P2-16 | `IF lv_score IS INITIAL OR lv_score IS INITIAL.` 条件重复 | :233 | 强烈暗示原意包含上界判断，写漏了 | 低 |

---

## 1. 继承结构

### 1.1 层次树

```
ZCL_GRADE_CALC  (CLASS-POOL 根类, ABSTRACT, CREATE PUBLIC)
│   无父类 —— 同时充当"全局服务类"与"抽象根"
│
├── CX_GRADE_ERROR   ← 独立异常类，INHERITING FROM cx_static_check（不参与下面的树）
│
├── ZCL_GRADE_ABC        INHERITING FROM zcl_grade_calc   ABSTRACT
│   │  重定义: constructor, calculate
│   │  新增 protected: threshold
│   │
│   ├── ZCL_GRADE_STRICT   INHERITING FROM zcl_grade_abc   FINAL
│   │   重定义: constructor, calculate, derive_grade, threshold
│   │
│   └── ZCL_GRADE_LENIENT  INHERITING FROM zcl_grade_abc   FINAL
│       重定义: derive_grade（且由 protected 提升为 public）
```

可实例化的类只有 `ZCL_GRADE_STRICT` 与 `ZCL_GRADE_LENIENT` 两个（基类 ABSTRACT + 叶子 FINAL）。

### 1.2 成员归属与可见性

| 成员 | zcl_grade_calc | zcl_grade_abc | zcl_grade_strict | zcl_grade_lenient |
|---|---|---|---|---|
| `constructor` | PUBLIC / 实现（COALESCE→100） | PUBLIC / 重定义，纯透传 | PUBLIC / 重定义，纯透传 | 继承 ABC 的透传版本 |
| `calculate` | PUBLIC / **未实现（抽象方法）** | PUBLIC / 重定义并实现 | PUBLIC / 重定义并实现 | 继承 ABC 的实现 |
| `derive_grade` | protected / 实现 B/C | 继承 | **protected** / 重定义 A+/A/F | **public** / 重定义 C/D |
| `threshold` | — | protected / 实现 0.5 | protected / 重定义 0.7 | 继承 ABC 的 0.5 |
| `validate` | protected / 实现 | 继承 | 继承 | 继承 |
| `ratio_of` | **private** / 实现 | 继承（私有成员不可被子类调用，故只能由基类方法内部使用） | 继承 | 继承 |
| `lock_enrolment` | protected / 实现 | 继承 | 继承 | 继承 |
| `calculate_fee` | PUBLIC / 实现 | 继承 | 继承 | 继承 |
| `reserve_seat` | PUBLIC / 实现 | 继承 | 继承 | 继承 |
| `get_scale` | PUBLIC / 实现 | 继承 | 继承 | 继承 |

三点值得注意：

1. **`zcl_grade_calc` 标了 ABSTRACT，但它只缺 `calculate` 一个实现**（其余 8 个方法全部实现）。也就是说 `ZCL_GRADE_ABC` 完全可以是具体类——它的 `calculate` 已经实现了。抽象标记在此处是多余的，除非意图是预留更多抽象钩子。
2. **`lenient` 把 `derive_grade` 从 protected 提升到 public**，而 `strict` 保持 protected。ABAP 允许重定义时放宽可见性（protected → public 合法，反向不合法），但两个兄弟类对同一钩子的暴露面不一致，调用方可以对 lenient 绕过 `validate`/`ratio_of` 直接调 `derive_grade`。
3. **`ratio_of` 是 private**，所以只有 `zcl_grade_calc` 自己的方法能调它。这限制了子类扩展计算方式，但也意味着 `calculate` 必须留在基类——这恰好和 §2.2 里 strict 的做法直接冲突。

### 1.3 上帝基类问题

`zcl_grade_calc` 同时承担四类职责：成绩计算模板（`calculate`/`validate`/`ratio_of`/`derive_grade`）、比例尺契约（`get_scale`）、计费（`calculate_fee`）、资源分配（`reserve_seat`）。后果：

- 两个"评分策略"类被迫继承"开票"和"抢座位"的行为，谁都不需要。
- ABAP 单继承 + FINAL 叶子 ⇒ 无法表达"严格且按学时加权"这类组合需求。组合能力只能靠接口提供，而这里一个接口都没有。

---

## 2. 多态是怎么生效的

### 2.1 三种绑定，混用是本类的主要陷阱来源

| 调用形式 | 绑定时机 | 本文件中的位置 |
|---|---|---|
| 隐式同名调用 `derive_grade( ... )` | **动态（晚）绑定**：按 `me` 的实际动态类型在运行时解析 | `zcl_grade_calc->calculate` :117、:118；`zcl_grade_strict->calculate` :162 |
| `super->method( ... )` | **静态（早）绑定**：编译期锁定为父类版本，无论实例真实类型 | :105、:147、:153、:182、:213 |
| 通过引用调用 `ref->calculate( ... )` | 动态绑定到引用的实际类型 | 外部调用方（构造函数同理） |

`threshold` 的调用点 :118 尤其关键：`lv_ratio >= threshold( iv_ratio = lv_ratio )` —— 这里 `threshold` **没有** `super->` 前缀，因此在 strict 实例上会走 `zcl_grade_strict->threshold`（0.7），在 lenient 实例上走 ABC 的 0.5。这就是模板方法模式的正确形态。

### 2.2 一个正常的多态分发路径

```abap
DATA lo_strict  TYPE REF TO zcl_grade_strict.
DATA lo_lenient TYPE REF TO zcl_grade_lenient.

lo_strict  = NEW #( iv_max_points = 100 ).
lo_lenient = NEW #( iv_max_points = 100 ).
```

构造时：`NEW #` 触发的是**动态类型**的构造函数。lenient 未重定义 constructor ⇒ 走 `zcl_grade_abc->constructor`（:146-148 是 strict 自己的，lenient 用的是 ABC 的 :104-106）⇒ `super->constructor` ⇒ `zcl_grade_calc->constructor` 真正写入 `mv_max_points`。

调用 `lo_strict->calculate( ... )` 时的分派链：

```
[动态] zcl_grade_strict->calculate                    :151
   └─ [静态] super->calculate  → zcl_grade_abc->calculate   :109
        ├─ [静态] validate( )      → zcl_grade_calc->validate      :231
        ├─ [静态] ratio_of( )      → zcl_grade_calc->ratio_of      :244
        ├─ 写入 ls_result-points / grade / passed
        │    └─ derive_grade( iv_ratio = lv_ratio )
        │         └─ [动态] zcl_grade_strict->derive_grade    :169  ← 严格评级在此生效
        │    └─ threshold( iv_ratio = lv_ratio )
        │         └─ [动态] zcl_grade_strict->threshold       :181  ← 0.7 在此生效
        └─ RETURNING rs_result → 局部变量 ls_result           :155
   └─ sy-subrc 检查                                             :158
   └─ 用 rs_result（仍是初始值）重算 grade / passed         :162-164
```

**关键认知：`super->` 是静态的。** `zcl_grade_abc->calculate` 内部那次动态分发的正确结果（它确实拿到了 strict 的评级与 0.7 阈值）被 strict 的 `calculate` 覆盖层直接丢弃——静态调用保证了父类逻辑"一定跑"，却完全无法阻止子类"跑完再扔掉"。

### 2.3 多态契约缺失

`get_scale` 被三个类共享，但只有一个常量实现（见 P2-11）。调用方无法通过多态获得与实际等级匹配的刻度；同时 `threshold`（passing 线）是 protected，外部**无法**查询某个实例的及格线。多态接口只描述了"怎么算"，没有描述"结果长什么样"。

---

## 3. 严格评级的判定逻辑：逐步追踪

### 3.1 缺陷 P0-1：`rs_result` 从未被写入

```abap
METHOD calculate.

  super->calculate(
    IMPORTING it_scores    = it_scores
    RECEIVING rs_result    = DATA(ls_result)      " ← 父类结果进了局部变量
    EXCEPTIONS cx_grade_error = 1 ).

  IF sy-subrc = 1.
    RAISING cx_grade_error.                        " ← P0-3：这是声明，不是抛出
  ENDIF.

  rs_result-grade  = derive_grade( iv_ratio = rs_result-points ).   " ← 读的是本方法的 RETURNING 参数
  rs_result-passed = COND #( WHEN rs_result-points >= mv_max_points * 0.7 ... ).
```

`rs_result` 是本方法自己的 `RETURNING VALUE` 形参，进入方法时为初始值（结构体各分量均为初始）。父类结果进了 `ls_result`，此后代码再没碰过 `ls_result`。因此 `rs_result-points` **恒为 0**。

正确写法应是先整体搬运再局部覆盖：

```abap
  rs_result = ls_result.                            " ← 缺失的这一行
```

### 3.2 缺陷 P0-2：单位错配

即使补上上一行，这里仍然错。`derive_grade` 的形参是 `iv_ratio TYPE p`，语义是 **0~1 的比例**：

```abap
METHODS derive_grade
  IMPORTING iv_ratio TYPE p
  RETURNING VALUE(rv_grade) TYPE string
  PROTECTED.
```

而严格实现里的分支常量 `0.9` / `0.8` 也确实是比例。而实参传的是 `points`（满分 100 时取值 0~100）：

```abap
      WHEN 0.9.
        rv_grade = 'A+'.
```

`points = 90.00` 与 `0.9` 永远不相等 ⇒ 落到 `OTHERS` ⇒ `'F'`。这是一次**隐式的量纲切换**，编译器不会报错，ABAP 强转换让它"看起来能跑"。

对照父类的正确用法（:117）：`derive_grade( iv_ratio = lv_ratio )` —— 传的是 4 位小数的比例。strict 把"比例"错换成了"分数"。

### 3.3 缺陷 P0-3：`RAISING` 不是 `RAISE`

```abap
  IF sy-subrc = 1.
    RAISING cx_grade_error.
  ENDIF.
```

ABAP 方法体末尾的 `RAISING exc1 exc2.` 是**"本方法继续向外传播这些异常"的声明语句**，用于 `EXCEPTIONS` 场景下排除式地继续上抛。它**不抛出任何东西**——紧跟其后的 `ENDMETHOD` 直接结束，异常在此**静默消失**，方法以初始的 `rs_result` 正常返回。

后果链条：`validate` 检出非法分数 → 抛 `cx_grade_error` → strict 捕获后不抛 → 用全零 `rs_result` 继续 → `grade='F'`、`passed=false`、`points=0` 返回给调用方。**非法输入被伪装成了一次"评定为不及格"的正常结果。**

正确做法二选一：

```abap
" 方案 A：直接让父类异常冒泡（最简，本方法已声明 RAISING cx_grade_error）
    super->calculate(
      IMPORTING it_scores = it_scores
      RECEIVING rs_result = DATA(ls_result) ).
```

```abap
" 方案 B：确需加工再抛
    TRY.
        super->calculate( IMPORTING it_scores = it_scores
                          RECEIVING rs_result = DATA(ls_result) ).
      CATCH cx_grade_error.
        RAISE EXCEPTION TYPE cx_grade_error
          MESSAGE |严格评级无法处理成绩集：{ | 异常：{ sy-exception } | }|.
    ENDTRY.
```

另外补一点：即使异常被正确捕获，`sy-subrc` 在 `super->calculate` 正常返回后应为 0；但**依赖 `sy-subrc` 判断父类是否抛异常本身就是脆弱写法**——父类方法体内任何嵌套过程调用都会污染 `sy-subrc`。这也是 P0-3 容易被"测不出来"的原因。

### 3.4 修复顺序（关键）

这三个缺陷是**串联**的，不是并联的：

| 修复到哪一步 | 输入 {85, 95}，满分 100 的实际结果 |
|---|---|
| 现状 | `points=0, grade='F', passed=false` |
| 只修 P0-1（回写 `rs_result`） | `points=90.00, grade='F', passed=false` ← 仍错（P0-2） |
| 只修 P0-2（传 `ls_result-points`→比例） | 读 `rs_result-points`=0 ⇒ 仍是 `'F'`、false ← 仍错（P0-1） |
| 只修 P0-3 | 合法输入下无变化（仍恒为 F/false）；非法输入不再被吞 ⇒ **这是唯一能立刻产生可观测差异的修复** |
| P0-1 + P0-2 + P0-3 全修 | `points=90.00, grade='F', passed=false` ← **仍错**（P1-4 相等比较） |
| 再加 P1-4（改为区间比较） | `points=90.00, grade='A+', passed=true` ✅ |

结论：**修完三个 P0 严格评级仍然是坏的**。真正的根因是 P1-4 与"子类重写 `calculate`"这个设计选择（见 §6）。

---

## 4. 其余评级逻辑问题

### 4.1 `CASE` 精确相等 vs 连续量（P1-4）

三处 `derive_grade` 全部用 `CASE` 匹配单个标量常量，而入参是**除法得到的连续实数**：

```abap
  CASE iv_ratio.
    WHEN 0.9.
      rv_grade = 'A+'.
    WHEN 0.8.
      rv_grade = 'A'.
    WHEN OTHERS.
      rv_grade = 'F'.
  ENDCASE.
```

`CASE` 只支持等值比较，没有区间语义。任何非恰好落点的分数都会被判成 OTHERS：

| 比例 | strict | lenient | base |
|---|---|---|---|
| 0.60 | F | **C** | C |
| 0.80 | A | D | **B** |
| 0.85 | F | D | C |
| 0.90 | **A+** | D | C |
| 1.00 | F | D | C |

顺带暴露另外两个事实：**base 把 100% 判成 'C'**；**lenient 把 90% 判成 'D'**——"宽松"体现在 `passed` 用 0.5 门槛，但等级刻度反而把高分判成 D，比 strict 更具误导性。

正确写法（区间判定，ABAP 的 `CASE` 不支持范围，必须用 `IF` 链或区间表）：

```abap
METHOD zcl_grade_strict->derive_grade.
  IF iv_ratio >= 0.9.
    rv_grade = 'A+'.
  ELSEIF iv_ratio >= 0.8.
    rv_grade = 'A'.
  ELSE.
    rv_grade = 'F'.
  ENDIF.
ENDMETHOD.
```

若希望刻度可配置，改用区间表（`RANGES` 或排序表 + `READ TABLE`），把阈值与字母解耦，也顺手解决 P2-11：

```abap
TYPES: BEGIN OF ty_band,
         lower_bound TYPE p DECIMALS 4,
         grade       TYPE string,
       END OF ty_band.
" 由 derive_grade_using( it_bands ) 统一查表
```

### 4.2 阈值双份维护 + 死代码（P1-5）

```abap
  " ABC::calculate —— 走 threshold()，动态绑定 :118
  rs_result-passed = COND #( WHEN lv_ratio >= threshold( iv_ratio = lv_ratio ) ... )

  " strict::calculate —— 绕过 threshold()，硬编码 :163
  rs_result-passed = COND #( WHEN rs_result-points >= mv_max_points * 0.7 ... )

  " strict::threshold —— 无人调用的重定义 :181
  METHOD threshold.
    super->threshold( iv_ratio = iv_ratio ).    " rv_value 先被置 0.5，再被 0.7 覆盖，纯副作用式浪费
    rv_value = 0.7.
  ENDMETHOD.
```

`zcl_grade_strict->threshold` 的重定义因为 strict 覆盖了 `calculate` 而**完全不可达**（唯一调用点是 ABC 的 `calculate`，而它被 strict 绕过了）。它唯一的作用是让读者误以为"strict 的及格线走的是 0.7"。同一常量 `0.7` 现在存在于两处（:163 与 :183），改一处漏一处就产生行为漂移。

### 4.3 精度与舍入隐患

```abap
  DATA lv_ratio TYPE p DECIMALS 4.                       " 中间量：4 位小数
  lv_ratio  = ratio_of( it_scores );                     " rv_ratio TYPE p —— 只有 1 位小数！
  rs_result-points = lv_ratio * mv_max_points;           " 用 4 位小数
  rs_result-grade  = derive_grade( iv_ratio = lv_ratio ); -- 返回值侧被截断成 1 位小数
```

- `ratio_of` 的 `rv_ratio TYPE p`（:76-79）**未指定 DECIMALS**，ABAP 对内建 `p` 的默认是 **1 位小数**。0.85 在赋值时就被舍成 0.9 或 0.8，恰好会撞上 P1-4 的等值分支，产生"看起来能升级、实则随舍入方向漂移"的随机行为。
- 同一次计算里 `points` 用 4 位小数、`grade` 用 1 位小数，两个输出字段来自不同精度源。
- `iv_max_points TYPE p` 也是 1 位小数，却赋给 `mv_max_points TYPE p DECIMALS 2`（:58），丢一位精度。

建议统一：所有中间量显式 `TYPE p DECIMALS 4`（或更高），形参同步声明，且**不要在中间环节做降精度**。

### 4.4 缺上界校验 + 溢出（P1-6、P2-16）

```abap
METHOD validate.
  LOOP AT it_scores INTO DATA(lv_score).
    IF lv_score IS INITIAL OR lv_score IS INITIAL.      " 两个子句完全相同
      mv_errors = mv_errors + 1.
    ENDIF.
  ENDLOOP.
```

条件重复强烈暗示原意包含上界判断。结合 `ratio_of` 的：

```abap
  rv_ratio = lv_sum / ( lv_count * mv_max_points );
```

可以构造出这样的输入：

```abap
it_scores = VALUE #( ( 500 ) ( 500 ) ).   " 满分 100
```

- `validate` 通过（500 既非 initial 也非 0）
- `ratio_of` = 1000 / 200 = **5.0**（合法，未超 `TYPE p` 范围）
- `points` = **500.00**（是满分的 5 倍）
- ABC：`passed` = `5.0 >= 0.7` ⇒ **true**
- grade：strict `'F'`、lenient `'D'`、base `'C'`

即"得分是满分 5 倍"被判为**及格**。若分数继续放大到 ratio > 9.99，`TYPE p`（8 位 1 位小数）溢出 ⇒ 触发运行时溢出错误，**而不是本方法声明的 `cx_grade_error`**。

补上边界校验（顺带修掉重复条件）：

```abap
METHOD validate.
  DATA lv_bad TYPE i.
  LOOP AT it_scores INTO DATA(lv_score).
    IF lv_score IS INITIAL
       OR lv_score <= 0
       OR lv_score > mv_max_points.
      lv_bad = lv_bad + 1.
    ENDIF.
  ENDLOOP.
  IF lv_bad > 0.
    RAISE EXCEPTION TYPE cx_grade_error
      MESSAGE |成绩表中有 { lv_bad } 项越界（允许区间 0 ~ { mv_max_points }）|.
  ENDIF.
ENDMETHOD.
```

### 4.5 对象状态中毒（P1-7）

```abap
  DATA mv_errors TYPE i.                       " protected 对象属性
  ...
  METHOD constructor.
    mv_errors = 0.                             -- 只在这里重置
  ...
  METHOD validate.
    LOOP ... mv_errors = mv_errors + 1. ...
    IF mv_errors > 0. RAISE EXCEPTION TYPE cx_grade_error. ENDIF.
```

校验失败后 `mv_errors > 0` 成为**粘性状态**。调用方只要写了 `TRY ... CATCH` 然后复用同一个实例重试，后续**每一次** `calculate` 都会在第一步立刻抛异常，对象被永久毒化。

这是把"本次调用的局部统计"放进对象状态造成的典型问题。修法即 §4.4：改用局部计数器，并彻底删除 `mv_errors`（连同它的声明一起删）——错误信息应通过异常文本返回，而不是留在对象里。

### 4.6 其它零碎问题

- **`calculate_fee` 的币种二次赋值**（:277 与 :283）：先 `rs_bill-waers = is_fee-waers.`，五行后又被 `rs_bill-waers = is_fee-waerk.` 覆盖。若这是"以发票币种记账"的意图，那第一次赋值是无用功；若是笔误，则计价与记账币种错配。语义需明确，并考虑拆成 `document_currency` / `transaction_currency` 两个字段。
- **`calculate_fee` 不校验 `is_result-passed`**：`passed = abap_false` 也能照常开票，只是金额为分数×单价。
- **`calculate_fee` 丢弃 `points`**：`rs_bill-points` 从未赋值，账单回执里拿不到分数。
- **`calculate_fee` 声明 `RAISING cx_grade_error` 却一条异常都不抛**：契约骗人。
- **金额溢出**：`lv_amount TYPE cuxy`（15 位 2 位小数）承接 `points(p,2) × netpr(netpr)`，两个 2 位小数相乘需要 4 位小数，`cuxy` 会静默舍入甚至溢出。
- **`get_scale` 返回 `string`**（:53-54、:226-228）：等级刻度应当是值范围/枚举/区间表，而不是自由文本。

---

## 5. 非评级部分的风险

### 5.1 `reserve_seat` 座位号必然重复（P1-8）

```abap
  DATA lv_next TYPE i.
  CALL FUNCTION 'NUMBER_GET'
    EXPORTING nrr = 'ZGRADE' nrobject = 'ZSEAT'
    IMPORTING number = lv_next ...
  ...
  rv_seat = |SEAT{ lv_next ALPHA = OUT }|.
```

`lv_next` 是内建类型 `i`。ABAP 字符串模板对内建类型按其技术长度（`i` 为 10 位）渲染，`ALPHA = OUT` 再把它变成左补零的 10 位数字串。于是表达式先得到 `'SEAT0000000042'`（14 字符），再赋给 `rv_seat TYPE char10` —— 被**从左截断**为 `'SEAT000000'`，真正的流水号被整段丢掉。

即：**任何号码小于 10^6 的调用都会得到同一个座位号 `SEAT000000`**。修法是让长度显式且不溢出：

```abap
  DATA lv_next TYPE numberc(6).
  CALL FUNCTION 'NUMBER_GET'
    EXPORTING nrr = 'ZGRADE' nrobject = 'ZSEAT' nr2 = 'SEAT6'
    IMPORTING number = lv_next ...
  rv_seat = |SEAT{ lv_next }|.          " 恰好 10 字符，不截断
```

顺带：`DO 5 TIMES` 对 `buffer_overflow` 重试是危险的（号码范围溢出通常不会因为重试而恢复），且失败时抛的是**空消息** `cx_grade_error`，没有任何诊断线索。

### 5.2 `lock_enrolment` 三处问题（P1-9）

```abap
  CALL FUNCTION 'ENQUEUE_ZGRADE_ENROL'
    EXPORTING  iv_student = iv_student
    IMPORTING  ev_locked  = lv_locked
    EXCEPTIONS conflict_lock = 1
               OTHERS        = 2.

  rv_locked = lv_locked.                 " sy-subrc 从不检查
```

1. **疑似签名错误**：SAP 命名规范的 `ENQUEUE_*` 函数模块（FM 锁定）**只有 EXCEPTIONS，没有任何 IMPORTING 参数**，锁定结果一律通过异常传递（`conflict_lock` / `sy-subrc`）。这里声明的 `IMPORTING ev_locked` 在标准 FM 上不存在。需确认该 FM 是否为自建；若为自建命名规范，程序激活时即报错。
2. **`sy-subrc` 从不检查**：`conflict_lock` 与 `OTHERS` 被声明但从未判定，调用方拿到的永远是 `abap_false`，**无法区分"没锁上"和"被别人锁着"**，业务上无法给出正确提示。
3. **无对应 DEQUEUE**：方法内加锁后从不释放。调用方若忘记 `DEQUEUE`，将造成跨请求的死锁。
4. 该方法是 protected 且**全类无任何调用点**，属于死代码。

### 5.3 异常类与消息

- `CX_GRADE_ERROR` 出现在客户对象命名空间。SAP 的标准异常族以 `CX_` 开头；客户开发的全局类通常需 `Z`/`Y` 前缀，激活时可能报命名空间错误（程序内异常可用 `zcx_...`）。
- 异常构造函数接收 `iv_text` 却在实现里丢掉：

```abap
  CLASS cx_grade_error IMPLEMENTATION.
    METHOD constructor.
      super->constructor( ).        " iv_text 从未被传给 cx_static_check
    ENDMETHOD.
```

  应为 `super->constructor( text = iv_text )`（`cx_root` 的构造参数名是 `TEXT`），并且所有 `RAISE` 调用点都要传消息。
- 三处 `RAISE EXCEPTION TYPE cx_grade_error.`（:239、:250、:310）全都没有消息文本，线上排障时只能看到一个空的异常。

### 5.4 类型与签名

```abap
  METHODS calculate
    IMPORTING it_scores TYPE STANDARD TABLE OF p WITH EMPTY KEY   " 匿名内表做形参
```

- 匿名内表类型作为形参虽可编译，但**没有名字**，`calculate` 与 `validate` 各写一遍、结构不共享，改一处忘一处必然漂移。应定义具名类型（如 `ty_score_tab`），更好的是引入**带结构的成绩项**（`score` + `weight` + `exam_type`），而不是裸 `p`——当前设计无法表达加权评分。
- `ty_result` 里混入 `netwr` / `waers`（销售与财务数据项）：成绩结果结构应当与金额、币种解耦，后者属于 `calculate_fee` 的账单类型。
- `get_scale` 返回 `string`，见 §4.6。

---

## 6. 根因与设计建议

### 6.1 根因：子类重写了模板方法本身

ABC 的 `calculate` 已经是一个**正确的模板方法**：

```abap
validate( it_scores ).                                  " 固定步骤（静态）
DATA lv_ratio TYPE p DECIMALS 4.
lv_ratio = ratio_of( it_scores ).                       // 固定步骤（静态）
rs_result-points = lv_ratio * mv_max_points.            // 组装结果（静态）
rs_result-grade  = derive_grade( iv_ratio = lv_ratio ). -- 可变钩子（动态）✓
rs_result-passed = COND #( WHEN lv_ratio >= threshold( iv_ratio = lv_ratio ) ... ).  -- 可变钩子（动态）✓
```

子类只需要提供 `derive_grade` 与 `threshold` 两个钩子，多态就会自动生效。strict 额外重写 `calculate`，一次性绕开了两个动态钩子——这正是 P0-1/P0-2/P0-3/P1-5 四个缺陷的共同源头。

**修掉 strict 的 `calculate` 重定义**（连同 `threshold` 重定义一起删掉，保留 `derive_grade`），问题 1、2、3、5 四个缺陷同时消失。strict 类将退化为：

```abap
CLASS zcl_grade_strict DEFINITION PUBLIC INHERITING FROM zcl_grade_abc FINAL CREATE PUBLIC.
  PROTECTED SECTION.
    METHODS derive_grade REDEFINITION.
    METHODS threshold    REDEFINITION.      " 由父类 calculate 动态调用，复活为活代码
ENDCLASS.
```

### 6.2 让 `passed` 只由一个来源决定

把"及格判定"和"等级判定"解耦，各自只有一个可覆写点：

```abap
" 基类：唯一计算入口，不再被任何子类覆盖
METHOD calculate.
  validate( it_scores ).
  DATA lv_ratio TYPE p DECIMALS 4.
  lv_ratio = ratio_of( it_scores ).
  rs_result-ratio   = lv_ratio.                     " ← 把比例放进结果结构
  rs_result-points  = lv_ratio * mv_max_points.
  rs_result-grade   = derive_grade( iv_ratio = lv_ratio ).
  rs_result-passed  = COND #( WHEN lv_ratio >= passing_ratio( )     " ← 钩子，无入参
                               THEN abap_true ELSE abap_false ).
ENDMETHOD.

" 钩子 1：等级刻度（区间比较）
METHOD zcl_grade_strict->derive_grade.
  IF iv_ratio >= 0.9.     rv_grade = 'A+'.
  ELSEIF iv_ratio >= 0.8. rv_grade = 'A'.
  ELSE.                   rv_grade = 'F'.
  ENDIF.
ENDMETHOD.

" 钩子 2：及格线
METHOD zcl_grade_strict->passing_ratio.
  rv_ratio = 0.7.
ENDMETHOD.
```

`threshold` 现有的 `iv_ratio` 入参在三个实现里都没被用到——删掉它，或让钩子无入参，避免"形参存在但语义为空"的误导。

### 6.3 结果结构应显式承载比例与刻度

```abap
TYPES: BEGIN OF ty_result,
         ratio      TYPE p DECIMALS 4,   " 0~1，避免下游再猜量纲
         points     TYPE p DECIMALS 2,
         grade      TYPE string,
         scale      TYPE ty_scale,       -- 值范围，而非 string
         pass_mark  TYPE p DECIMALS 4,   -- 本次实际使用的及格线，事后可审计
         passed     TYPE abap_bool,
       END OF ty_result.
```

`pass_mark` 让"为什么判为及格"成为结果的一部分，代替了当前"阈值藏在两个常量里、调用方查不到"的状态。`ratio` 则从类型上就杜绝了 P0-2 那类量纲混用。

### 6.4 用接口组合替代上帝基类

```abap
INTERFACE zif_grade_calculator.
  METHODS calculate
    IMPORTING it_scores TYPE ty_score_tab
    RETURNING VALUE(rs_result) TYPE ty_result
    RAISING   cx_grade_error.
ENDINTERFACE.

INTERFACE zif_fee_calculator.
  METHODS calculate_fee
    IMPORTING is_result TYPE ty_result is_fee TYPE ty_fee
    RETURNING VALUE(rs_bill) TYPE ty_bill
    RAISING   cx_grade_error.
ENDINTERFACE.
```

评分策略类用 **local class + 接口实现**（无状态，无需继承），开票与座位分配拆成独立类。这样"严格评级"和"加权评分"可以自由组合，不再受单继承树限制；ABC 也不必被拖进开票和抢座号的职责。同时把 `CLASS-POOL` 换成普通 include 顺序的全局类，减少全局命名空间占用。

### 6.5 修完之后的完整对照

| 项 | 改动 | 解决的问题 |
|---|---|---|
| 删除 `strict->calculate` 重定义 | 恢复模板方法 | P0-1、P0-2、P0-3、P1-5 |
| `derive_grade` 改区间比较 | `IF/ELEsIF` 或区间表 | P1-4 |
| `passed` 只经 `passing_ratio( )` 钩子 | 单一事实来源 | P1-5 |
| `validate` 加 0/负数/超上限校验，局部计数 | 修上界 | P1-6、P2-16 |
| `ratio_of` 与所有 `p` 显式 `DECIMALS 4` | 消除舍入抖动 | §4.3 |
| 删除 `mv_errors`，异常携带文本 | 消除对象中毒与静默 | P1-7、P2-13 |
| `RAISING` → `RAISE` / 直接冒泡 | 异常不再被吞 | P0-3 |
| `reserve_seat` 显式 `nr2` + `numberc(6)` | 不再截断 | P1-8 |
| `lock_enrolment` 判 `sy-subrc` + 提供解锁路径 | 锁状态可判定、可释放 | P1-9 |
| `calculate_fee` 校验 `passed`、明确币种语义、实际抛异常 | 计费契约自洽 | P2-10 |
| `get_scale` 改为按实例覆写 / 返回刻度表 | 多态契约完整 | P2-11 |
| 具名内表类型 + 结构化成绩项 | 去掉匿名类型重复 | P2-12 |
| 接口化 + 取消 CLASS-POOL | 消除上帝基类 | P2-15 |

---

## 7. 回归测试建议

这类"结构正确但静默算错"的缺陷，**单元测试比代码走查有效得多**。建议至少覆盖：

```abap
CLASS ltc_grade_test DEFINITION FINAL FOR TESTING DURATION SHORT RISK LEVEL HARMLESS.
  PRIVATE SECTION.
    METHODS strict_normalizes_result FOR TESTING RAISING cx_static_check.
    METHODS strict_grade_uses_ratio  FOR TESTING RAISING cx_static_check.
    METHODS lenient_scale_is_sane    FOR TESTING RAISING cx_static_check.
    METHODS invalid_input_raises     FOR TESTING RAISING cx_static_check.
    METHODS score_above_max_raises   FOR TESTING RAISING cx_static_check.
    METHODS object_survives_failure  FOR TESTING RAISING cx_static_check.
ENDCLASS.

CLASS ltc_grade_test IMPLEMENTATION.
  METHOD strict_normalizes_result.
    DATA(lo) = NEW zcl_grade_strict( iv_max_points = 100 ).
    DATA(ls) = lo->calculate( it_scores = VALUE #( ( 85 ) ( 95 ) ) ).

    " 现状下这三条断言会同时失败（0 / 'F' / false）：
    cl_abap_unit_assert=>assert_equals( act = ls-points exp = 90.00 ).
    cl_abap_unit_assert=>assert_equals( act = ls-grade  exp = 'A+'  ).
    cl_abap_unit_assert=>assert_equals( act = ls-passed exp = abap_true ).
  ENDMETHOD.

  METHOD strict_grade_uses_ratio.
    " 满分 100 与满分 1000 必须给出同一个等级 —— 抓住量纲错配
    DATA(ls100)  = NEW zcl_grade_strict( iv_max_points = 100 )
                   ->calculate( it_scores = VALUE #( ( 90 ) ) ).
    DATA(ls1000) = NEW zcl_grade_strict( iv_max_points = 1000 )
                   ->calculate( it_scores = VALUE #( ( 900 ) ) ).
    cl_abap_unit_assert=>assert_equals( act = ls100-grade  exp = ls1000-grade ).
  ENDMETHOD.

  METHOD lenient_scale_is_sane.
    " 抓相等比较：0.85 既不等于 0.6 也不等于 0.9
    DATA(ls) = NEW zcl_grade_lenient( iv_max_points = 100 )
               ->calculate( it_scores = VALUE #( ( 85 ) ) ).
    cl_abap_unit_assert=>assert_equals( act = ls-grade exp = 'B' ).   " 期望刻度按约定调整
    cl_abap_unit_assert=>assert_equals( act = ls-passed exp = abap_true ).
  ENDMETHOD.

  METHOD invalid_input_raises.
    DATA(lo) = NEW zcl_grade_strict( iv_max_points = 100 ).
    " 现状不抛异常（被 RAISING 静默吞掉），修复后必须抛
    DATA lv_x TYPE i.
    TRY.
        lo->calculate( it_scores = VALUE #( ( 0 ) ) ).
      CATCH cx_grade_error.
        lv_x = 1.
    ENDTRY.
    cl_abap_unit_assert=>assert_equals( act = lv_x exp = 1 ).
  ENDMETHOD.

  METHOD score_above_max_raises.
    DATA(lo) = NEW zcl_grade_strict( iv_max_points = 100 ).
    DATA lv_x TYPE i.
    TRY.
        lo->calculate( it_scores = VALUE #( ( 500 ) ) ).   " 现状：ratio 5.0 → passed = true
      CATCH cx_grade_error.
        lv_x = 1.
    ENDTRY.
    cl_abap_unit_assert=>assert_equals( act = lv_x exp = 1 ).
  ENDMETHOD.

  METHOD object_survives_failure.
    DATA(lo) = NEW zcl_grade_strict( iv_max_points = 100 ).
    TRY.
        lo->calculate( it_scores = VALUE #( ( 0 ) ) ).
      CATCH cx_grade_error.
    ENDTRY.
    " 修复前：第二次调用仍抛异常（mv_errors 残留）→ 这条失败
    DATA(ls) = lo->calculate( it_scores = VALUE #( ( 85 ) ) ).
    cl_abap_unit_assert=>assert_equals( act = ls-grade exp = 'A+' ).
  ENDMETHOD.
ENDCLASS.
```

`strict_grade_uses_ratio` 值得单独强调：它是唯一能同时防住"单位错配"和"满分不可配置"两类回归的断言——用两组不同 `max_points` 得到同一等级，比逐个固定期望值更抗重构。

---

## 8. 待确认事项

以下无法从源码判定，需要向开发者核实：

1. `ENQUEUE_ZGRADE_ENROL` 是否真实存在于函数组？标准 FM 锁定没有 `IMPORTING` 参数，若为自建命名规范，程序当前无法激活。
2. `ZGRADE` 号码范围对象是否已创建、长度多少？直接决定 §5.1 的截断问题是否已在线上产生脏数据。
3. `get_scale` 返回的 `'A+ A F'` 究竟是刻度声明还是占位符？若是占位符，需要为 base / lenient 补齐各自的覆写。
4. `calculate_fee` 中 `waers`（结果币种）先赋 `is_fee-waers` 后被 `is_fee-waerk` 覆盖，是刻意的"记账币种优先"还是笔误？
5. `threshold` 的 `iv_ratio` 入参在全部三个实现中均未被使用——是预留参数还是冗余签名？
6. `zcl_grade_calc` 同时是 `CLASS-POOL` 全局类与抽象父类，是否有下游代码依赖它作为可实例化的工具类？（若有，会因 `ABSTRACT` 而在激活期报错。）
7. `cx_grade_error` 的命名空间是否已在 TR 中登记？`CX_` 前缀在客户系统通常需要审批或改名。
8. 是否已有单元测试？没有的话，本文第 7 节可作为起点直接落地。