# ABAP 现代语法分析报告 — `ZMODERN_LO`

> 分析对象：`evals/zmodern_lo.abap`（97 行，报表程序 + 3 个 FORM）
> 关注重点：内联声明的作用域、`VALUE #(` 的映射语义、表表达式 / `FILTER` / `REDUCE` 的行为边界
> 结论一句话：**这份程序当前无法通过语法检查**——不是"用得不好"，而是"编译不过"。除此之外还有 3 处会造成数据错误的字段语义问题，和若干现代语法的语义陷阱。

---

## 0. 结论速览（按严重度）

| # | 级别 | 位置 | 问题 | 后果 |
|---|------|------|------|------|
| 1 | 🔴 编译失败 | 73、93 | `lv_total` / `lv_waers` 跨 FORM 引用内联变量 | 语法错误，程序无法激活 |
| 2 | 🔴 编译失败 | 24 | `SELECT-OPTIONS ... FOR gt_stock-matnr` 引用表组件 | 语法错误 |
| 3 | 🔴 字段错误 | 37-41 | `MARD` 不存在 `NTGEW` / `BRGEW`（属 `MARA`） | 语法/运行期 SQL 错误 |
| 4 | 🔴 数据错误 | 61-63 | `REDUCE p(` 隐式 `p LENGTH 8 DECIMALS 0` | 库存数量小数位被静默截断 |
| 5 | 🟠 字段语义 | 37、93 | `MAKTX`（`MAKT` 表）未选取，`WAERS` 被硬编码 `'USD'` | 文本永远为空、币种被伪造 |
| 6 | 🟠 业务逻辑 | 58-59 | `FILTER ... WHERE ntgew > brgew`（净重大于毛重） | 逻辑恒假，结果集为空 |
| 7 | 🟠 单位语义 | 22、81 | `gv_min` 是无单位 packed，与 `QUAN` 直接比较 | 单位不检查，比较结果不可信 |
| 8 | 🟠 稳定性 | 81-83 | `LOOP` 内逐行 `MESSAGE TYPE 'S'` | 行数多时消息缓冲区溢出 dump |
| 9 | 🟡 结构 | 19 | `WITH EMPTY KEY` + 无去重 | 重复行静默保留，后续聚合翻倍 |
| 10 | 🟡 死代码 | 43-46、44 | `lv_rows` / `lv_first` 算出不用；`CONV i(` 冗余 | ATC 告警、`lv_first` 名不副实 |

---

## 1. 程序骨架与执行流程

```abap
REPORT zmodern_lo.

TYPES: BEGIN OF ty_stock, ... END OF ty_stock.        " 本地结构：把 MARA/MARD/MARK 揉在一起
TYPES ty_stock_tab TYPE STANDARD TABLE OF ty_stock WITH EMPTY KEY.
DATA gt_stock TYPE ty_stock_tab.                      " 全局结果表
DATA gv_min   TYPE p DECIMALS 2.                      " 最小库存阈值（无单位！）
SELECT-OPTIONS s_matnr FOR gt_stock-matnr.            " ① 见问题 2

START-OF-SELECTION.
  DATA(lv_waers) = 'USD'.                             " ② 事件块内联变量，作用域 = 本事件块
  PERFORM read_stock.                                 "    选数
  PERFORM filter_and_aggregate.                       "    过滤 + 聚合（lv_total 在此诞生）
  PERFORM report_output.                              "    输出（却要用上面两个变量）

FORM read_stock.
  SELECT matnr werks lgort mstock ntgew brgew
    FROM mard INTO TABLE @gt_stock                    " ③ @ 内联转义正确，但字段来自错表
    WHERE matnr IN @s_matnr AND werks = 'A100'.
  DATA(lv_rows)  = lines( gt_stock ).                 " ④ 死代码
  DATA(lv_first) = CONV i( REDUCE i( INIT m = 0 ... ) ).  " ④ 死代码 + 冗余 CONV
ENDFORM.

FORM filter_and_aggregate.
  DATA(lv_missing) = REDUCE i( ... IS INITIAL ... ).  " 空库位计数（在过滤前算）
  gt_stock = FILTER ty_stock_tab( gt_stock WHERE ntgew > brgew ).   " ⑤ 过滤条件恒假
  DATA(lv_total) = REDUCE p( ... sum + row-mstock ).  " ⑥ 内联变量，作用域 = 本 FORM
ENDFORM.

FORM report_output.
  DATA(lv_header) = |... { lv_total W = 12 }|.       " ⑦ 跨 FORM 引用 → 编译失败
  LOOP AT gt_stock INTO DATA(ls_row).                 " 内联变量，作用域 = 本 FORM
    IF ls_row-mstock > 0 AND ls_row-mstock <> gv_min.
      MESSAGE ... TYPE 'S'.                            " ⑧ 循环内发消息
    ENDIF.
  ENDLOOP.
  DATA(lt_good) = VALUE ty_stock_tab(                 " ⑨ 重建结构，丢字段
    FOR row IN gt_stock WHERE ( mstock > 0 )
    ( matnr = row-matnr  maktx = row-maktx
      mstock = row-mstock  waers = lv_waers ) ).      " ⑩ 跨 FORM 引用 → 编译失败
ENDFORM.
```

数据流：`MARD`(+应为 `MARA`) → `gt_stock` → `FILTER` 就地替换 → `REDUCE` 聚合 → `WRITE` / 字符串模板 / `VALUE` 重建。

设计上最大的结构性问题是：**`START-OF-SELECTION` 里的内联变量 + FORM 传参缺失**，导致跨过程数据只能靠隐式全局量传递，而作者又误以为内联变量像全局量一样可见。

---

## 2. 核心专题一：内联声明的作用域

### 2.1 规则

`DATA(x) = ...` 声明的变量，作用域是**所在的最内层过程上下文**，即：

- 类方法 → 方法结束
- `FORM` → `ENDFORM`
- 报表事件块（`START-OF-SELECTION` 等）→ 事件块结束
- `FOR` / 表推导式 → 单条语句（`row`）
- `LOOP AT ... INTO DATA(x)` → 所属 FORM/方法，**不是循环体**

关键点：**FORM 之间是平级的兄弟作用域，不是嵌套关系。** FORM 里看不到调用方事件块的变量，这和"调用方是活动上下文"毫无关系——FORM 不是闭包，不存在词法捕获。这是最常见的现代语法误用。

### 2.2 本程序的两处硬错误

```abap
START-OF-SELECTION.
  DATA(lv_waers) = 'USD'.        " 作用域 = START-OF-SELECTION 块

FORM report_output.
  ... waers = lv_waers ) ).      " ← 作用域外，编译器报 "lv_waers 未声明"
ENDFORM.
```

`lv_total` 同理：它在 `FORM filter_and_aggregate` 里诞生，却在 `FORM report_output` 里被用（73 行）。

这两处是**语法错误（syntax error）**，不是运行期 dump——程序根本激活不了。修复只能二选一：

```abap
" 方案 A：提升为全局（简单，适合 report）
DATA gv_waers TYPE c LENGTH 3 VALUE 'USD'.

" 方案 B：内联声明 + 显式参数传递（推荐，见 §6.1）
PERFORM report_output USING lv_total.
FORM report_output USING iv_total TYPE p.
```

### 2.3 `LOOP AT ... INTO DATA(ls_row)` 的作用域陷阱

```abap
LOOP AT gt_stock INTO DATA(ls_row).
ENDLOOP.
" 循环外 ls_row 依然存在，且持有最后一次赋的值
```

这一条本身**不会报错**，但有三个真实坑：

1. **变量在 FORM 全程可见** → 循环后若误用 `ls_row`，拿到的是"最后一行"而不是空值，静默产生错误结果。
2. **空表时它保持初始值** → 不报错，也不代表"未循环"，无法用 `IS INITIAL` 判断是否走过循环。
3. **循环嵌套时名字相同会互相覆盖** → 内外层都用 `DATA(ls_row)` 只会在同一作用域声明一次（第二次是同一声明而非新变量），迭代后外层变量被内层污染。

推荐显式声明 `DATA ls_row TYPE ty_stock.`，让生命周期一眼可见。

### 2.4 作用域速查

| 声明位置 | 可见范围 | 常见误判 |
|---|---|---|
| `START-OF-SELECTION` 内 | 该事件块 | ✗ 以为 FORM 能看见 |
| `FORM` 内 | 该 FORM | ✗ 以为下一个 FORM 能看见 |
| `FORM` 的 `PERFORM ... USING` 形参 | 另算 | ✓ 这是唯一正确跨过程通道 |
| `FOR row IN itab` | 单条语句 | ✗ 在语句外用 `row` |
| `LOOP INTO DATA(x)` | 整个 FORM | ✗ 以为每轮重新初始化 |
| 类方法内 | 该方法 | ✓ 不跨实例、需字段存全局 |

---

## 3. 核心专题二：`VALUE ty_stock_tab( ... )` 的映射语义

这段是全程序里最容易写错、后果最隐蔽的部分：

```abap
DATA(lt_good) = VALUE ty_stock_tab(
  FOR row IN gt_stock
  WHERE ( mstock > 0 )
  ( matnr  = row-matnr
    maktx  = row-maktx
    mstock = row-mstock
    waers  = lv_waers ) ).
```

### 3.1 逐条拆解

**① 执行顺序：`FOR` 取行 → `WHERE` 过滤 → 逐行构造新结构。**
`WHERE ( mstock > 0 )` 里的 `mstock` 裸名**解析为源内表的组件**，不是 `ty_stock` 的，也不需要 `row-` 前缀。这点在 `FILTER` 里同样成立（`WHERE ntgew > brgew`），与普通表达式里的"必须写 `row-mstock`"正好相反，最容易记混。

**② 括号里是"目标结构的命名赋值"，不是"投影"。**
`( matnr = ... maktx = ... )` 是给 `ty_stock` 的每个组件赋值；**没提到的组件（`werks`、`lgort`、`ntgew`、`brgew`）一律保持初始值**。这不是 bug，是 ABAP 语义——但很多人以为它会"带着走"。

因此 `lt_good` 里 `werks` / `lgort` 全空，而 `mard` 的主键恰恰是 `MATNR + WERKS + LGORT`。**下游任何按工厂/库位再分组的逻辑都会把不同库存混作一条。**

> 对比 `FILTER`：`FILTER ty_stock_tab( ... )` 返回的是**原结构的全部字段**，只是行被筛掉；`VALUE #( ... )` 是**重建**。这是二者的本质差异，也是本程序把 `FILTER` 和 `VALUE` 混着用时丢字段的根源。

**③ `WHERE` 之后的行可能"半空"。**
`FOR` 的过滤条件（`mstock > 0`）与结构映射（`waers = lv_waers`）是独立的。硬塞 `'USD'` 意味着所有行的"币种"字段都被覆盖——而 `MARD-MSTOCK` 是 `QUAN`，其单位字段 `MSTOCK`（如 `PC`/`KG`）本程序压根没取。**现在写入的是虚假的币种。**

**④ `FOR` 里的 `row` 是临时变量。**
它只活在这一条语句内，且每次迭代重新绑定。不能把它存起来、不能当 `LOOP` 的游标用、不能传给 PERFORM。

**⑤ `WITH EMPTY KEY` 让构造器不做唯一性检查。**
目标表 `ty_stock_tab` 是 `STANDARD TABLE ... WITH EMPTY KEY`，构造时不去重；同一 `(matnr, werks, lgort)` 若在源表重复，`lt_good` 里就重复两行，后续 `REDUCE` 求和会**按重复次数翻倍**。

**⑥ 命名 vs 位置写法。**
本例用的是命名（`matnr = ...`），顺序可乱、与结构定义顺序无关。若写成位置写法 `( row-matnr row-maktx ... )`，则**顺序必须与 `ty_stock` 定义完全一致**，否则是静默错位赋值（类型相容时甚至不报错）。除非刻意做重排，永远用命名写法。

**⑦ `VALUE ty_stock_tab(` vs `VALUE #(`。**
`DATA(lt_good)` 之后可以写 `VALUE #(`，类型由目标变量 `lt_good` 推导。这里显式写类型名更好——但前提是**目标变量本身类型正确**，否则 `#` 会让错误延后到别处才爆。

### 3.2 修正建议

要么补全映射（并真正选出 `maktx`），要么在结构里把不该搬的字段去掉：

```abap
DATA(lt_good) = VALUE ty_stock_tab(
  FOR row IN gt_stock WHERE ( mstock > 0 )
  ( matnr  = row-matnr
    werks  = row-werks      " 别丢
    lgort  = row-lgort      " 别丢
    mstock = row-mstock ) ).
```

如果"只关心某几个字段"，更清晰的做法是定义一个**专用窄结构** `ty_good`，而不是复用宽结构再漏填——让漏填变成编译期错误。

---

## 4. `REDUCE` / `FILTER` / 表表达式的语义与风险

### 4.1 `REDUCE p(` —— 最隐蔽的数据损坏点

```abap
DATA(lv_total) = REDUCE p( INIT sum = 0
                           FOR row IN gt_stock
                           NEXT sum = sum + row-mstock ).
```

`p` 在这里**不是"任意 packed"**，而是一个**具体类型**：`p` 不带参数时默认 `p LENGTH 8 DECIMALS 0`。

- `MARD-MSTOCK` 是 `QUAN`，带 3 位小数（长度 13,3）。
- 累加过程中每次 `sum + row-mstock` 都会把结果**四舍五入到 0 位小数**——不报错、不 dump，只是数字悄悄变小。
- `lv_total` 随后被 `WRITE`、被 `W = 12` 格式化成整数，一眼看不出问题。

正确写法是把精度显式化：

```abap
DATA(lv_total) = REDUCE mara-matnr( INIT sum = CONV mara-ntgew( 0 )    " 或用 p LENGTH 13 DECIMALS 3
                        FOR row IN gt_stock
                        NEXT sum = sum + row-mstock ).
```

> 经验法则：**`REDUCE` 的类型参数不要图省事写单字母内建类型**。写业务类型（`QUAN` 派生的 `mara-ntgew`、`mard-mstock`）或完整 `p LENGTH n DECIMALS m`，让精度和单位成为类型的一部分。

### 4.2 `REDUCE` 与 `lines()` 重复

```abap
DATA(lv_rows)  = lines( gt_stock ).                                        " 已经有了
DATA(lv_first) = CONV i( REDUCE i( INIT m = 0 FOR row IN gt_stock
                                   NEXT m = m + 1 ) ).                      " 又算一遍
```

三重问题：

1. `lines()` 是内建函数，`REDUCE` 计数纯属重复劳动，全表扫描两遍。
2. `REDUCE i( ... )` 结果已是 `i`，外层 `CONV i(` 是空操作。
3. `lv_first` 命名暗示"第一行"，实际是"行数"，语义误导。这两行都是死代码，建议直接删除。

### 4.3 `COND i( WHEN row-mstock IS INITIAL ... )` 计数

语法正确，`IS INITIAL` 对 `QUAN` 等价于"= 0"。但它统计的是"过滤**前**的空库位行"，而 `lv_total` 统计的是"过滤**后**"的总量，两个数字口径不同却并排 `WRITE` 打印（65 行），容易被读成同一口径的对照指标。建议要么都取过滤前，要么都取过滤后。

### 4.4 `FILTER` 的条件恒假

```abap
gt_stock = FILTER ty_stock_tab( gt_stock WHERE ntgew > brgew ).
```

`NTGEW`（净重）`> BRGEW`（毛重）在业务上不可能成立（毛重 = 净重 + 包装重）。**即使字段取对了，这行也必然把 `gt_stock` 清空**，导致 `lv_total = 0`、`lv_header` 显示 0 行、整个 LOOP 不执行、`lt_good` 为空。

看起来作者想表达的是"只保留有库存的行"或"超出最小值容差"。修改前必须先确认真实业务意图——**这里不是语法问题，是需求缺失**。

另外注意 `gt_stock = FILTER ...` 是**整体重新赋值**，原引用被丢弃。若其它 FORM 已持有 `gt_stock` 的引用或并行任务在读，会看到旧/新数据不一致。

### 4.5 `SELECT-OPTIONS ... FOR gt_stock-matnr`

```abap
DATA gt_stock TYPE ty_stock_tab.
SELECT-OPTIONS s_matnr FOR gt_stock-matnr.   " ✗ 语法错误
```

`FOR` 后面必须是一个**独立的数据对象**（`C`/`D`/`N`/`T`/数值型），不允许是表字段，也不允许是结构组件——否则选屏的输入值就无处安放。

```abap
DATA gv_matnr TYPE mara-matnr.
SELECT-OPTIONS s_matnr FOR gv_matnr.
```

（顺带：`s_matnr` 在 `WHERE matnr IN @s_matnr` 里的用法本身是正确的转义写法 `@`，这一处没问题。）

### 4.6 `FROM mard` 取 `ntgew` / `brgew`

```abap
SELECT matnr werks lgort mstock ntgew brgew FROM mard ...
```

`NTGEW` / `BRGEW` 是 **`MARA`** 的字段，`MARD` 里没有。这要么在编译期报"字段未知"，要么在运行期抛 SQL 错误（取决于版本与检查级别），无论哪种都要改。**跨表取字段必须写 `INNER JOIN`，否则"字段语义"和"数据语义"会一起错位**：

```abap
SELECT m~matnr m~werks m~lgort m~mstock a~ntgew a~brgew
  FROM mard AS m INNER JOIN mara AS a ON a~matnr = m~matnr
  INTO TABLE @gt_stock
  WHERE m~matnr IN @s_matnr
    AND m~werks  = 'A100'.
```

同类问题还有：

- `maktx` 来自 `MAKT`（物料描述），`MARD` 没有，`gt_stock-maktx` **永远为空**；
- `waers` 在选数时**根本没取**，后面却被填成 `'USD'`。

---

## 5. 字段语义、单位与消息风险

### 5.1 `gv_min` 的单位问题

```abap
DATA gv_min TYPE p DECIMALS 2.          " p LENGTH 8 DECIMALS 2，无单位、无币种
...
IF ls_row-mstock > 0 AND ls_row-mstock <> gv_min.
```

三重隐患：

1. **从来没人给 `gv_min` 赋值**，永远是 0。于是 `<> gv_min` 对任何 `mstock > 0` 的行恒真，条件退化成 `mstock > 0`——半条死逻辑。
2. **`QUAN` 与无单位 `p` 比较不做单位检查**。ABAP 只在算术（尤其除法）时才因单位不一致 dump，比较会**静默给出错误结果**。把 100 KG 和 100 PC 判成相等。
3. `p LENGTH 8 DECIMALS 2` 与 `MARD-MSTOCK`（13,3）精度也不匹配。

正确做法是让它带上单位，或干脆与 `INITIAL` 比较：

```abap
DATA gv_min TYPE mard-mstock.           " 复用 QUAN 定义，自带 3 位小数
IF ls_row-mstock IS INITIAL.            " 显式表达"无库存"
  MESSAGE ...
ENDIF.
```

### 5.2 `WRITE` vs `MESSAGE`

```abap
IF ls_row-mstock > 0 AND ls_row-mstock <> gv_min.
  MESSAGE |Material { ls_row-matnr } below minimum| TYPE 'S'.
ENDIF.
```

- `TYPE 'S'` 是**成功消息**，会被缓存到消息缓冲区，**在列表末尾才集中显示**。放在 LOOP 里想"逐行提示"是达不到效果的。
- 行数较多时消息累积，会触发 **` MESSAGE（内部消息缓冲区溢出）dump**。这是循环内发消息的经典崩溃点。改成 `WRITE`、写 ALV 单元格，或 `COLLECT` 起来最后一次性汇总。
- 提示文案 `below minimum` 与实际条件（`> 0`）语义相反，条件改了文案也不会跟着变。

### 5.3 `WITH EMPTY KEY` 的连带风险

`gt_stock` / `lt_good` 都声明为 `STANDARD TABLE ... WITH EMPTY KEY`：

- 任何 `SORT` 都不保证顺序稳定（STANDARD 表 + EMPTY KEY 时排序算法依赖运行时）；
- `READ TABLE` 只能按索引 / `WHERE`，不能按键；
- **不去重**。`MARD` 主键是 `MATNR/WERKS/LGORT`，若筛选条件放宽到多工厂，同一物料会出现多行——这对"每物料一行"的报表是静默错行。

如果报表要"每物料汇总"，改成带 `SORTED ... WITH UNIQUE KEY matnr` 或先 `DELETE ADJACENT DUPLICATES`。

### 5.4 字符串模板

```abap
DATA(lv_header) = |Stock overview { lines( gt_stock ) } rows|
                  && | total qty { lv_total  W = 12 }|.
```

模板与 `&&` 拼接、模板内嵌 `lines()`、`W = 12` 格式化——这些**都是 7.40 合法语法**，`lv_total` 后面的双空格只是笔误，不影响编译。

唯一要注意的是：`W = 12` 只是**显示格式**，不改变 `lv_total` 的值，也**不能修复 §4.1 的精度截断**——格式化一个已经被截断的数字，只是把错误显示得更整齐。

`MESSAGE |...|` 内联文本同理合法。

---

## 6. 修复路线

### 6.1 建议的整体改造

1. **弃用 `FORM` / `PERFORM`**，改为 `CLASS lcl_main DEFINITION/IMPLEMENTATION`，方法之间用真实参数传递。这是消除作用域问题的根本手段——内联声明的问题 90% 来自"FORM 是平级作用域"这一非直觉规则。
2. **选数修正**：`MARD INNER JOIN MARA`（需要 `ntgew/brgew`）；`MAKT` 若要描述则再 join 或单独取，并**只把真正要用的字段放进结构**。
3. **修 `SELECT-OPTIONS`**：独立 `DATA gv_matnr TYPE mara-matnr`。
4. **重写聚合**：`REDUCE` 的类型参数用业务类型，不用单字母 `p`。
5. **确认 `FILTER` 的真实业务条件**（当前 `ntgew > brgew` 恒假）。
6. **重建表用窄结构 + 命名映射 + 补全字段**，或直接复用 `FILTER` 结果不做 `VALUE` 重建。
7. **`gv_min` 改用 `QUAN` 类型并真正赋值**；`MESSAGE` 移出循环。

### 6.2 修正后的核心骨架（示意）

```abap
CLASS lcl_report DEFINITION FINAL.
  PUBLIC SECTION.
    TYPES: BEGIN OF ty_stock,
             matnr  TYPE mara-matnr,
             maktx  TYPE makt-maktx,
             werks  TYPE mard-werks,
             lgort  TYPE mard-lgort,
             mstock TYPE mard-mstock,
             ntgew  TYPE mara-ntgew,
             brgew  TYPE mara-brgew,
           END OF ty_stock,
           ty_stock_tab TYPE STANDARD TABLE OF ty_stock WITH EMPTY KEY.
  PRIVATE SECTION.
    DATA gt_stock TYPE ty_stock_tab.
    METHODS run
      IMPORTING iv_matnr TYPE mara-matnr
                iv_waers TYPE c LENGTH 3.
    METHODS filter_and_aggregate
      RETURNING VALUE(rv_total) TYPE mara-ntgew.
ENDCLASS.

CLASS lcl_report IMPLEMENTATION.
  METHOD run.
    DATA(lo_report) = NEW lcl_report( ).
    lo_report->run( iv_matnr = gv_matnr
                    iv_waers = 'USD' ).               " 显式传参，作用域问题消失
  ENDMETHOD.

  METHOD filter_and_aggregate.
    gt_stock = FILTER ty_stock_tab( gt_stock WHERE mstock > 0 ).   " 明确的业务条件
    rv_total = REDUCE mara-ntgew( INIT sum = CONV mara-ntgew( 0 )
                                  FOR row IN gt_stock
                                  NEXT sum = sum + row-mstock ).
  ENDMETHOD.
ENDCLASS.
```

### 6.3 现代语法的使用准则（本程序提炼）

| 准则 | 反例（本程序） | 正例 |
|---|---|---|
| 内联变量不跨过程 | `lv_total` 跨 FORM | 提升为全局 / 显式 `USING` |
| `LOOP INTO DATA(x)` 显式声明显式意图 | `DATA(ls_row)` 循环外泄漏 | `DATA ls_row TYPE ty_stock.` |
| `REDUCE` 类型参数写业务类型 | `REDUCE p(` | `REDUCE mara-ntgew(` |
| 不用内建类型图省事 | `p`、`i`、`c` | 业务 DDIC 类型 |
| `VALUE #(` 映射要写全字段 | 漏 `werks`/`lgort` | 补全，或换窄结构 |
| 有键表别用 `EMPTY KEY` | `WITH EMPTY KEY` | `SORTED ... WITH UNIQUE KEY` |
| 筛选用 `FILTER`（保字段）或 `VALUE`（重建）要清楚 | 两者混用丢字段 | 明确意图 |
| 数量/金额带单位 | `TYPE p DECIMALS 2` | `TYPE mard-mstock` |
| 循环内不发消息 | `MESSAGE` in LOOP | `WRITE` / ALV / 汇总后发 |

---

## 7. 优先级建议

**必须先修（否则程序跑不起来）：**
1. 73、93 行的跨作用域内联变量（语法错误）
2. 24 行的 `SELECT-OPTIONS` 引用表组件（语法错误）
3. 37-41 行 `MARD` 取 `NTGEW/BRGEW`（字段不存在）

**必须修（能跑但数据错）：**

4. 61-63 行 `REDUCE p(` 精度截断
5. `maktx` / `waers` 的字段来源（空文本 + 假币种）
6. 58-59 行恒假过滤条件（先确认业务意图）

**建议修（质量与健壮性）：**

7. `gv_min` 的单位与恒真冗余条件
8. 循环内 `MESSAGE TYPE 'S'` 溢出风险
9. `WITH EMPTY KEY` 的重复/顺序风险
10. 删除 `lv_rows` / `lv_first` 死代码与冗余 `CONV i(`

---

## 8. 一句话总评

这份程序把 7.40 语法用在了**表面**——`@` 转义、字符串模板、`FILTER`/`REDUCE`/`VALUE` 都写得像模像样；但**作用域、单位、字段来源**这三件真正决定正确性的事情全部没跟上。典型症状是：用现代语法缩短了代码长度，却把错误从"看得见的冗长"变成了"看不见的精度截断"和"激活时才炸的语法错误"。建议先补作用域意识，再谈语法糖的收益。