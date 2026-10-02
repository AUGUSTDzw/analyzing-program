# ABAP 现代语法程序分析报告：`ZMODERN_LO`

> 分析对象：`evals/zmodern_lo.abap`（97 行，Report + 3 个 FORM）
> 关注点：7.40+ 新语法（内联声明 / 表表达式 / 字符串模板 / FILTER / REDUCE / VALUE #）是否用在了错误的位置
> 结论口径：语法与语义问题直接给出定位行号；字段级结论标注"需在系统核对"

---

## 0. TL;DR

新语法本身几乎全部**语法合法**，但有三处是**结构性的误用**，其中一处会直接让程序无法通过激活：

| # | 级别 | 问题 | 位置 |
|---|---|---|---|
| P0-1 | 阻断 | `lv_total` 在 `FORM filter_and_aggregate` 内联声明，却在 `FORM report_output` 使用 —— **FORM 局部内联变量不跨 FORM 可见** | `zmodern_lo.abap:61` ↔ `:73` |
| P0-2 | 阻断 | `SELECT-OPTIONS s_matnr FOR gt_stock-matnr` —— 选择屏不能指向内部表的组件 | `:24` |
| P0-3 | 阻断 | 从 `mard` 取 `ntgew / brgew`（类型定义却指向 `mara-`），MARD 很可能没有这两个字段 | `:37-41` vs `:14-15` |
| P1-4 | 高 | `maktx`、`waers` 从未真实填充：文本全空，币种被硬编码成 `'USD'` 写进结果集 | `:37`, `:93` |
| P1-5 | 高 | `REDUCE p( )` 默认只有 1 位小数，累加 3 位小数的 `MARD-MSTOCK` → 逐行舍入误差 | `:61-63` |
| P1-6 | 高 | `row-mstock IS INITIAL` 对 QUAN 字段不可靠（单位字段非空时即使数量为 0 也不成立） | `:55` |
| P2-7 | 中 | `lv_missing`（过滤前口径）与 `lv_total`（过滤后口径）混在同一行输出，两个数字不可比 | `:53-65` |
| P2-8 | 中 | `gt_stock = FILTER ty_stock_tab( gt_stock ... )` 自覆盖赋值，可行但极易被误读为原地修改 | `:58-59` |
| P2-9 | 中 | `VALUE ty_stock_tab( ... )` 漏映射 `werks / lgort / ntgew / brgew`，静默丢字段；又没用 `#` | `:87-93` |
| P3-10 | 低 | `lv_first` 是死代码，且语义是"计数"不是"first"；`gv_min` 从未赋值，消息文案与条件自相矛盾 | `:44-46`, `:81-83` |

**一句话给业务方**：这份报表的"骨架"（选范围 → 读数 → 过滤 → 汇总 → 输出）是对的，但**数据完整性是假的**——物料文本恒为空、币种是写死的 `'USD'`、数量精度在 REDUCE 里被吃掉；如果它已经在线上跑出数字，那些数字不能直接用。

---

## 1. 程序在做什么

```
START-OF-SELECTION
  ├─ DATA(lv_waers) = 'USD'          ← 内联声明，落在全局数据区
  ├─ PERFORM read_stock              ← SELECT mard WHERE matnr IN s_matnr AND werks = 'A100'
  ├─ PERFORM filter_and_aggregate    ← 统计零库存行数 → 过��� ntgew > brgew → 汇总 mstock
  └─ PERFORM report_output           ← 写表头 → 逐行 WRITE + MESSAGE → VALUE # 重建子集 → WRITE 整表
```

全局状态只有三个：`gt_stock`（`ty_stock_tab`，`WITH EMPTY KEY`）、`gv_min`（`p DECIMALS 2`）、`s_matnr`。**三个 FORM 之间没有任何参数传递，全部靠全局变量耦合**——这是后文所有作用域问题的根源。

一个必须先说清的业务事实：**`mard` 的一行是「物料 + 工厂 + 库存地点」**，不是「物料」。所以这个"Stock overview"其实是 A100 工厂下**按库存地点**的明细表，而后面 `VALUE #( ... )` 又把 `lgort` 丢了，同一物料会出现多行、且看不出是哪个库位的。

---

## 2. 阻断级问题

### 2.1 `lv_total` 跨 FORM 引用 —— 内联声明作用域用错了地方

```abap
FORM filter_and_aggregate.
  DATA(lv_total) = REDUCE p( ... ).          " ← :61  FORM 局部
ENDFORM.

FORM report_output.
  DATA(lv_header) = |... { lv_total  W = 12 }|.  " ← :73  另一个 FORM，看不到 lv_total
ENDFORM.
```

这是本次分析里**唯一一个纯编译期错误**：`DATA(x)` 写在 FORM 里，变量就归入该 FORM 的局部数据，`ENDFORM` 之后失效。`report_output` 里引用 `lv_total` 会得到 "未声明的变量/字段符号" 类错误，**程序无法激活**。

注意同一份代码里 `lv_waers`（`:28` 声明，`:93` 使用）却是**合法**的——因为它声明在 `START-OF-SELECTION` 这个全局事件块中，内联声明会落进程序全局数据区，FORM 内可见。一份代码里同时出现"能用"和"不能用"的跨 FORM 内联变量，说明作者对作用域规则没有建立模型，只是碰运气写对的。

**三种改法**（推荐度从高到低）：

```abap
"① 最小改动：把变量提到全局显式声明（回到传统写法，但明确）
DATA gv_total TYPE p DECIMALS 3.
FORM filter_and_aggregate.
  gv_total = REDUCE p( ... ).
ENDFORM.

"② 用 PERFORM 的形参显式传递（FORM 无参耦合被打破）
FORM filter_and_aggregate USING VALUE(p_total) TYPE p.
  p_total = REDUCE p( ... ).
ENDFORM.
" 调用：PERFORM filter_and_aggregate USING lv_total.

"③ 推荐：改局部类，FORM 全部退休，作用域由编译器保证
DATA(lo_svc) = NEW zcl_stock_service( ).
DATA(ls_sum) = lo_svc->aggregate( gt_stock ).
```

### 2.2 `SELECT-OPTIONS ... FOR gt_stock-matnr`

```abap
TYPES ty_stock_tab TYPE STANDARD TABLE OF ty_stock WITH EMPTY KEY.
DATA gt_stock TYPE ty_stock_tab.

SELECT-OPTIONS s_matnr FOR gt_stock-matnr.   " ← :24
```

`FOR` 后面必须跟一个**独立的、可持久的**数据对象（或 DDIC 表字段），不能是内部表的组件。正确写法是单独声明选择屏宿主变量：

```abap
DATA gv_matnr TYPE mara-matnr.
SELECT-OPTIONS s_matnr FOR gv_matnr.
```

附带一个容易被误解的行为：**空的选择范围表示"不限制"，不是"查不到数据"**。首次运行时 `s_matnr` 未勾选 → 内表为空 → SQL 里这个 `IN` 条件会被整体省略 → 程序把 A100 工厂的**全部**库存行读进内存。生产上要么给选择屏加必填校验，要么保留 `s_matnr` 但在 `START-OF-SELECTION` 里检查 `s_matnr[] IS INITIAL` 并提示。

### 2.3 `SELECT ... ntgew brgew FROM mard`

```abap
matnr TYPE mara-matnr,   "← 类型都取自 mara
ntgew TYPE mara-ntgew,
brgew TYPE mara-brgew,

SELECT matnr werks lgort mstock ntgew brgew
  FROM mard               "← 却从 mard 读
```

`NTGEW`（净重）/ `BRGEW`（毛重）是 MARA 的字段，类型定义也明确指向 `mara-`。**MARD 上没有这两列**，这条 SELECT 在语法检查阶段就会报"表 MARD 中不存在字段"。需要立刻在系统里确认（SE11 → MARD → Ctrl+F12 找 `NTGEW`）；如果确认没有，正确做法是 JOIN：

```abap
SELECT m~matnr m~werks m~lgort m~mstock a~ntgew a~brgew a~waers t~maktx
  FROM mard AS m
  INNER JOIN mara AS a ON a~matnr = m~matnr
  LEFT OUTER JOIN makt AS t ON t~matnr = m~matnr
                          AND t~spras = $SPRAS
  INTO TABLE @DATA(lt_stock)
  WHERE m~matnr IN @s_matnr
    AND m~werks  = 'A100'.
```

顺带一提 `INTO TABLE @gt_stock` 里的 `@` 是多余的：`@` 只在 host expression 场景才有意义，用来写内联目标 `@DATA(lt_stock)`。对一个已存在的全局变量应写 `INTO TABLE gt_stock`。解析器通常能容忍，但会让读者误以为 `gt_stock` 是个 host 变量。

---

## 3. 内联声明作用域规则（本次误用的根源）

| 声明位置 | 变量归属 | 可见范围 | 循环/表达式结束后 |
|---|---|---|---|
| `DATA(x)` 在 `START-OF-SELECTION` / 全局事件块 | 程序**全局**数据区 | 全程序，含所有 FORM、METHOD | 保留 |
| `DATA(x)` 在 `FORM` 内 | 该 FORM 的**局部**数据 | 仅本 FORM，`ENDFORM` 后消失 | 保留（但外部不可见） |
| `DATA(x)` 在 METHOD 内 | 方法局部 | 仅本方法 | 保留 |
| `LOOP AT it INTO DATA(x)` | 所在作用域 | **声明一次、循环复用**（不是每次迭代新变量） | 保留**最后一行**的值 |
| `FOR row IN ...` 于 FILTER/REDUCE/VALUE# | 表达式局部 | 仅该表达式 | 不保留 |
| `METHOD` 内 `DATA(x)` 返回 | 方法局部 | 仅本方法 | 不保留 |

三条要记住的规则：

1. **FORM 是硬边界。** 在事件块里内联声明 = 全局；在 FORM 里内联声明 = 私有。本程序 `:28` 走的是第一条（正确），`:61` 走的是第二条（错误）。
2. **`LOOP AT ... INTO DATA(x)` 只声明一次。** `ls_row` 是同一个变量被反复覆盖，`ENDLOOP` 后它仍持有最后一行数据。别在 `ENDLOOP` 之后误用"当前行"——本程序 `LOOP` 结束后的 `lt_good` 构造本身不依赖它，所以侥幸没出事。
3. **内联声明是"把数据藏起来"。** 它比 `DATA: gv_x TYPE ...` 更隐蔽：数据流向在源码里不可见，正是本程序"FORM 之间无参却共享数据"这种坏味道的温床。现代语法应该用来消除耦合，不是把耦合藏起来。

---

## 4. 表表达式逐项核对

### 4.1 `FILTER` 自覆盖赋值

```abap
gt_stock = FILTER ty_stock_tab( gt_stock
                                WHERE ntgew > brgew ).
```

`FILTER` 的结果是一个**新建**的内部表，`WHERE` 作用在源表快照上，赋值发生在结果构造完成之后，因此这行**能跑通**。但它有两个真实的坑：

- **可读性**：读者会在第一眼以为这是"原地过滤"，而 `gt_stock` 的类型/初始状态都被换掉了，而这一点对后续 `:72` 的 `lines( gt_stock )` 和 `:81` 的循环都有影响。
- **不可扩展**：一旦把这个 `FILTER` 塞进 `REDUCE` 的 `FOR` 里、或在同一个 `FOR` 的 `NEXT` 里再赋值给 `gt_stock`，就是明确的运行时错误（`REDUCE` 迭代期间不允许修改源表）。

```abap
"更安全：显式中间变量，让"过滤改变了 gt_stock"这件事写在代码里
DATA(lt_heavy) = FILTER ty_stock_tab( gt_stock WHERE ntgew > brgew ).
gt_stock = lt_heavy.
```

另外 `WHERE ntgew > brgew`（净重 > 毛重）作为"重点物料"过滤条件，量纲上说得通，但**业务含义未在程序里体现**——建议加注释或改名为 `zcl_heavy_only`。

### 4.2 `REDUCE p( ... )` —— 精度被吃掉了

```abap
DATA(lv_total) = REDUCE p( INIT sum = 0
                           FOR row IN gt_stock
                           NEXT sum = sum + row-mstock ).
```

**这是最容易漏掉的一个 P1 问题**：ABAP 中 `p` 类型的默认 `DECIMALS` 是 **1**。而 `MARD-MSTOCK` 是 `QUAN`（15 位数值 + **3 位小数** + 3 位单位字段）。所以每次 `sum + row-mstock` 都会把结果收敛到 1 位小数——**每一行都在舍入**，汇总 10 万行时误差不可控。

```abap
"要么显式给足精度
DATA(lv_total) = REDUCE ty_sum( INIT sum = CONV ty_sum( 0 )
                                FOR row IN gt_stock
                                NEXT sum = sum + row-mstock ).
TYPES ty_sum TYPE p LENGTH 15 DECIMALS 3.

"要么干脆别用 p —— 直接用 QUAN，单位和精度一起保住
DATA(lv_total) = REDUCE mara-ntgew( ... ).   " 仍不理想
```

另外，`p` 累加 **丢弃了单位**。A100 下混着 KG 和 STU 的行，被压进一个裸 `p` 里，加出来的小数没有业务含义。如果只是要"一个能显示的总数"，至少在输出处注明"单位已归一"。

### 4.3 `REDUCE i( ... )` —— 命名与语义不符，且是死代码

```abap
DATA(lv_first) = CONV i( REDUCE i( INIT m = 0
                                   FOR row IN gt_stock
                                   NEXT m = m + 1 ) ).
```

- `lv_first` 从头到尾**没有被使用**——纯死代码，编译器不会报错，但会让读代码的人以为有个"首行"逻辑。
- 它算的是**行数**，和 `lines( gt_stock )` 完全等价（`:43` 已经算过一次了）。
- `CONV i( REDUCE i( ... ) )` 是双重冗余：内层 `REDUCE i( )` 的结果类型已经是 `i`，外面再套 `CONV i( )` 没有任何作用（这通常是无声加了个 `no_conversion` 之外的干扰）。

```abap
"删掉；若真要首行，用 LOOP + EXIT
DATA(ls_first) = gt_stock[ 1 ].   " EMPTY KEY 表只能按位置取，正好可用
```

### 4.4 `COND i( ... IS INITIAL ... )` —— QUAN 的坑

```abap
DATA(lv_missing) = REDUCE i( INIT sum = 0
                             FOR row IN gt_stock
                             NEXT sum = sum + COND i(
                               WHEN row-mstock IS INITIAL THEN 1 ELSE 0 ) ).
```

`MARD-MSTOCK` 是 `QUAN`，在 ABAP 里是**一个结构**：15 位数值（3 位小数）+ 3 位单位字段。`IS INITIAL` 检查的是**整个字段**，包括单位。所以一行"数量 0.000、单位 'KG'"的库存 **不是 INITIAL**，会被漏统计。

```abap
"要判断"数量为零"，必须显式比较数值部分
NEXT sum = sum + COND i( WHEN row-mstock = 0 THEN 1 ELSE 0 )
```

另外名字也有误导：`lv_missing` 数的是**零库存行**，不是"数据缺失"。若目的是"报表可信度校验"，应该同时输出总行数 `: lines( gt_stock )` 和零行数，让两者成对出现。

### 4.5 `VALUE #` 的映射 —— 字段静默丢失

```abap
DATA(lt_good) = VALUE ty_stock_tab(
  FOR row IN gt_stock
  WHERE ( mstock > 0 )
  ( matnr  = row-matnr
    maktx  = row-maktx
    mstock = row-mstock
    waers  = lv_waers ) ).
```

四个要点：

1. **没列出的字段 = initial，不报错。** `werks`、`lgort`、`ntgew`、`brgew` 全被静默清空。而因为源表是 `WITH EMPTY KEY`，重复键也不会报错——`lt_good` 里同一物料重复出现，是静默的。
2. **`maktx` 是空的。** `:37` 的 SELECT 根本没取 `MKTX`（也没 JOIN `MAKT`），所以 `row-maktx` 恒为 initial，这里只是在**把空气复制一份**。用户会看到"物料号有、名称列空白"。
3. **`waers = lv_waers` 是在伪造数据。** `'USD'` 硬编码，与 `MARA-WAERS` 的真实币种无关。这个字段一旦流入下游报表或导出文件，就是**业务事故**级别的脏数据。要么 JOIN 出来，要么就**不要这个字段**，别用假值占位。
4. **用 `VALUE ty_stock_tab( )` 而不是 `VALUE #( )`。** `VALUE #(` 会从目标变量 `lt_good` 推导类型（ABAP 的推导类型），更短、更不会写出与目标不一致的类型。这里二者等价，但 `#` 是 7.40 之后的标准惯用法。

修正版：

```abap
"字段不缺、币种真实、不静默重复
DATA(lt_good) = VALUE ty_stock_tab(
  FOR row IN gt_stock
  WHERE ( mstock > 0 )
  ( matnr  = row-matnr
    maktx  = row-maktx          " ← 前提：SELECT 里真的 JOIN 了 MAKT
    werks  = row-werks          " ← 补回被丢的字段
    lgort  = row-lgort
    mstock = row-mstock
    ntgew  = row-ntgew
    brgew  = row-brgew
    waers  = row-waers ) ).     " ← 取真实币种，而不是 lv_waers
```

### 4.6 `lines( )` 与字符串模板

```abap
DATA(lv_header) = |Stock overview { lines( gt_stock ) } rows|
                  && | total qty { lv_total  W = 12 }|.
```

- `lines( )` 是内建函数不是表表达式，在模板里合法，没问题。
- `{ lv_total W = 12 }`：**`W = 12` 对 `p` 会补足符号位和小数位**，结果**带尾部空格**，再用 `&&` 拼接时这些空格会原样进串。显示上无害，但如果 `lv_header` 后续被 `CONDENSE`、比较或定长写入，就是埋雷。`p` 类型建议改用 `{ lv_total DECIMALS = 3 }` 明确小数位，把对齐交给 `WRITE` 或 ALV。
- `|{ ls_row-matnr ALPHA = OUT }|`（`:79`）：`ALPHA = OUT` 会把物料号补成前导零的长串。在 basic list 报表里通常**不**想要这种"看起来像主键全量"的形式，建议 `ALPHA = NO-GAP` 或干脆直接输出。

---

## 5. 字段语义与数据质量

| 字段 | 来源 | 现状 | 后果 |
|---|---|---|---|
| `matnr` | `mard-matnr` | 正常 | — |
| `maktx` | `makt-maktx` | **从未 SELECT** | 名称列全空 |
| `waers` | `mara-waers` | **从未 SELECT**，`lv_waers` 硬编码 `'USD'` | 币种伪造；`'USD'` 是 `c(3)`，写入 `c(5)` 的 `waers` 会补成 `'USD  '`，后续等值比较必失败 |
| `mstock` | `mard-mstock` (QUAN) | 正常，但 REDUCE 里降精度 | 汇总误差 |
| `ntgew/brgew` | 定义为 `mara-`，却从 `mard` 取 | 字段可能不存在 | 激活失败 |
| `werks`/`lgort` | 正常读取，但 `VALUE #` 里被丢 | 结果集丢失库位维度 | 同物料多行无法辨识 |

关于 `gv_min`：

```abap
DATA gv_min TYPE p DECIMALS 2.          " ← 从未赋值，恒为 0；且无单位
IF ls_row-mstock > 0 AND ls_row-mstock <> gv_min.
  MESSAGE |Material { ls_row-matnr } below minimum| TYPE 'S'.
ENDIF.
```

三重问题：

1. `gv_min` 无人赋值 → 恒为 initial → `ls_row-mstock <> gv_min` 恒为真 → **整个第二个条件是废的**，等价于只判 `mstock > 0`。
2. `mstock > 0` 与文案 "below minimum"（低于最小值）**语义相反**：条件成立意味着有库存，消息却说低于下限。这属于会误导用户的文案错误。
3. `p DECIMALS 2` 与 `QUAN` 比较时小数位不一致（2 vs 3），第三个小数位的差异被静默忽略。

```abap
"最小库存应该和库存同型、同单位
DATA gv_min TYPE mard-mstock.   " QUAN，保留单位
...
IF ls_row-mstock < gv_min.
  MESSAGE |Material { ls_row-matnr ALPHA = OUT } below minimum { gv_min }| TYPE 'S'.
ENDIF.
```

另外，`MESSAGE TYPE 'S'` 写在 `LOOP` 里 = **每一行弹一次消息框**。基本列表报表里这样会锁死屏幕；批处理下还会刷屏。应当收集到内表，最后汇总提示，或干脆改 ALV + 消息收集。

---

## 6. 风险清单（按处置优先级）

| 优先级 | 风险 | 影响面 |
|---|---|---|
| P0 | 程序无法激活（`lv_total` 作用域 / `SELECT-OPTIONS FOR` / MARD 字段） | 编译 |
| P1 | `maktx` 空、`waers` 伪造 `'USD'` | 数据正确性，且可能已流入下游 |
| P1 | REDUCE `p` 精度 1 位累加 QUAN 3 位 | 汇总数字失真 |
| P1 | 全表被读入内存（空选择范围 = 不限制） | A100 全量行，`gt_stock` 可能很大；`WITH EMPTY KEY` 表只能线性访问，输出 O(n²) 风险 |
| P2 | `lv_missing`（过滤前）与 `lv_total`（过滤后）同屏输出 | 数字不可比，读者误读 |
| P2 | `VALUE #` 静默丢字段 + EMPTY KEY 不报错 | 结果表重复无法察觉 |
| P2 | QUAN `IS INITIAL` 漏统计 | 校验行数不准 |
| P3 | MESSAGE 在循环内 / `gv_min` 死条件 / `lv_first` 死代码 / `@` 冗余 | 可维护性 |

关于 `WITH EMPTY KEY`（`:19`）再补一句：这是**正确**的选择（报表输出表不需要键），但它的代价是**只能按位置读取**——`SORT` 之后无法 `READ ... BINARY SEARCH`，也不能 `MODIFY ... BY KEY`。一旦这个表被别人拿去当 lookup 用，就会踩坑，值得在类型上加注释固化这个约定。

---

## 7. 一个"干净"的参考骨架

```abap
TYPES: BEGIN OF ty_stock,
         matnr TYPE mara-matnr,
         maktx TYPE makt-maktx,
         werks TYPE mard-werks,
         lgort TYPE mard-lgort,
         mstock TYPE mard-mstock,     " QUAN：单位和 3 位小数都保住
         ntgew TYPE mara-ntgew,
         brgew TYPE mara-brgew,
         waers TYPE mara-waers,       " 真实币种
       END OF ty_stock.
TYPES ty_stock_tab TYPE STANDARD TABLE OF ty_stock WITH EMPTY KEY.

DATA gt_stock TYPE ty_stock_tab.
DATA gv_matnr TYPE mara-matnr.        " ① 选择屏宿主变量
SELECT-OPTIONS s_matnr FOR gv_matnr.

START-OF-SELECTION.
  PERFORM read_stock.                " ② 全局变量只留 gt_stock 一个
  PERFORM report_output.

FORM read_stock.
  IF s_matnr[] IS INITIAL.
    MESSAGE '请选择物料范围' TYPE 'S'.   " ③ 空范围 = 不限制，必须拦
    LEAVE LIST-PROCESSING.
  ENDIF.

  SELECT m~matnr m~werks m~lgort m~mstock
         a~ntgew a~brgew a~waers
         t~maktx
    FROM mard AS m
    INNER JOIN mara AS a ON a~matnr = m~matnr
    LEFT OUTER JOIN makt AS t ON t~matnr = m~matnr AND t~spras = $SPRAS
    INTO TABLE gt_stock              " ④ 去掉多余的 @
    WHERE m~matnr IN @s_matnr
      AND m~werks  = 'A100'.

  DATA(lt_heavy) = FILTER ty_stock_tab( gt_stock WHERE ntgew > brgew ).  " ⑤ 中间变量
  gt_stock = lt_heavy.
ENDFORM.

FORM report_output.
  TYPES ty_sum TYPE p LENGTH 15 DECIMALS 3.
  DATA(lv_zero_rows) = REDUCE i( INIT c = 0
                                 FOR row IN gt_stock
                                 NEXT c = c + COND i( WHEN row-mstock = 0 THEN 1 ELSE 0 ) ).  " ⑥ = 0 而非 IS INITIAL
  DATA(lv_total)     = REDUCE ty_sum( INIT sum = CONV ty_sum( 0 )      " ⑦ 足精度
                                      FOR row IN gt_stock
                                      NEXT sum = sum + row-mstock ).

  WRITE: / |Total rows { lines( gt_stock ) }, zero-stock rows { lv_zero_rows }|.  " ⑧ 两个口径都在过滤后
  WRITE: / |Total qty { lv_total DECIMALS = 3 }|.

  LOOP AT gt_stock INTO DATA(ls_row).
    WRITE: / |{ ls_row-matnr ALPHA = OUT } qty { ls_row-mstock W = 10 }|.
  ENDLOOP.
ENDFORM.
```

改动要点：选择屏宿主独立（②）、空范围拦截（③）、JOIN 补齐字段（④⑤）、`= 0` 替代 `IS INITIAL`（⑥）、`REDUCE` 指定精度（⑦）、口径统一（⑧）。原来的三个 `FORM` 里，`read_stock` 内部包含了过滤，逻辑上更内聚，跨 FORM 传参的需求随之消失——**作用域问题的正解是消除跨作用域需求，不是给变量搬家**。

---

## 8. 使用现代语法的判断标准（沉淀）

- 内联声明适合**表达式内部的一次性中间值**（`LOOP ... INTO DATA()`、模板里的计算）；一旦需要**跨 FORM / 跨方法 / 跨事件块**共享，它就是错的——显式声明反而更安全。
- `FILTER` / `VALUE #` / `REDUCE` 三件套的前提是**源数据语义干净**。源字段没读出来时，表表达式只会**更快地把空值传播下去**，错得更有条理。
- `REDUCE` 的结果类型决定汇总精度。累加 `QUAN`/`CURR` 时**必须**给显式类型，否则默认 `p(1)` 会静默舍入。
- 表构造器漏映射字段**不报错**，这是 7.40 语法里最容易埋雷的地方之一。写完 `VALUE #( ... )` 一定要逐字段对照 `ty_` 定义核一遍。
- 命名要能自解释：`lv_first`（实为 count）、`lv_missing`（实为零库存行数）、`gv_min`（恒为 0）——现代语法让代码变短，也让**错误命名藏得更深**。

---

## 9. 上线前必须验证的清单

- [ ] SE11 确认 `MARD` 是否存在 `NTGEW` / `BRGEW`；不存在则改 JOIN `MARA`
- [ ] SE11 确认 `MARA-WAERS` 的实际长度（`c(5)`？），以及是否需要 `MARAX` 里的 `WRSFX`
- [ ] 激活时确认 `lv_total` 的跨 FORM 引用报错（预期报错）
- [ ] 跑一笔已知数据，人工核对 `lv_total` 与 `SUM(mstock)`（Excel 侧 SUM）的差值，检查第 3 位小数
- [ ] 确认 `maktx` 在修复前是全空（若是，说明报表上线至今的名称列一直是无效列）
- [ ] 确认没有任何下游程序/导出文件消费过 `waers` 字段（`'USD  '` 已污染）
- [ ] 评估 A100 全量数据规模，必要时在 `lv_waers`/空范围处加限制或改包大小查询

---

*报告基于源码静态阅读生成。标注"需在系统核对"的结论（字段存在性、长度、字段长度语义）请以 SE11 / DDIC 实际定义为准。*