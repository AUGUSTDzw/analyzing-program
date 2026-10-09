# Task 3 报告：`check()` 进 `structure.py`，note 进 `advisory.py`，notes 收敛为 `all_notes()`

状态：DONE_WITH_CONCERNS（brief 本身有 5 处错误，全部已修正；三个套件计数一个未变）
分支：`feature/gate-enforcement`
基线 commit：`0f35c50`

---

## 1. 结果摘要

| 指标 | 期望 | 实际 |
|---|---|---|
| `test_skill.py` | 165（本任务不许变） | **165** |
| `test_contract_drift.py` | 107（本任务不许变） | **107** |
| `test_gate_enforcement.py` | 20（本任务不许变） | **20** |
| `report_qc.py` 行数 | < 600 | **485**（本任务开始前 802） |
| AST 同名遮蔽 | 0 | **0** |
| 子进程行为差异 | 0 | **0 / 119 次调用逐字节相同** |

产出文件：

- 新增 `skill/analyzing-programs/scripts/checks/structure.py`（91 行）
- 新增 `skill/analyzing-programs/scripts/checks/advisory.py`（302 行）
- 改 `skill/analyzing-programs/scripts/report_qc.py`（802 → 485 行）

`checks/contract.py` 与 `checks/text.py` **未被修改**（Task 2 的文件本任务一个字没动）。

---

## 2. 逐 Step 执行记录

### Step 1：建 `structure.py`，逐字搬入 `check()`

按 brief 建文件，文件头 docstring 与 brief 逐字一致。

**搬运保真用 AST 验证，不靠肉眼**：写了一个脚本，用 `ast.parse` 取出函数定义，从
`def` 行到 `end_lineno` 逐行切出源码文本，与 git `HEAD` 版本的同一函数做字符串全等比较：

```
check()  IDENTICAL
```

函数体一字未改，包括 `A8-cc` / `A8-pt` 那段区分空白的逻辑和两段解释性注释。

`__all__ = ["check"]`，写法和 `text.py` 一样（前面一段说明"为什么必须有，否则
`import *` 会把名字漏回主文件"的注释）。

**bare 名绑定**：所有原来靠星号导入到达的名字，现在由 `structure.py` 顶部 17 个
显式 import 绑定。名字本身是同一批标识符，所以**没有发生任何文本改名**——"改成
import 的名字"在这里就是"由 import 而非星号导入来绑定"。另加 `import re`
（`check()` 里 `re.findall` 那一行需要它，而 `re` 原本是从 `checks/contract.py`
漏进主文件的）。

### Step 2：建 `advisory.py`，逐字搬入六个 note 函数

同样用 AST 逐字比对，六个全部 IDENTICAL：

```
authz_note           IDENTICAL (35 lines)
density_note         IDENTICAL (42 lines)
ext_asset_note       IDENTICAL (30 lines)
fidelity_note        IDENTICAL (42 lines)
fix_lang_note        IDENTICAL (34 lines)
fix_mislabel_note    IDENTICAL (60 lines)
```

`fidelity_note` 本轮留在 advisory（Task 10 再分档），已按 brief 搬入。

`__all__` 列全部 7 个名字（六个 note + `all_notes`）。

### Step 3：`report()` 改用 `all_notes()`

`report()` 与 `--fix` 分支那两份写了两遍的列表，收敛成一处，**输出顺序逐条核对过**。

`all_notes()` 实现按你的补充要求，**按真实签名显式调用，不用 `try/except TypeError`
探测**。真实签名（`inspect.signature` 读出来）：

```
density_note(s, src)        fidelity_note(s, src)     fix_lang_note(s)
fix_mislabel_note(s, src)   authz_note(s, src)        ext_asset_note(s, src)
```

只有 `fix_lang_note` 是单参。

**顺序验证做了两层**：

1. 直接对 `all_notes` 打桩，把六个函数替换成会记录自己被调用的哨兵，断言调用序列
   等于原列表顺序；再验证返回 `None` 的 note 被过滤掉、空 `src=None` 调用形状也一致：

   ```
   original order : [density, fidelity, fix_lang, fix_mislabel, authz, ext_asset]
   all_notes order: [density, fidelity, fix_lang, fix_mislabel, authz, ext_asset]
   src=None order : [density, fidelity, fix_lang, fix_mislabel, authz, ext_asset]
   OK: all_notes reproduces the original order in both call shapes
   ```

2. 端到端：手写一份六个 note **全部触发**的报告 + 源文件（第一版只触发 2 个，
   逐个查了每个 note 的触发条件才凑齐：density 要 7 个 subprogram 对 2 个 block；
   ext_asset 的正则要求 `_LOGO` 前一个字符是 `N`，所以资产名得叫
   `ZIMG_N_LOGO_SMALL`；fix_lang 要 fence 落在 `风险与改进` 层且尾窗三层不全；
   fix_mislabel 的 abap-fix 块必须是源文件里的**连续**行）。然后用 git `HEAD` 版
   老 gate 和新版 gate 各跑一遍，比对 stdout：

   ```
   plain  rc 1->1  IDENTICAL=True
   fix    rc 1->1  IDENTICAL=True
   fid    rc 1->1  IDENTICAL=True
   fixed file byte-identical: True
   ```

   实际打印顺序：density → fidelity → fix_lang → fix_mislabel → authz → ext_asset。

### Step 4：改 `report_qc.py` 的导入

```python
from checks.contract import *          # noqa: F401,F403
from checks.text import *             # noqa: F401,F403
from checks.structure import check                          # noqa: F401
from checks.advisory import (all_notes, authz_note, density_note,  # noqa: F401
                             ext_asset_note, fidelity_note, fix_lang_note,
                             fix_mislabel_note)
```

顺序刻意保持 `contract` → `text` → `structure` → `advisory`：三个套件里有一条用例把
`checks/text.py` 写成语法错误，期望 exit 2。星号导入必须排在前面，坏的 `text.py`
才会**先**于其它模块抛 SyntaxError，被同一个 guard 接到。brief 的顺序也是这样。

### Step 5：跑三个套件

```
165 checks passed, 0 failed
107 drift checks passed, 0 failed
20 checks passed, 0 failed
```

三个数字与本任务开始前的基线**完全一致**。

### Step 6：确认体积

```
report_qc.py lines: 485      (brief 期望 < 600)
```

### Step 7：提交

见文末。

---

## 3. 额外的行为等价证据（brief 没要求，但这是"纯搬家"的唯一硬证据）

三个套件只有 20 / 165 / 107 个断言，覆盖不了"输出顺序一模一样"这件事。所以我在
**动代码之前**先把三个套件里**每一次** `subprocess` 调用都录下来（argv、returncode、
stdout、stderr，共 119 次），改完再录一遍，逐条比对：

```
SUBPROCESS: 119 calls, 0 diffs
```

也就是说 119 次调用里，没有一次的退出码或输出发生过哪怕一个字节的变化。

另外把 `report_qc.py` 整个模块的公开属性名也录了份快照对比：

```
attrs LOST: ['_NEXT_SEC_RE', '_claims', '_flat', 're']   ← 见第 5 节，均为有意清除的死导入
attrs NEW : ['all_notes']
```

---

## 4. 被我修正的 brief 错误

### 错误 1（Step 5）：期望的第一个套件计数是错的

brief 写 `157 checks passed, 0 failed`，实测基线就是 **165**。三个套件计数一个都没动，
是 brief 的数字过期了。已按你给的 165 为准。

### 错误 2（Step 1）：`A8_GAP` 不需要补，已存在

brief 说"`A8_GAP` 与 `LAYER_LABELS` 若 `report_qc.py` 里没有同名常量，就用下面两行补在
`contract.py` 末尾"。实际 `A8_GAP` **Task 2 已经搬进 `contract.py` 第 68 行**，而且已经在
`__all__` 里。再补一遍会造出第二个定义，正是这个代码库通篇在消灭的那类"第二份拷贝"
缺陷。**只 import，没补。**

### 错误 3（Step 1）：`LAYER_LABELS` 是多余的，整条都不做

brief 定义的 `LAYER_LABELS = LAYERS` 是一个别名。但：

- 全仓库 `git grep LAYER_LABELS` 只在 brief 自己里出现，`check()` 用的是 `LAYERS`；
- brief 自己列的"要改成的名字"清单里也没有它。

所以它是纯死代码。而且 `text.py` 特意**没有**把 contract 的名字收进自己的 `__all__`
（注释里写明"它们是 contract 的 `__all__` 成员，不是第二个列表"）。再造一个 `LAYERS`
的第二个名字，恰好违反同一条约定。**没有创建 `LAYER_LABELS`。**

### 错误 4（Step 1 / Step 2）：两处 import 清单都不全，照抄会 NameError

- `structure.py` 的清单漏了 **`TICK` 和 `TAG`**——`check()` 里 `TICK.finditer(...)` 和
  `TAG.sub(...)` 各用一次。漏了就第一行就炸。
- `advisory.py` 的清单漏了 **`LAYERS`**（`fix_lang_note` 的 `all(l in tail for l in LAYERS)`）、
  **`ANCHORS`** 和 **`source_blocks`**（`density_note`）、**`block_head` / `in_risk_layer` /
  `prose_end`**（`fix_lang_note`）、以及 **`re`**（`authz_note` / `ext_asset_note`）。

反过来，清单里列了 `_strip_comment` 和 `anchors_of`——这两个没有任何 note 函数用
（它们是留在主文件的 fixer 用的），已剔除。

两个模块都按"实际引用到什么就 import 什么"落地，并补 `import re`。

### 错误 5（Step 3）：`all_notes` 代码块的顺序是错的，和它自己下一段话矛盾

brief 给的代码块把 `fidelity_note` 放在**最后**（`for (density, fix_lang)` →
`for (fix_mislabel, authz, ext_asset)` → `fidelity`），得到的顺序是
density, fix_lang, fix_mislabel, authz, ext_asset, **fidelity**。
而紧接着那段"注意顺序"明确说必须复现 density, fidelity, fix_lang, … 并要求
"把 `fidelity_note` 挪到 fix_lang 之前"。

**按散文要求实现，不按代码块。** 最终顺序 = density, fidelity, fix_lang,
fix_mislabel, authz, ext_asset，与改动前两份列表完全一致。

### 错误 6（Step 4）：导入清单会让 drift 套件掉数

brief 只让 import `all_notes, fidelity_note`。但 `test_contract_drift.py:232-234` 有：

```python
for fn in ("density_note", "fidelity_note", "fix_lang_note", "fix_mislabel_note", "prose_end"):
    check(hasattr(rq, fn), f"report_qc.{fn} exists for its advisory")
```

照 brief 只 import 两个，`hasattr(rq, "density_note")` 会变 False，
**drift 从 107 掉到 104**。

我最终 import 了**全部六个** note 而不是四个。理由：那个 `hasattr` 检查表达的是
"闸门整体对外暴露每个 advisory"，只按某个测试今天恰好列出的四个来补，会留下一个
任意切口。今天补四个、明天测试加第五个又要改一次导入。把门面做成完整的一个，
理由只写一次，也不给后来人留"这三个为什么在、那两个为什么不在"的疑问。

---

## 5. 我自己做的决定（brief 没写）

### 决定 1：删掉 `report_qc.py` 里四个因搬运而死的导入

搬完之后 pyflakes 报出四个只-import不使用：

| 名字 | 原来为什么在 | 现在 |
|---|---|---|
| `re` | `check()` / `authz_note` / `ext_asset_note` 用 | 全部搬走，主文件再无 `re.` |
| `_NEXT_SEC_RE` | `check()` 用 | 搬到 `structure.py` |
| `_claims` | `fidelity_note` / `fix_mislabel_note` 用 | 搬到 `advisory.py` |
| `_flat` | 同上 | 搬到 `advisory.py` |

这三个下划线导入是 Task 2 特意加的，注释写着"这些在下面按名字被读到"。搬完这句话
**变成假话**了。留着一个自称有理由、实际已经没人用的导入，比删掉更糟——它会骗下一个
读代码的人。

已删，并把注释换成一条仍然成立的提醒（星号导入跳过所有下划线名，以后在这里写检测器
要用 `_flat` 会得到 NameError）。已 `git grep` 确认全仓库没有任何地方引用这四个名字。

### 决定 2：改了一行模块 docstring

原文：`Detectors live in this one file and are shared by both modes on purpose.`
改为：`Detectors live in checks/ and are shared by both modes on purpose.`

这是**本次改动唯一一处用户可见的输出变化**（无参数运行会打印 `__doc__`）。
我把老 gate 和新 gate 的 usage 输出做 `Compare-Object`，57 行里只有这一行不同，
其余完全一致。留着"都住在这一个文件里"是本次任务直接造成的假陈述。
这一段后面的历史说明（检查器和修复器分开导致漂移）原样保留。

### 决定 3：`all_notes` 里没用 `try/except TypeError`

按你的补充要求，签名用 `inspect.signature` 读出来是硬事实（只有 `fix_lang_note`
是单参），直接显式调用。异常探测的写法有三个具体问题：签名写错时会**静默吞掉真正的
TypeError**（note 函数体里任何一处类型错误都会被当成"签名不对"而重试）；重试路径
依赖运行到一半才暴露的事实；而且 `TypeError` 是 note 函数体里最可能真实抛出的异常。
`all_notes` 里只有一处 `fix_lang_note(s)` 是单参调用，肉眼即可核对。

### 决定 4：绝对导入而非相对导入

`text.py` 用的是 `from .contract import`，brief 给的两个新模块头部用的是
`from checks.contract import`。我按 brief 走绝对导入（也与 `report_qc.py` 自身一致）。
两种在当前所有测试下都成立（`importlib.util.spec_from_file_location` 加载主文件时
`checks` 是作为包被导入的，相对导入可用，这一点 Task 2 已经证明了）。
代价是新模块和 `text.py` 在这一点上风格不一致——**记在这里，留给后续任务决定要不要统一**，
本任务不改 `text.py`。

---

## 6. AST 同名遮蔽检查

用 `ast` 遍历 `scripts/` 下每个 `.py` 的**模块级**绑定（import / 赋值 / def / class，
含 `try:`、`if:` 内的绑定），解析各模块的 `__all__`，算出每个星号导入实际会带进
主文件的**确切名字集合**，再与该模块自己绑定的名字求交集。

检查脚本第一版有两个自身缺陷，先修了才让结果有意义，否则"0 冲突"是**空的真**：

1. 两个 `from ... import *` 写在 `try:` 里，第一版只在 `ast.Module.body` 找，
   **两个星号导入一个都没扫到**；
2. 用 `bound["*"]` 存星号导入，两个同名 key 互相覆盖，只剩最后一个。

修好后：

```
report_qc.py pulls in:
   checks.contract: CONTRACT, CONTRACT_PATH, SEC, SEC_RE, LAYERS, A8_GAP, BUCKETS, ROW,
                   DIAGRAM_LANG, FENCE_LANGS, QUOTE_LANG, FIX_LANG, PSEC, PSEC_RE,
                   LINE_NUM, FULLWIDTH, MM_BAD, DENSITY_FLOOR, CITE_NUM, ANCHORS   (20)
   checks.text:     TICK, TAG, FENCE_MARK, mm_violation, NODE, mermaid_labels, inventory,
                   lang_of, fence_spans, fence_defects, blank_fences, anchors_of,
                   anchor_for, block_head, in_risk_layer, PROSE_END, prose_end,
source_blocks, line_of, cite_extent, ELIDE, PAREN_NOTE, CJK,
                    STR_LIT, PUNCT                                                    (25)

== SELF-BOUND vs STAR-IMPORTED (shadowing) ==
report_qc.py           -> no collision

TOTAL SHADOWING COLLISIONS: 0
```

结论：

- **0 处遮蔽。** `report_qc.py` 自己绑定的名字与星号导入进来的 45 个名字**无交集**。
- `contract.__all__`（20）与 `text.__all__`（25）**互不相交**，两个星号导入之间
  也不存在"同名谁先到"的歧义。
- 新增的 `structure.py`（21 个绑定）和 `advisory.py`（23 个绑定）**不是被星号导入的**，
  它们的命名空间不会漏进主文件；两者的 `__all__` 已按 `text.py` 的写法补上，即使将来
  有人改成星号导入，`re` 之类也不会漏出去。
- 你提到的"Task 2 遗留隐患"已确认存在且已收敛：`ANCHORS` / `MM_BAD` / `QUOTE_LANG`
  确实同时出现在 `contract.py` 和 `text.py` 的命名空间里（`text.py` 从 contract 转出
  它们使用），但被 `text.py` 的 `__all__` 挡住，两个 `__all__` 无交集，**不构成遮蔽**。
  本任务没有改动 `text.py`，此项维持 Task 2 的状态。

---

## 7. 遗留观察（不在本任务范围，未改）

1. `report_qc.py` 模块 docstring 里有一处 "the four advisories" 的说法（`:48`），
   而实际有六个 note；另一处 "the four things"（`:58`）经复核指的是**四个优先级桶**，
   是准确的。**已复核拆开，详见文末遗留清单第 9 条**——本条保留 Task 3 当时的
   原始判断（当时两处都未复核，一律按可疑处理），不追改历史结论。
2. `structure.py` / `advisory.py` 用绝对导入、`text.py` 用相对导入（见决定 4）。

---

## 8. 提交

只暂存 `skill/analyzing-programs/scripts/`，未包含 `.superpowers/`（含本报告）。

---

## 修复轮 1

基线 commit：`a6a6a2a`。两条 Important 两条 Minor（4、7）已改，四条 Minor
（3、5、6、8）本轮明确不做，见文末遗留清单。

### Important 1：两个新文件补末尾换行

改动前后实测（`bytes.endswith(b"\n")`，并回扫末尾连续 LF 个数）：

| 文件 | 改前 endsWithLF | 改后 endsWithLF | 末尾连续 LF |
|---|---|---|---|
| `checks/structure.py` | **False** | **True** | 1 |
| `checks/advisory.py` | **False** | **True** | 1 |

各追加一个字节 `0x0A`（`structure.py` 3712 → 3713 字节，`advisory.py`
13897 → 13898 字节）。追加前断言过 `not b.endswith(b"\n\n")`，所以补的是
**终止最后一行**的一个 LF，不是多出一个空行——两个文件末行分别是
`    return bad` 与 `    return out`。

`git diff` 里两处 `\ No newline at end of file` 标记随之消失。

### Important 2：`all_notes()` docstring 只说真话

原 docstring（`advisory.py` 第 277–283 行）写的这段是**假的**：

> report() and the --fix branch each built this list by hand, in two different
> orders. They drifted once already: --fix prints them before the verdict,
> report() after.

三处不实：两个调用点的顺序**相同**（都是 density, fidelity, fix_lang,
fix_mislabel, authz, ext_asset）；`--fix` 的 note 印在 PASS/FAIL 那一行**之后**
（`report_qc.py` 的 fix 分支，verdict 先出、note 后出），不是之前；"drifted
once already" 是一次没有发生过的 diff。

改写后（现第 277–287 行）只陈述三件可验证的事：两处调用点各自手写同一份列表、
现在只有一处定义；这个顺序就是两个模式打印的顺序，改它会改变 gate 在 plain 模式
和 `--fix` 下的输出；**没有任何套件钉住这个顺序**。

最后一句是本轮实测出来的，不是推测。把 `all_notes()` 里的六个 note 调用顺序
**整个反过来**（`ext_asset, authz, fix_mislabel, fix_lang, fidelity, density`），
三个套件依然全绿：

```
=== mutation probe: test_skill.py ===            165 checks passed, 0 failed
=== mutation probe: test_contract_drift.py ===   107 drift checks passed, 0 failed
=== mutation probe: test_gate_enforcement.py ===  20 checks passed, 0 failed
```

探针改完已还原，`all_notes` 的调用顺序与 `a6a6a2a` 一致。

**这里与 brief 的一处出入，需要点明**：brief 要求 docstring 写"而**有测试在盯着
输出**"。上面的实测证明这句话为假——`all_notes` 在三个套件里出现 **0 次**
（`git grep all_notes tests/` 无结果），六个 note 函数只被 `hasattr` 检查
存在性（`test_contract_drift.py:232,238`），没有任何一条断言顺序。若照 brief
原话写，就等于在一个专门清理"会骗人的注释"的修复轮里**新写一条骗人的注释**，
与本仓库刚定的标准（决定 1）直接冲突。**故按事实写，不按 brief 措辞写**，
并把"顺序无测试保护"作为 Minor 8 记入遗留清单。此出入请人工复核。

### Minor 4：`# noqa` 标注对齐事实

用 `ast` 取模块体内全部 `ast.Name`（`Load` 上下文）与显式导入名求差集，得到
ground truth；再用 `pyflakes` 独立复核，两者一致：

| 名字 | 模块体引用 | 改前标注 | 判定 |
|---|---|---|---|
| `check` | **用了**（`report()` 与 fix 分支各一次） | `# noqa: F401` | 标注断言了一件假事 |
| `all_notes` | 用了 | 被括号语句整体静音 | 同上 |
| `fidelity_note` | 用了（`--fidelity-only`） | 被括号语句整体静音 | 同上 |
| `authz_note` / `density_note` / `ext_asset_note` / `fix_lang_note` / `fix_mislabel_note` | 未用 | — | 标注正确 |

改法：

1. `report_qc.py:84` 去掉 `# noqa: F401`。`check` 是被调用的，F401 根本不会触发，
   标注纯属虚构。
2. advisory 的括号导入**调整顺序**，让五个真正未使用的名字排在前面，`all_notes`
   与 `fidelity_note` 落到后面。理由是 pyflakes 把整条 `ImportFrom` 的五个 F401
   **全部报在语句首行**（改后为 `report_qc.py:101`，五处都是 `101:5`），所以标记
   只能落在那一行才有效；而那一行现在只装着未使用的名字，标记所断言的内容与事实
   一致。原来 `all_notes` 排在第一个，标记读起来就是在说它未被使用。

   ```python
   from checks.advisory import (authz_note, density_note, ext_asset_note,  # noqa: F401
                                fix_lang_note, fix_mislabel_note, all_notes,
                                fidelity_note)
   ```

3. 上方注释补三行，说明这个顺序不是随手排的（否则下一个人会"顺手整理"回去）。

导入顺序在单条 `from ... import (...)` 内不产生任何绑定差异，三个套件已证。

### Minor 7：报告里的行数

第 1 节 `advisory.py` 204 → **302**，`structure.py` 61 → **91**。

`advisory.py` 在本轮开始时实测 **298** 行；Important 2 的 docstring 从 6 行正文
改成 10 行，净增 4 行，故提交时为 **302**。302 是提交时的真实行数——把 298 写进
报告会重犯本条 Minor 本身的错。

`report_qc.py` 本轮由 485 增至 **487**（Minor 4 新增 3 行注释）。第 1 节的 485 是
Task 3 当时的交付数字，保留为历史记录，当前值以本节为准。

### 三个套件实测计数

```
165 checks passed, 0 failed        # test_skill.py
107 drift checks passed, 0 failed  # test_contract_drift.py
20 checks passed, 0 failed         # test_gate_enforcement.py
```

与基线完全一致，本轮未加任何测试。

### 编码实测

```
file                 endsWithLF  trailingLF  CR  BOM    U+FFFD  utf8_ok  lines
structure.py         True        1           0   False  False   True     91
advisory.py          True        1           0   False  False   True     302
report_qc.py         True        1           0   False  False   True     487
```

末尾恰好一个 LF、无 CR、无 BOM、无字面 U+FFFD、均为合法 UTF-8。

### 未动的部分

`check()` 与六个 note 函数的**函数体与 docstring 一字未改**——用 `ast` 切出
`def` 到 `end_lineno` 的源码文本，与 `HEAD` 逐字全等比较：

```
check                IDENTICAL  (66 lines)
density_note         IDENTICAL  (42 lines)
fidelity_note        IDENTICAL  (42 lines)
fix_lang_note        IDENTICAL  (34 lines)
fix_mislabel_note    IDENTICAL  (60 lines)
authz_note           IDENTICAL  (35 lines)
ext_asset_note       IDENTICAL  (30 lines)
all_notes (code only) IDENTICAL
```

`all_notes` 只换了 docstring，代码逐字未动。`schemas/report-contract.json`、
`SKILL.md`、`checks/contract.py`、`checks/text.py` 本轮均未触碰。

---

## 遗留清单

本节五条里 3、5、8 是技术债，9 已复核为**准确**（不是缺陷），6 已获批追认并关闭。

### 3. 五个 note 导入只为测试的 `hasattr` 而存在

`report_qc.py` 从 `checks.advisory` 导入 `authz_note`、`density_note`、
`ext_asset_note`、`fix_lang_note`、`fix_mislabel_note`，但**模块体内一次都没
引用**（本轮用 `ast` 复核，五个 `used=False`）。它们存在的唯一理由是
`test_contract_drift.py:232` 的 `hasattr(rq, fn)` 检查——闸门模块把**生产导入面
交给了一个测试的属性列表来塑形**。

这意味着加一个 advisory 要同时改三处：`advisory.__all__`、本文件的导入、以及那个
测试的元组；而三者本可以由一处决定。Task 3 的报告（决定 6 / 第 4 节错误 6）记录了
当时的取舍：只按测试今天列出的名字导入会留下任意切口，所以选择把门面做全。这在当时
是合理的，但**根因没被消除**。

**留给**：Task 4 定下 advisory 的对外 API 之后。届时应把"闸门对外暴露哪些
advisory"变成一处声明，而不是由测试反向决定。

### 5. 绝对导入与相对导入不一致

`structure.py` / `advisory.py` 用 `from checks.contract import ...`（绝对），
`text.py` 用 `from .contract import ...`（相对）。两种在当前所有测试下都成立，
但同一个包内混用两种风格，下一个人不知道该抄哪一种。

已披露（Task 3 决定 4），**有意推迟**。**留给**：统一 `checks/` 包导入风格的任务。
统一时需确认不会破坏 `test_gate_enforcement.py` 里那条"把 `text.py` 写成语法错误、
期望 exit 2"的用例——相对/绝对导入在 SyntaxError 的触发时机上表现一致，但需要实测。

### 6. 【已关闭 — 已获批追认】`report_qc.py` 模块 docstring 的一行改动

Task 3 决定 2 改了 `report_qc.py:31`：

- 原文：`Detectors live in this one file and are shared by both modes on purpose.`
- 改为：`Detectors live in checks/ and are shared by both modes on purpose.`

**这是本任务造成的唯一一处用户可见输出变化**——无参数运行会打印模块 `__doc__`。
而"用户可见输出必须不变"当初是绝对表述，不是"除这一处外"。批准理由：拆分
`checks/` 之后，"都住在这一个文件里"这个陈述**因本任务而变假**；留着一个假陈述
比改一个词的输出更糟。

**状态：已由用户批准追认，本条关闭。**（批准理由即上述"宁可改输出也不留假陈述"。）

Task 3 当时的证据仍然有效：老 gate 与新 gate 的 usage 输出做 `Compare-Object`，
57 行里只有这一行不同。

**仍未复核的是同一段 docstring 里的 "the four things" / "the four advisories"
两个数字**——那不属于本条，属于第 9 条，两处已分别得出结论。

### 8. `all_notes()` 的顺序没有任何测试钉住

这次重构的全部价值就是"一处定义、一个顺序"，但**没有一个断言保护这个顺序**。
本轮已实测坐实：把 `all_notes()` 的六个 note 调用顺序整个反过来，三个套件依然
**165 / 107 / 20** 全绿（探针输出见 Important 2 小节）。

后果很具体：Task 3 的实现者不得不**手工搭探针**（打桩记录调用序列 + 端到端造一份
六个 note 全部触发的报告）才能验证顺序——本该由测试承担的成本，落在了人的身上。

**本轮不加测试**，因为加测试会动三个套件的冻结计数（165 / 107 / 20）。

**留给**：后续**第一个**碰到 `all_notes()` 的任务。那次应补一条断言调用序列的测试
（打桩记录调用顺序并与期望列表比对是最省事的写法，不依赖任何具体报告内容）。在它
落地之前，docstring 里那句 "No suite pins it" 是提醒后来者唯一的护栏。

### 9. 【已复核 — 结论：不是缺陷】`report_qc.py` 模块 docstring 里的 "the four things"

同一段 docstring 里有两处数量词。**本轮逐条核对，结论不同**，所以拆开记：

#### 9a. `report_qc.py:58` "the bucket check, one of the four things this gate exists to do"

> ...the crash replaced the diagnosis with a traceback and the bucket check, one
> of the four things this gate exists to do, was unreachable on that platform.

**结论：准确，不是缺陷。** "the four things" 数的是**检查对象**——第五节的四个优先级
桶，不是 advisory。依据（实测）：

| 事实 | 实测值 |
|---|---|
| `report-contract.json` 的 `problem_section.buckets` | **4**：`🔴 🟠 🟡 🟢` |
| `checks/contract.py` 的 `BUCKETS` | `('🔴', '🟠', '🟡', '🟢')` |
| `checks/structure.py:87-90` | `miss_b = [b for b in BUCKETS if b not in sec5]` → kind 为 `buck` |

即 `check()` 产出的 `buck` 这一 kind，字面就是"检查第五节四个桶名是否齐全"，
正是这句话所指的那一项。数字对得上。

**本轮不改 `report_qc.py:58`**——它没有说错任何事，改它反而是为了改而改。

#### 9b. `report_qc.py:48` "the four advisories -- density, fidelity, fix-lang and fix-mislabel"

**结论：已复核，确认过时。** 这一处数的是 **advisory**，而 advisory 实际是**六个**：
`density, fidelity, fix-lang, authz, ext-asset, fix-mislabel`（契约
`advisories` 六个键，`advisory.__all__` 七个名字 = 六个 note + `all_notes`）。
原文漏了 `authz` 与 `ext-asset`。

**本轮同样不改 `report_qc.py:48` 本身**（本轮不动产品代码），**交给下一个碰这段
docstring 的人**：那时改这一处是改输出，需与第 6 条走同一套"显式交给用户追认"的
流程；9a 那处不必跟着改。第 7 节遗留观察 1 已同步指向本条。

---

## 修复轮 2

1 个 Important + 3 个 Minor，全部只改注释/docstring，**未动任何函数体**，未加测试。

本轮的问题不是新写错了什么，而是上一轮定的原则——**会骗人的注释比没有注释更糟**——
在同一个文件里只被应用了一半。上一轮刚在 `all_notes()` 的 docstring 上判了"编造历史"，
这一轮就发现同一模块的模块头 docstring 里还留着三句从 brief 逐字抄来的、与文件内容
相反的陈述。

### Important — `advisory.py` 模块 docstring 的三处假陈述

`skill/analyzing-programs/scripts/checks/advisory.py:1-17`（原 `:1-7`）。
原文本：

```
"""Advisories: things worth reading, never reasons to fail a run.

`die()`'s docstring says it: labelling a fatal error as a note let a caller that
greps for advisories collect hard failures as soft ones. Everything in this
module prints and returns a string or None; none of it changes an exit code.
That is why 1.1.0 had to move fidelity OUT of this module to give it teeth.
"""
```

三处假话与各自的新陈述：

| # | 原陈述（假） | 实测反证 | 新陈述 |
|---|---|---|---|
| 1 | `That is why 1.1.0 had to move fidelity OUT of this module to give it teeth.` | `fidelity_note` 就定义在 `advisory.py:244`，并且在 `__all__`（`:29-30`）里 | `That mode is not fidelity having teeth. What 1.1.0 intends, and what Task 10 does, is splitting the note in two: PUNCT-ONLY stays advisory, SUBSTANTIVE gets counted in plain mode's exit code.`（`:12-14`）——**明确写成"尚未做"，并指名它落在 Task 10** |
| 2 | 标题行 `never reasons to fail a run` + `none of it changes an exit code` | `report_qc.py:375-378`：`--fidelity-only` 单独裁定 `fidelity_note`，打印 FAIL 后 `rc = 1` | 标题改为 `things worth reading, and the one mode where one of them fails`；正文 `Five of the six are advisory wherever the gate runs. fidelity_note is the exception: --fidelity-only adjudicates it alone and promotes it to a failure, exiting 1.`（`:8-9`） |
| 3 | `Everything in this module prints and returns a string or None` | 六个 note 函数确实只 return 字符串/None 且不 print，但 `all_notes`（`:288`）返回 **list**；"Everything ... is" 是全称命题，一处不成立即假 | `The six note functions here each return a string or None, and none of them prints; all_notes() returns a list of whichever fired, and is the only thing here that returns a list.`（`:4-6`）——把全称拆成"六个 note 函数"与"`all_notes`"两句 |

**为什么第 2 条比措辞严重**：具体危害是维护者读到"fidelity 已经有牙齿了"就跳过
Task 10，而 Task 10 正是那件事。新陈述末句把这个洞写死在原地：
`Until that lands, a report that invented an ABAP statement prints "Check whether the
report rewrote the source" and still passes the structural pass.`（`:14-16`）。

**没动的部分**：`die()` 那段引文原样保留（`report_qc.py:320-322` 的 docstring 本身
正确，它说的是 die 不是 note）；`check()` 与六个 note 函数的函数体与 docstring 一律
未动。`fidelity_note` 自己的 docstring（`:244-260`）里"Reported, not enforced"那句
也未动——它描述的是**plain mode** 的事实，仍然成立，且 Task 10 才会改它。

**新陈述的事实核验**（全部实测，不是推断）：

- `all_notes` 返回 list：`type(all_notes('# a', None))` → `<class 'list'>`。
- 六个 note 函数不 print：逐个读完 `:22-286`，函数体只有 `re` 匹配与 return，无 print 调用。
- `--fidelity-only` 退 1：`test_gate_enforcement.py:97-98` 的 PROBE 1 已钉住 `rc == 1`，本轮 20/20 绿；调用点在 `report_qc.py:371-378`。
- plain mode 仍打 note 且退 0：`report_qc.py:259-261` 对每个 note 打 `  note  {n}` 后 `return 0`；PROBE 1 的 `rc == 0` 断言（`:87`）同样绿。
- 引文逐字：`fidelity_note` 返回串含 `Check whether the report rewrote the source.`（`:285`），新 docstring 引的就是它。

### Minor 2 — `report_qc.py:97-101`，"从它加载的模块上读取它们"收紧到事实

原句把"导入全部六个"的理由说成 `test_contract_drift.py` 会逐个读它们。这对**四个**
成立，不是全部六个：`test_contract_drift.py:232-234`（`hasattr` 存在性）与 `:238-241`
（"被调用而非仅被定义"）两个元组里都只有 `density_note`、`fidelity_note`、
`fix_lang_note`、`fix_mislabel_note`；`authz_note` 与 `ext_asset_note` 不在任何元组里。

改为：

```
# surface: test_contract_drift.py reads four of the six off the module it
# loads, and an advisory the gate can no longer reach by name is the drift
# that suite exists to catch. authz_note and ext_asset_note are in none of
# its tuples; naming all six keeps the surface uniform rather than
# importing only the ones a given test happens to list today.
```

前一句把数量说准，后一句把"为它们 import 纯粹是门面一致性"这个**真实**理由从
被夸大的位置挪到它自己的句子里。导入清单本身（`:105-107`）与 `# noqa: F401` 标注
一个字节都没动。

### Minor 3 — `report_qc.py:85-91`，换掉不成立的理由

原句：`# \`import *\` skips every underscore-prefixed name and nothing below needs one.`
理由不成立——下划线跳过是**没有 `__all__` 时**的默认规则，而 `contract.py` 与
`text.py` 都定义了 `__all__`：

```
$ python -c "..."
contract __all__: 20 has _NEXT_SEC_RE: False
text __all__: 25 has _flat/_claims/_past_line/_strip_comment: []
```

`__all__` 一旦存在就**整体替换**默认规则，与名字是否带下划线无关。`_NEXT_SEC_RE`、
`_flat`、`_claims` 进不来，是因为那两份清单没列它们。改为：

```
# __all__ replaces the default rule rather than modifying it: `import *`
# takes exactly the names the two lists above spell out, which is why
# _NEXT_SEC_RE, _flat and _claims stay out -- their own modules do not list
# them, not because they begin with an underscore. Worth knowing before
# someone adds one: a detector written here that reached for _flat or
# _claims would resolve neither, and say so with a NameError at the first
# call rather than at import.
```

读者真正需要的理由是**"清单是白名单，加名字要改清单"**——这才是他能据此行动的那句。
末句 "a detector ... gets a NameError" 审查确认正确，原样保留（只是重排了折行）。

### Minor 4 — `advisory.py:26`，`__all__` 注释补上 `all_notes`

原句说 `check()` 和"这些 advisory"是闸门唯一重新导出的东西，但 `__all__` 里还有
`all_notes`。改为 `check() and these advisories and all_notes() must be the only
things the gate re-exports`，同段的"explicit list 把意外到达的名字变成 import 期的
NameError"理由不变。

### 三个套件的实际计数

改动前后各跑一次，**均为 165 / 107 / 20，无变化**（本轮未加测试，计数本就不该动）：

```
$ python tests/test_skill.py
165 checks passed, 0 failed

$ python tests/test_contract_drift.py
107 drift checks passed, 0 failed

$ python tests/test_gate_enforcement.py
20 checks passed, 0 failed
```

（workdir：`skill/analyzing-programs`）

### 编码实测值

```
skill/analyzing-programs/scripts/checks/advisory.py
  bytes 14663  CR: 0  BOM: False  U+FFFD: 0  ends with exactly one LF: True  maxlen 127 over88: 1
skill/analyzing-programs/scripts/report_qc.py
  bytes 22207  CR: 0  BOM: False  U+FFFD: 0  ends with exactly one LF: True  maxlen 88 over88: 0
```

`advisory.py` 唯一超 88 列的一行是 `:226` 的 `ext_asset_note` 正则，本轮未触碰，
改动前就是 127。`report_qc.py` 全文件仍 ≤88 列。

### 遗留清单

5 条：3、5、6、8、9。清单抬头已按第 6 条的关闭同步。

**关于 brief 里的 `text.__all__` 数字**：brief 写的是 **26**，实测是 **25**
（7+7+7+4 组 = 25；`contract.__all__` 20 个，两处合计 45）。**26 是笔误**，
Task 3 的 commit 内容未受它影响（`structure.py` / `advisory.py` 的导入与 `__all__`
都是照实际引用写的，没有按 26 拼装过清单）。第 6 节正文里两处引用了这个数字，
已改为 25。
