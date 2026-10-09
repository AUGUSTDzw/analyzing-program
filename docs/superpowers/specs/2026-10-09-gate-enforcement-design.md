# 1.1.0 设计：让闸门能拦住「形状完美、内容全废」的报告

日期：2026-10-09
状态：待实施
前置：1.0.9 出货（`7e136a9`）、1.0.7 产物补齐（`8d20287`）、1.0.9 效果实验（`c14266e`）

## 问题

1.0.9 的闸门（`scripts/report_qc.py`，1218 行）能证明报告**长得像报告**，不能证明
报告**说得对**。实测四个方向都能拿到 `PASS` / exit 0：

| 篡改 | 结果 |
|---|---|
| 往 ` ```abap ` 围栏插入源码里不存在的语句 | `PASS` exit 0，仅打印 note |
| 把第五节 4 行真实 P0 换成 `\| P0 \| 无 \| 这段代码写得很好 \|` | `PASS` exit 0 |
| 把 70 行三层压成同一句空话 | `PASS` exit 0 |
| 删掉全部 Mermaid 图 | `PASS` exit 0 |

散文里注入 `U+FFFD` 同样通过。共同点是：**闸门看见的每一项都合格，它看不见的那一项
（报告说了什么）是假的。**

保真检查尤其刺眼——它把唯一的信号打印出来
（`1 quoted statement(s) of 182 do not occur in the source ... Check whether the
report rewrote the source.`），然后仍然 exit 0。

规模上：`report_qc.py` 1218 行 / 54759 字节，是 `SKILL.md`（476 行 / 32191 字节）的
2.6 倍行数、1.7 倍字节。

## 目标

1. 闸门对最严重的一类错误（编造源码、内容空洞）有强制力
2. 闸门体积倒挂得到缓解
3. 出货证据与实测一致

**非目标**：提升报告的分析能力。1.1.0 改的是闸门，不是 skill 的判断力。这些改动
**不产生任何效果证据**，README 不得出现"提升了效果"的说法。

## 关键决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 范围 | 强制面 + 证据层 + 规模 + 回归测试 | 四个领域都做 |
| 保真假阳性 | 按失配类型分档 | `fidelity_note` docstring 自己给了判据：16 条失配里 11 条是实质性的 |
| 闸门改法 | 拆分模块，规则不改 | 1218 行重写风险太高，drift 测试是唯一护栏 |
| 版本 | 1.1.0 | 契约 enforcement 变了，但没删检查、没改既有要求 |

## 设计

### 1. 模块边界

```
scripts/
  report_qc.py              编排 + 退出码 + CLI（目标 < 400 行）
  checks/
    __init__.py
    contract.py             读 report-contract.json，一次加载
    text.py                 _flat / _claims / _strip_comment / fence_spans / line_of …
    structure.py            现有 check() 原样搬入
    fidelity.py             fidelity_note + 分档判定
    encoding.py             U+FFFD 检查
    advisory.py             density / fix-lang / authz / ext-asset
```

`text.py` 是唯一公共层，其余三个互不依赖。

**搬家不改行为**：`check()` 搬进 `structure.py` 后返回值、退出码、157 项测试必须
逐字不变。`fidelity_note` 现在用的 `_flat`/`_claims` 从 `text.py` 来，不重写。

模块边界由 `test_contract_drift.py` 守住：扩展成检查"规则在哪个模块"（例如 Mermaid
规则只能在 `structure.py`），防止有人把规则塞回主文件。

### 2. 保真分档

现在：`fidelity_note` 做 `_flat(probe) not in _flat(src)`，即扁平化后的**子串包含**。
`_flat` 只归一化了 `[,;:)]` 的空白，所以 `.` `-` `=>` 的任何差异都算失配——这正是
docstring 里那 5 条假阳性的来源。

改成两段判定。对每条被 `_claims` 认定为源码的语句：

```
1. tokenize 成序列，元素分四类：
   ident    [A-Za-z_][A-Za-z0-9_]*   关键字与名字，一律小写
   literal  '...'                     原样比对，大小写敏感
   number   数字字面量                 原样
   punct    . , ; : ( ) - + => 等     运算符与标点

2. 在源码的 token 流里找该语句的 token 序列（连续子序列）
3. 同时跑旧的那个扁平子串包含判定，取两者的差集定档：

| 旧子串检查 | 新 token 检查 | 结论 |
|---|---|---|
| 失配 | 失配 | `SUBSTANTIVE` — 标识符/字面量/数字被改过，exit 1 |
| 失配 | 忠实 | `PUNCT-ONLY` — 旧检查的假阳性，advisory |
| 忠实 | 忠实 | 忠实，不出 note |

**PUNCT-ONLY 必须按这个差集定档，不能按单条语句判断。** 理由是可证明的：
`identity()` 两边都剥掉 punct，所以任何只差标点的语句其 identity 必然相等 → 第 2 步
就已被判为忠实，**永远进不了"失配"的输出**。写成"这条语句看起来只差标点"会得到一个
恒为 False 的死代码。

保留旧判定不是为了怀旧：没有它就没有办法区分"标点滑动"与"重写"，只能区分"有差异"与
"无差异"。它同时是判据 A 的比较基准。

这也让判据 A 与 B 变成同一个函数的输出：A 是"旧失配集合 ⊆ 新标记集合"，
B 是"SUBSTANTIVE 计数为 0"。
```

字符串字面量进身份比对：改一个字面量就是改数据语义（`'BUK'` 写成 `'LIFNR'`），
必须算实质失配。

失败输出：

```
FAIL  report.md
  fid  line 105  SUBSTANTIVE  quoted statement does not occur in the source
       report : lv_tampered = fabricated_token_does_not_exist( ) .
       source : (no line shares its identifier sequence)
  fid  3 punctuation-only mismatch(es), advisory:
       line 210 'lv_cnt = lv_cnt + 1 .'  vs source 'lv_cnt = lv_cnt + 1'
```

SUBSTANTIVE 退 1；PUNCT-ONLY 保持退 0 但照旧打印。

**接受标准（硬性，可机械判定）**：

把现有子串检查与新分类器都跑过 `analyzing-programs-workspace/` 下的全部存档报告
（`conformance-probe-*/`、`heldout-1.0.7/`、`exp-1.0.9/` 下的报告，共 27 份候选，
实施时以实际枚举为准），必须同时满足：

- **A 不漏**：新分类器标记为失配的语句集合 ⊇ 旧子串检查标记的集合。
  一次重写绝不能让原本被发现的失配变成沉默。
- **B 不误伤**：新分类器判为 SUBSTANTIVE 的语句总数为 **0**。若非 0，逐条人工看过
  并写明理由；无法说明理由的那些，退回标点子集白名单。

B 为 0 是因为存档报告都是**能进闸门**的报告，它们此前没有触发过 exit 1。`_strip_comment`
的 docstring 记着当初的分类器是在存档报告上调出来的，代价是四次重写、零假阳性——新分类器
必须继承这个性质。

注意：存档报告由**不同版本**的 skill 生成，若 B 非 0 并不自动说明分类器错，也可能是
那些报告确实有问题。所以 B 非 0 时逐条判定，不整体推翻。

**已知不修的边界**：`_claims` 逐行比对，ABAP 用 `+` 或逗号续行的跨行语句，其续行
单独比对时可能匹配不上。这是现有行为，分档不改变它。修它要改 `_claims` 的分句逻辑，
是另一件事，避免混在一个 diff 里。

### 3. 五条新检查

全部 exit 1。

| | 规则 | 契约键 |
|---|---|---|
| C1 | 第五节每个问题行至少点名一个源码里真实存在的标识符 | `problem_section.rows_require_source_object` |
| C2 | 一个围栏后的三层正文不得三行相同 | `layers.distinct` |
| C3 | 全文任何位置出现 `U+FFFD` 即失败 | `encoding.replacement_char` |
| C4 | 至少 1 张 `flowchart` + 至少 1 张 `sequenceDiagram` | `mermaid.required_diagrams` |
| C5 | 六节每节恰好命中一次（现在只数存在） | `sections.exactly_once` |

**C1** 的判定：行里至少有一个反引号包裹的 token，**或**有一个形似标识符的 token
（`[A-Za-z_][A-Za-z0-9_]*`，长度 ≥ 3）能在源码全文里搜到。

不直接依赖 `inventory(src)`——它只返回 `ANCHORS` 匹配到的**子程序名**（FORM /
FUNCTION / MODULE 等），而问题行经常引用的是字段名、表名、变量名，那些不在
inventory 里。判据用"源码全文搜得到"更宽也更少误伤；`inventory()` 留给 density
advisory 用。

**C2** 一处围栏后的三层正文取集合比较，三行相同即失败。

**C3** 让 `exp-1.0.9/with_skill/run3.md` 从 PASS 变 FAIL，**这是故意的**：它把上一轮
"刻意不修"的编码损坏变成闸门能看见的东西。存档报告里只有 run3 有 U+FFFD。

**C4** 不定成"总数 ≥ 2"而是两个类型各 ≥ 1，因为 `SKILL.md:206` 和 `:217` 点名的
就是这两张不同的图，只数总数的话两张 flowchart 也能过。这是五条里最贴规格、也最
容易和模型现有习惯打架的一条。

**C5** `present` 计数改成"每节恰好命中一次"。

### 4. 明确不做

- **P2-7 长度上限**：设上限会把膨胀问题变成新的失败原因，而 n=3 实验不足以判断
  多长合适。要定阈值，先得有"膨胀比 vs 召回"的实测关系。
- **P2-8 规模**：这轮只拆分，不重写规则。`check()` 搬进 `structure.py` 后行数不变。
- **P2-9 `__pycache__`**：已被 gitignore、不进 zip，无动作。

## 分批

每批独立可停，风险递增。

| 批次 | 内容 | 出口条件 |
|---|---|---|
| 1 | 把 7 个探针固化成回归测试，**钉住现状**（闸门现在放过它们） | 7 个用例全绿，且记录下当前行为 |
| 2 | 拆分模块，规则不改 | 157 + 107 逐字不变 |
| 3 | 契约加 5 个键 + 实现 C1–C5 + fidelity 分档 | 判据 A 与 B 同时成立 |
| 4 | README 三处 + 出 1.1.0 + 重打 release | 三方字节一致 + SHA256SUMS 全命中 |

批次 1 先固化"闸门放过它们"很关键：这样批次 3 才有对照——**同一批探针，从"记录
它错"变成"证明它对了"**。

## 证据层改动

README 三处，全部是改说法，不是加数字：

1. 出货版本的效果证据：现在是"零证据"。改为本轮真实状态——**n=3、盲判、结论不支持
   假设**，写清"两臂各 1/3 达到满档，10/12 vs 9/12"和"21 条里 7 条六次判定完全一致"。
   **不能**把这轮算成 1.0.9 的效果证据，它什么都没证明。
2. n=9 那节补一句：属于 `fac4d5a3`（1.0.3），**与本轮 n=3 不可合并**（程序不同、
   派发条件不同）。
3. 新增一节记录**区分度体检**：21 条里 7 条（33%）六次判定完全一致，整体 recall 差距
   主要由噪声决定。这是本轮最有价值的产出，比任何单次召回数字都该进 README。

`shipped_with` 表加 1.1.0 一行。

## 诚实边界

这些改动改的是**闸门**，不是 skill 的分析能力。做完之后闸门能拦住"编造源码"和
"内容空洞"，但它**依然测不出报告分析得好不好**——那需要新一轮实验，而本轮 n=3 已经
说明这个规模测不出来。

闸门有牙齿的证据也要一并保住：把报告砍到原文 1.6%（只剩六节标题 + 一个围栏）会
exit 1；三层标签缺失、位置标签带行号、Mermaid 裸尖括号、第五节缺优先级桶，全部拦得住。
这些是批次 2 的回归基线，不许在拆分中退化。