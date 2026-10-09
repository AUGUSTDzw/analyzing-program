# Task 4 报告：契约加 5 个键，drift 测试守住模块边界

**状态：DONE**
**分支：** `feature/gate-enforcement`
**基线：** `56a466f`

---

## 一句话

契约 `1.2.6 -> 1.3.0`、`release.ships_with 1.0.9 -> 1.1.0`，五个规则键落进契约，
`gate_io.exit_codes["2"]` 补上拆包带来的两个退 2 触发条件，drift 测试从 **107 涨到
118**，另两个套件 **165 / 20 一动不动**，闸门在 16 个用例上的输出与加键前逐字节相同
（唯一差异是 `plain no args` 打印的模块 docstring，那正是本任务修的第 5 条遗留）。

---

## Step 1：写失败测试

在 `tests/test_contract_drift.py` 里加 `load_contract()`（brief Step 1 给的定义，
原文件没有），并在 `main()` 的 `print("every contract rule is wired into the gate")`
之前插入 `1.1.0 rule keys` 一节。

brief 给的探针原样照抄，两处按下面的"brief 修正"改成 `.get()` 守卫。

### Step 1 实际输出

改动后、契约未改时：

```
1.1.0 rule keys
--------------------------------------------------------------------------
  FAIL  contract version is 1.3.0   1.2.6
  FAIL  contract ships with 1.1.0   1.0.9
  FAIL  rows_require_source_object is declared and on
  FAIL  layers.distinct is declared and on
  FAIL  encoding.replacement_char is U+FFFD
  FAIL  mermaid.required_diagrams names both diagrams
  FAIL  sections_exactly_once is declared and on

7 drift check(s) failed, 107 passed:
  - contract version is 1.3.0
  - contract ships with 1.1.0
  - rows_require_source_object is declared and on
  - layers.distinct is declared and on
  - encoding.replacement_char is U+FFFD
  - mermaid.required_diagrams names both diagrams
  - sections_exactly_once is declared and on
exit=1
```

brief Step 2 期望"至少 6 个 FAIL"。实测 **7 个 FAIL / 107 passed**，因为 brief 自己
的 Step 1 代码块里有 7 个 `check()` 而不是 6 个（version、ships_with、
rows_require_source_object、distinct、replacement_char、required_diagrams、
sections_exactly_once）。"至少 6"成立。

## Step 2：运行确认失败

上面就是。**注意**：brief 的代码块直接写 `C["encoding"]` / `C["mermaid"]`，在契约还
是 1.2.6 时第一版跑出来是一个 `KeyError: 'encoding'` traceback，套件死在第 5 个
check 上——不是 FAIL，是崩溃。见"brief 修正"一节。

## Step 3：改契约

`schemas/report-contract.json`：

- `"version": "1.2.6"` → `"1.3.0"`
- `release.ships_with`: `"1.0.9"` → `"1.1.0"`
- `problem_section` 内加 `"rows_require_source_object": true`
- `layers` 内加 `"distinct": true` 与 `"distinct_why": "..."`
- `mermaid` 内加 `"required_diagrams": ["flowchart", "sequenceDiagram"]`
- 顶层加 `"sections_exactly_once": true`
- 顶层加 `encoding` 对象（`replacement_char` / `why` / `skill_anchor`）
- `release._comment` 顶部补两段：1.3.0 记五个键、记 exit_codes["2"] 补两行

`encoding.replacement_char` 写成 JSON 转义（反斜杠 + ufffd），不是字面 U+FFFD。理由：
契约文件本身被 `encoding.replacement_char` 管着，一个字面 U+FFFD 落在契约里会让
"检查器自己坏在编码上"这条批评变成真的。改完后全文件 `U+FFFD` 字面量计数为 0。

`encoding.skill_anchor` 用 `"先转成 UTF-8 再跑"`，不是 brief 写的 `"保存为 UTF-8"`。
理由见"brief 修正"。

## Step 4：运行确认通过

```
115 drift checks passed, 0 failed
exit=0
```

brief Step 4 写 `113 drift checks passed, 0 failed`（107 + 6）。实测 **115**。
差的 2 条：

1. Step 1 是 7 个 check 不是 6 个（上面已列）
2. 新增的 `encoding.skill_anchor` 让 `anchors()` 多收一条，drift 的
   "every enforced rule is taught" 一节从 22 条 anchor 涨到 23 条，多一个 check。
   这是加 skill_anchor 的必然代价，不是重复计数

逐条 diff（`git stash` 前后各跑一次，逐行 `Compare-Object`）：

```
=> ok skill_anchor: '先转成 UTF-8 再跑' appears in SKILL.md
=> ok contract version is 1.3.0 1.3.0
=> ok contract ships with 1.1.0 1.1.0
=> ok rows_require_source_object is declared and on
=> ok layers.distinct is declared and on
=> ok encoding.replacement_char is U+FFFD   (detail column holds the char itself)
=> ok mermaid.required_diagrams names both diagrams ['flowchart', 'sequenceDiagram']
=> ok sections_exactly_once is declared and on
```

**零删除、零修改、零翻转**，只有 8 条新增。

## Step 5：加模块边界检查

`main()` 末尾（汇总之前）加 `rule placement` 一节。brief 给的探针改成明确断言，
并按 brief 自己的要求把 `def check(` 探针收紧成"结果必须恰好等于"：

```
rule placement
--------------------------------------------------------------------------
  ok    mermaid_labels() is defined in checks/text.py   ['checks/text.py']
  ok    check() is defined in checks/structure.py       ['checks/structure.py']
  ok    all_notes() is defined in checks/advisory.py     ['checks/advisory.py']
```

brief Step 5 只给了 2 个 check 并写 `116 drift checks passed`（113 + 3）。实测加了
**3** 个（第三条是 `all_notes()` 的归属），最终落在 **118**：

```
118 drift checks passed, 0 failed
exit=0
```

brief 的 `def mermaid_labels(` 我换成了裸 `mermaid_labels` 探针会怎样，见
"brief 修正"第 3 条——答案是会 FAIL，所以必须改。

## Step 6 / Step 7：三个套件与提交

```
118 drift checks passed, 0 failed
165 checks passed, 0 failed
20 checks passed, 0 failed
```

| 套件 | Task 3 后 | Task 4 后 | 期望 |
| --- | --- | --- | --- |
| `test_contract_drift.py` | 107 | **118** | 增加 |
| `test_skill.py` | 165 | **165** | 不变 |
| `test_gate_enforcement.py` | 20 | **20** | 不变 |

`tests/test_skill.py` 与 `tests/test_gate_enforcement.py` 一个字节都没动
（`git status` 里不在修改列表）。

---

## 六个前序遗留，逐条

### 1. `gate_io.exit_codes["2"]` 补两行

拆包新增的两个退 2 触发条件此前不在契约那张表里，正是这个闸门要防的那类对不上。
两条都补进 `"2"` 那一行的既有行文里（同一个字符串，按 mode 分段的 `;` 分隔句式）：

```
common, the gate's own detectors did not load -- scripts/checks/ is absent or a
module in it will not parse / no arguments / ...
```

行文风格照旧：与其他 per-mode 触发条件同段、用 `/` 分隔、`and in all three modes`
那种从句照旧。**为什么排在 common 段最前**：这两个在 import 期触发，argv 还没读，
所以"哪个 mode"从来不是决定它们的东西——这句话也写进去了。

同时给 `exit_codes.measured` 补了一句 1.3.0 的实测记录，因为 `_comment` 明写
"Every row below was measured by running the gate, not read off the source"。
实测方式（两次都跑过，输出贴在这里）：

```
# 删掉 scripts/checks/
error  cannot load the checks at ...\scripts (No module named 'checks'), so nothing was checked
exit=2

# 给 checks/text.py 追加一行语法错误
error  cannot load the checks at ...\scripts (invalid syntax (text.py, line 364)), so nothing was checked
exit=2
```

两条都走 `report_qc.py:108` 的 `except (ImportError, SyntaxError)`，都打 `error`
行，都退 2。**补了两行**（一个 ImportError 触发条件、一个 SyntaxError 触发条件）。

### 2. `contract.py` 模块 docstring 的版本句

原文：

```
Contract version 1.2.6 -> 1.3.0 in 1.1.0 (five new rule keys). Shipped with
1.1.0.
```

本任务让这句话成真。核对结果：契约确实是 `1.3.0`，`ships_with` 确实是 `1.1.0`，
新增的规则键数了一遍——`problem_section.rows_require_source_object`、
`layers.distinct`、`encoding.replacement_char`、`mermaid.required_diagrams`、
`sections_exactly_once`——**正好五个**，"five new rule keys" 没说错。

本任务把这句话改成了把五个键名列出来：

```
Contract version 1.2.6 -> 1.3.0 in 1.1.0. Five new rule keys:
problem_section.rows_require_source_object, layers.distinct,
encoding.replacement_char, mermaid.required_diagrams, sections_exactly_once.
Shipped with 1.1.0.
```

理由：一个只写"five"的断言，第五个键被删掉再补一个新的照样通过；把名字写下来，
它就成了一条可被 drift 测试读到的声明。

### 3. `advisory.py:10` 的 plain mode 限定

原文：`Plain mode still prints it as a note and still exits 0.`

结构有缺陷时 plain mode 退 1，那个退码来自 `check()` 单独决定，与 fidelity 无关。
改为：

```
Plain mode
prints it as a note and its exit code is check()'s alone: 0 when the structure is
clean, 1 when check() found a defect, and nothing in between on this note's
account.
```

### 4. `advisory.py:3-4` 与 `:8-10` 的自相矛盾

原文第一段引 `die()` 的 "a note never stops the run"，第四段说 fidelity 在
`--fidelity-only` 下退 1。同一个 docstring 里两句打架。改法不是删掉任何一句，是把
两者的管辖范围说清楚：

- `die()` 那句对**它当初要防的失败**是对的——把致命错误标成 note，调用方 grep
  advisories 会把硬失败收成软失败。这层保留。
- 本模块的六个 note 函数**返回字符串、谁也不 print**，所以本模块里没有任何东西能
  决定退出码；打印它的 mode 决定它值多少。这句是新加的，它把矛盾消掉了。
- `--fidelity-only` 提升 fidelity 是"那个 mode 在问一个问题并对答案计数"，不是
  "一个 note 决定终止运行"。所以提升逻辑住在 `report_qc.py` 的
  `--fidelity-only` 分支里，不住在这里。这句也是新加的。

三段合起来：`die()` 的断言没有削弱，也没有被违反，两句各有各的适用范围。

### 5. `report_qc.py:48` 过时的"four advisories"

实际六个：density、fidelity、fix-lang、fix-mislabel、authz、ext-asset。
`the four advisories -- density, fidelity, fix-lang and fix-mislabel` →
`the six advisories -- density, fidelity, fix-lang, fix-mislabel, authz and
ext-asset`。改的是这一处；同一段里紧跟的 "because plain mode is the structural
pass" 那句仍然成立，没动。

### 6. `report_qc.py:86` 的 "the two lists above"

两份 `__all__` 在 `checks/contract.py` 与 `checks/text.py`，不在 `report_qc.py`
"上面"——本文件上面的是两条星号导入。改为把读者指到正确位置：

```
# takes exactly the names the two __all__ lists -- one in checks/contract.py,
# one in checks/text.py -- spell out, which is why _NEXT_SEC_RE, _flat and
# _claims stay out -- their own modules do not list them, ...
```

（第一版我顺手写了行号 `at its line 21` / `at its line 17`，自己 review 时删掉了：
行号会随任何一次编辑过期，而这个注释的全部意义就是不写出会在文件增长时过期的东西。
`checks/contract.py` 的 `__all__` 因为本任务改了 docstring 已经从 21 挪到 23。）

---

## brief 修正（我改了 brief 的四处，理由）

1. **`C["encoding"]` / `C["mermaid"]` → `.get()` 守卫。** brief 的代码块在契约还是
   1.2.6 时直接抛 `KeyError: 'encoding'`，整个套件死在第 5 个 check 上，一个 FAIL
   都看不到。一个"契约缺键"的失败不该表现为 traceback——那正是这份契约存在的理由
   所反对的东西。改成 `(C.get("encoding") or {}).get(...)`，缺块时它是一条 FAIL。

2. **`encoding.skill_anchor`：`"保存为 UTF-8"` → `"先转成 UTF-8 再跑"`。** brief
   给的锚点在 `SKILL.md` 里不存在。SKILL.md 第 26 行原文是
   `——先转成 UTF-8 再跑；报告同理，编辑器"另存为"默认会落到 cp936。`
   —— 是"另存为"不是"保存为"，而且整串"保存为 UTF-8"一次都没出现（逐字计数 0）。
   用 brief 的锚点会多一条 drift FAIL（"rule enforced but not taught"）。
   `"先转成 UTF-8 再跑"` 在 SKILL.md 里出现 1 次，就是那句教编码要求的话，是这条
   规则真正被教的地方。

3. **`where("mermaid_labels")` → `where("def mermaid_labels(")`。** brief 的探针
   断言 `"mermaid_labels" in where("mermaid_labels")[0]`，而 `where()` 按固定顺序扫
   6 个文件，`report_qc.py` 排第一且它 `import *` 了 checks/text.py 的 `__all__`，
   里面就有 `mermaid_labels`。所以 `where("mermaid_labels")[0]` 恒为
   `"report_qc.py"`，`"mermaid_labels" in "report_qc.py"` 为 False——这条断言会
   **永远 FAIL**。改用 `def mermaid_labels(` 前缀后，结果恰好是
   `["checks/text.py"]`。同理 `def check(` 恰好是 `["checks/structure.py"]`
   （brief 已要求收紧，我照做了）。第三条 `def all_notes(` 恰好是
   `["checks/advisory.py"]`。

4. **`encoding.replacement_char` 写字面 U+FFFD → JSON 转义（反斜杠 + ufffd）。** 见 Step 3。

`checks/fidelity.py` 与 `checks/encoding.py` 按 brief 保留在 `where()` 的扫描名单里，
当前不存在所以被 `os.path.exists` 跳过；1.1.0 后续任务把它们加进来时，这个探针是唯一
会注意到它们落错地方的东西。

---

## 闸门行为未变（Task 5 才开始变）

写了一个 16 用例的矩阵，覆盖三种模式 × 通过/失败/缺参/缺文件/空源/非 md 后缀/
`--fix` 少路径/`-o` 无值等，然后在 `git stash` 前后各跑一次，逐行 `Compare-Object`：

| # | 用例 | 退出码 |
| --- | --- | --- |
| 1 | plain pass | 0 |
| 2 | plain fail | 1 |
| 3 | plain two reports | 1 |
| 4 | plain report+source | 1 |
| 5 | plain no args | 2 |
| 6 | plain two sources | 2 |
| 7 | plain missing report | 2 |
| 8 | plain bad report ext | 2 |
| 9 | fidelity clean | 1 |
| 10 | fidelity dirty | 1 |
| 11 | fidelity no source | 2 |
| 12 | fidelity empty source | 2 |
| 13 | fidelity no report | 2 |
| 14 | fix few paths | 2 |
| 15 | fix no out | 2 |
| 16 | fix run | 1 |

16 个用例，**退出码全部一致，stdout 逐行 diff 只有一处**：

```
=> exit nonzero; the six advisories -- density, fidelity, fix-lang, fix-mislabel,
=> authz and ext-asset -- print as `note` and do not change
<= exit nonzero; the four advisories -- density, fidelity, fix-lang and
<= fix-mislabel -- print as `note` and do not change
```

这一处就是遗留第 5 条的修正，且只出现在 `plain no args` 用例里——那个 mode 打的是
`__doc__`。它是本任务有意改的文案，不是行为变化。

题面点名要的两条单独跑：

```
$ python scripts/report_qc.py references/example-report.md
PASS  example-report.md
  note  no source recognised, so density, fidelity, fix-mislabel, authz and ext-asset were not run (pass the ABAP file after the report)
exit=0

$ python scripts/report_qc.py <已知 FAIL 的报告>
  sec      document  missing section(s): 五
  prow     document  section 五 has no problem rows
  buck     document  section 五 missing priority bucket(s): 🔴 🟠 🟡 🟢
FAIL  t4-fail.md  (3 defect(s))
  note  no source recognised, so density, fidelity, fix-mislabel, authz and ext-asset were not run (pass the ABAP file after the report)
exit=1
```

与加键前逐字节相同。

**为什么加键不改行为**：五个新键没有任何检测器读它们。`checks/contract.py` 只从
契约里 `SEC / LAYERS / BUCKETS / LINE_NUM / FULLWIDTH` 等既有路径取值，新键不在任何
一条取值路径上。这正是本任务与 Task 5 的分界。

---

## 编码

改动的 5 个文件全部 UTF-8、无 BOM、无 CR、无字面 U+FFFD、末尾恰好一个 LF：

```
schemas\report-contract.json       clean
tests\test_contract_drift.py       clean
scripts\checks\contract.py         clean
scripts\checks\advisory.py         clean
scripts\report_qc.py               clean
```

---

## 改了哪些文件

| 文件 | 改了什么 |
| --- | --- |
| `schemas/report-contract.json` | 版本、五个键、`exit_codes["2"]` 两行、`measured`、`release._comment` |
| `tests/test_contract_drift.py` | `load_contract()`、`1.1.0 rule keys` 一节（7 条）、`rule placement` 一节（3 条） |
| `scripts/checks/contract.py` | 模块 docstring 的版本句（遗留 2） |
| `scripts/checks/advisory.py` | 模块 docstring 三段（遗留 3、4） |
| `scripts/report_qc.py` | 模块 docstring 两处（遗留 5、6） |

未动：`SKILL.md`、`checks/structure.py`、`checks/text.py`、`checks/__init__.py`、
`tests/test_skill.py`、`tests/test_gate_enforcement.py`。

## 明确不做（复核）

- C1–C5 的检查逻辑：**未实现**。五个键只是被声明、被 drift 测试读出"存在且开着"。
- `SKILL.md`：**未改**。新 `encoding.skill_anchor` 取的是它已有的原句。
- `check()` 与六个 note 函数的**函数体与 docstring**：未改。改的只有 `advisory.py`
  的**模块** docstring。
- `tests/test_skill.py` / `tests/test_gate_enforcement.py`：未改，165 与 20 保持。
