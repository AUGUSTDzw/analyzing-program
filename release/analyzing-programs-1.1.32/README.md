# analyzing-programs

给 ABAP/SAP 源码生成结构化中文分析报告：固定六节结构，每个引用源码的代码块后面
跟三层（做什么 / 为什么 / 风险与改进），问题按 P0–P3 分桶。

## 目录

```
SKILL.md                         规则本体（587 行）
scripts/report_qc.py             格式闸门：逐条列出违规位置，可自动修两类
scripts/evaluate.py              内容评分：对冻结缺陷清单判分，算召回与错误论断
scripts/docgen.py                文档生成：源码抽成类 / FORM / 函数 / 表 / 调用的清单
scripts/recon.py                 侦察：一次调用拿到编号源码与子程序清单（分析第 1、2 步）
scripts/abap_deps_analyzer.py    依赖分析：对照自带的 abaplint-deps 查标准对象引用
scripts/checks/                  闸门检测器：结构 / 文本 / 编码 / 忠实度 / 令牌 / 引文 / 建议
scripts/lint_skill.py            元工具：SKILL.md 对照 skill-contract.json 检查（见下节）
scripts/dedup.py                 元工具：语义重复章节检测
scripts/lift.py                  元工具：两份 verdict 的 recall 差异与符号检验
scripts/security_probe.py        元工具：17 组对抗输入压测 --fix
scripts/index.py                 元工具：references/ 的 TF-IDF 搜索索引
scripts/evolve.py                元工具：历史报告 P0-P3 模式挖掘与更新建议
references/example-report.md     完整范例（真实报告，逐字未改，闸门零缺陷）
references/abap-syntax/          ABAP 语法与语义速查，9 份
references/large-inputs.md       大输入的实测行为（观察，不是规则）
references/README.md             范例的出处与局限
references/delivery-methods.md   失败模式记录（观察，不是规则）
references/output-rate.md        失败模式记录（观察，不是规则）
references/slice-and-write.md    失败模式记录（观察，不是规则）
references/truncated-reports.md  失败模式记录（观察，不是规则）
evals/README.md                  缺陷参考的格式、用法与边界
evals/*.defects.json             127 条缺陷 / 7 个真实源码
schemas/report-contract.json     报告闸门规则与 skill 教学锚点的唯一来源
schemas/docgen-contract.json     docgen 输出与校验的规则
schemas/skill-contract.json      SKILL.md 自身的规则，lint_skill.py 读它
abaplint-deps/                   自带的标准库桩，依赖分析器读它
tests/*.py                       仓库内的验证套件，10 个，**不随包发布**（见「跑一遍」）
```

## 三件工具各管什么

| 工具 | 回答 | 答不了 |
|---|---|---|
| `report_qc.py` | 形状对不对：六节、三层、四桶、无行号、Mermaid 可渲染、密度 | 分析是否正确、漏没漏 |
| `evaluate.py` | 对着冻结清单，报告漏了几条、有几条错误论断 | 判分本身对不对 |
| `recon.py` | 源码长什么样：编号源码 + 子程序清单，一次调用拿到 | 分析是否正确、闸门是否通过 |
| `tests/test_skill.py` | 上面两个还灵不灵，尤其是**拒绝**路径与退出码 | — |
| `tests/test_contract_drift.py` | 契约里的每条规则 SKILL.md 教了没有，反之亦然 | — |
| `tests/test_gate_enforcement.py` | 闸门放过的报告逐条复现，先记录现状再断言应有的行为 | — |
| `tests/test_fidelity_tiers.py` | 新旧分类口径是否等价：不泄漏、不误伤 | — |
| `tests/test_docgen_deps.py` | docgen 与依赖分析器的解析器、锚点与命令行是否还灵 | — |
| `tests/test_lint_skill.py` | SKILL.md 是否符合 skill-contract.json 规范 | — |
| `tests/test_dedup.py` | SKILL.md 里有没有语义重复的章节 | — |
| `tests/test_lift.py` | 两份 verdict 的 recall 差异是否显著 | — |
| `tests/test_index.py` | references/ 搜索索引构建与检索是否正确 | — |
| `tests/test_evolve.py` | 历史报告 P0-P3 模式挖掘与 SKILL.md 建议是否合理 | — |

**判分是模型工作。** `evaluate.py` 的 `tasks` 子命令把问题打印出来让判分者逐条回答，
`score` 与 `compare` 是确定性的。它保证参考完整、聚合正确、缺项不能冒充完整；
它不保证判分是对的。

## 元工具（Meta Tools）

这些工具不用于写报告，而是用于**维护 skill 本身**。在修改 SKILL.md、审查报告质量、
或评估 skill 效果时运行。

| 工具 | 回答 | 退出码 |
|---|---|---|
| `scripts/lint_skill.py` | SKILL.md 是否符合 `schemas/skill-contract.json` 规范 | `0` 通过，`1` 有缺陷，`2` 拒绝 |
| `scripts/dedup.py` | markdown 文件里有没有语义重复的章节 | `0` 无重复，`1` 有重复，`2` 拒绝 |
| `scripts/lift.py` | 两份 verdict 的 recall 差异是否显著 | `0` 报告完成，`2` 拒绝 |
| `scripts/security_probe.py` | `report_qc.py --fix` 能不能扛住 17 组对抗输入 | `0` 全部通过，`1` 有失败，`2` 拒绝 |
| `scripts/index.py` | references/ 里哪份文件跟查询最相关 | `0` 成功，`2` 拒绝 |
| `scripts/evolve.py` | 历史报告里 P0-P3 有什么模式，SKILL.md 该怎么改 | `0` 完成，`2` 拒绝 |

这些工具是 tier-1（结构检查）、tier-2（语义去重）、tier-3（行为测量）三层评估模型
的实现。完整模型见 [NVIDIA/SkillEvaluator](https://github.com/NVIDIA/SkillEvaluator)。

## 跑一遍

包里的东西，装到哪儿都能跑：

```bash
python scripts/report_qc.py REPORT SOURCE                # 格式；报告须 .md/.markdown，其余当源码
python scripts/report_qc.py --fix REPORT SOURCE -o OUT   # 格式 + 自动修两类
python scripts/recon.py SOURCE [-o OUTDIR]              # 侦察：编号源码 + 子程序清单
python scripts/evaluate.py tasks  --defects evals/zcl_fi_toolkit.defects.json
python scripts/evaluate.py score --defects D.json --verdicts MY.json
python scripts/evaluate.py compare --defects D.json --a V1.json --b V2.json
```

元工具（可选，用于维护 skill）：

```bash
python scripts/lint_skill.py SKILL.md                   # 检查 SKILL.md 规范
python scripts/dedup.py SKILL.md                        # 检测重复章节
python scripts/lift.py --defects D.json --with-skill W.json --without-skill B.json
python scripts/security_probe.py --verbose              # 安全探针
python scripts/index.py build references/               # 构建搜索索引
python scripts/index.py query references/index.json QUERY
python scripts/evolve.py --results Test-result/         # 挖掘历史报告
```

`score` / `compare` 上还有一个 `--legacy`：豁免**整个引文校验**，给早于引文要求的旧判分文件用。不带它，`yes` / `partial` 的判分必须有 `evidence.<id>.report_line`、`evidence.<id>.quote`，而且 quote 得真的出现在那一行——缺 `report_line`、缺 `quote`、行号越界、quote 不在该行，四种都退 `2` 拒绝，而且 `--report` 缺失时同样拒绝（否则等于把校验静默接受下来）。**它不豁免 `false_claims`**：理由缺失照样拒，因为一个吞掉它的出口会把未解释的错误计成干净结果。带它时判分照做、仍退 `0`，但 `WARNING  --legacy: citations were not verified, so every verdict is an uncheckable assertion` 会印在输出里——打上这个警告的分数不算可审计的。

验证套件在仓库里跑。`tests/` 不随包发布，安装包里没有这十个文件：

```bash
python tests/test_skill.py              # 416 项
python tests/test_contract_drift.py     # 138 项，契约 <-> SKILL.md <-> 闸门 三方对齐
python tests/test_gate_enforcement.py   # 41 项，闸门执行漏洞探针
python tests/test_fidelity_tiers.py     # 9 项，改动前后口径是否等价
python tests/test_docgen_deps.py        # 171 项，docgen 与依赖分析器
python tests/test_lint_skill.py         # 41 项，SKILL.md 对照 skill-contract.json
python tests/test_dedup.py              # 33 项，语义重复章节
python tests/test_lift.py               # 35 项，两份 verdict 的 recall 差异与符号检验
python tests/test_index.py              # 37 项，references/ 搜索索引构建与检索
python tests/test_evolve.py             # 25 项，历史报告 P0-P3 模式挖掘与更新建议
```

合计 946 项，十个套件。仓库根还有一个 `run_tests.py`（不随包发布，和
`package_release.py` 一起只活在仓库里）：它逐个跑这十个套件加两个元脚本
（`lint_skill.py`、`security_probe.py`），解析每个套件自己印的那行
`N checks passed, M failed` 汇总成真实总数——汇总数不是猜的。`lint_skill.py`
只印 `PASS` 不带数，它会被标成 unverified 而不是算绿；`security_probe.py`
是 17 项。所以全部跑完是 12 个套件、963 项带数断言。

**退出码是契约的一部分。** 所有模式在仍有缺陷时返回非零，包括 `--fidelity-only`
与 `--fix` —— SKILL.md 第 6 步让模型"重跑到干净为止"，那条循环只能靠退出码终止。
十一个脚本都自己把 stdout 与 stderr 重配为 UTF-8：契约里的优先级桶标记是 emoji，
在 cp936（中文 Windows 的默认）上打印会抛 `UnicodeEncodeError`，
依赖分析器的报告整篇是中文、在 cp437 上同样会抛。1.1.26 之前这个 guard
只覆盖其中三个，漏掉的那两个见下面的 `1.1.25 → 1.1.26` 那条。
Windows 上不需要设 `PYTHONUTF8`。

**为什么 `tests/` 不进包。** 每个 suite 都用
`HERE = dirname(abspath(__file__))` 往上数出仓库根，再去根下找同级的
`Test-source/` 与 `analyzing-programs-workspace/`——那两棵树明确不随 skill 发布
（`analyzing-programs-workspace/` 是上游开发线快照）。所以放进包里只会得到一个
跑不起来的东西：装到 `~/.agents/skills/` 之后四个 suite 会在第一个 fixture 上
`FileNotFoundError`（`test_gate_enforcement.py`、`test_fidelity_tiers.py`、
`test_docgen_deps.py` 要 `Test-source/` 或 `analyzing-programs-workspace/`），
`test_skill.py` 与 `test_contract_drift.py` 能一路跑到最后、各只挂一条
（挂的是 `the exemplar's source is present`，它需要 `Test-source/real/` 里那份
`zbc_show_error_log`）。在仓库里跑是绿的，因为往上数层恰好能走到真的仓库根——
量要装到仓库外才量得出来。
1.1.10 是把这句话写进 README；1.1.11 是直接不把它发出去——包里剩下的每件东西
都能在装好的位置跑通，这句话才成立。仓库根的 `package_release.py` 里有一个
`NOT_SHIPPED` 名单加一条 `CRITICAL` 守卫，后者保证误把 `schemas/` / `scripts/` /
`references/` / `evals/` 填进排除名单时打包会直接断言失败，而不是悄悄少发；
`--verify` 还会拿一份**不**经过 `NOT_SHIPPED` 过滤的遍历去核对已发的包，
否则一个被污染的包在过滤后的视图里显得自洽，检查永远不触发。
这条守卫 1.1.28 那次重写打包器时丢掉过一次：1.1.29 把十个测试文件连同整个 harness
发进了包，`--verify` 在 461 个条目上照报 clean——两个方向都用的同一个已丢的排除。
1.1.30 把它补回，并给 `--verify` 加上 repository-only 检查，所以现在能拦。
1.1.29 本身没修：`release/` 是 append-only，它记的 digest 对得上它自己那个带
harness 的 zip。`references/README.md` 与 `evals/README.md` 里有两处指向 `tests/`
的交叉引用，那是指向仓库内的套件，读发布包的人找不到很正常，不删。

**四种「没检查」的样子，其中一种仍然和通过只差一行 note。** 下表全部实测，
SKILL.md「闸门输出」一节照抄：

| 情况 | 实际输出 | 退出码 |
|---|---|---|
| 形状模式不传源码 | `PASS <报告名>` + `note  no source recognised, so density, fidelity, fix-mislabel, authz, ext-asset and row-src were not run (pass the ABAP file after the report)` | `0` |
| 源码路径不存在 | `error no such source: ...`，一个字都没查 | `2` |
| 报告路径不存在 | `error no such report: ...` | `2` |
| 给了多于一个源码 | `error more than one source: ...`（不是静默取最后一个） | `2` |
| 报告存成非 `.md` / `.markdown` | `error no report path: ...` —— 闸门认为你没给报告 | `2` |

所以：形状检查的 `0` 只能读作「形状对」，**看到那条 skip note 就等于五项诊断外加 `row-src` 没跑**
（六项诊断里只有 `fix-lang` 不需要源码；`row-src` 是强制项，也一起跳过）。
这一版的闸门在源码路径写错时会**拒绝运行**而不是打印 PASS —— 上一版不是那样的，
上一版会照跑、照打印 `PASS`、零 note。这三条语义已经改过两轮，
全部记在 `schemas/report-contract.json` 里，闸门行为集中在 `gate_io` 段
（该段 4 个锚点，契约合计 23 个），
`test_contract_drift.py` 逐条查它们在不在 SKILL.md 里。

自动修只做两类改不动的判断：位置标签写成行号 → 改成最近的前置构造名；
Mermaid 标签里的裸 `<` `>` `#` → 改成全角。三层缺失**只报位置不修**，
因为那需要判断后面的散文本该属于哪一层，猜错会把风险论述标成"做什么"。

## 两条实测边界

- **20 条缺陷的配对比较分辨不出小效应。** 低于约 30 个百分点记作**未测量**。
  同一个 skill 同一文件重判，召回在 0.625–0.700 之间动。
- **大输入下预期一次任务写不完 —— 但这条只对 FI toolkit 那批成立。**
  两个数必须带协议标签读，**不能并列**：

| 观测 | 输入 | 协议 | 结果 |
|---|---|---|---|
| `references/large-inputs.md` | FI toolkit，约 1700 行、18 个子程序 | 更早的 harness、更早的 skill 版本 | 14 次派发完整 4/14（29%），其中 6 次静默、4 次截断 |
| 符合性探针 + 完成率第三、四轮 | `objects_program` 1597 行、`flow_logic` 1114 行 | 当前版本，**不要求额外交付物** | **9 份报告全部产出** |

第二个数只说明"这一类输入在当前版本下目前写得完"，**不构成完成率断言**。
而"失败都死在第三节内部"这句旧的概括已经不准确：FI toolkit 那 14 次里有
**6 次是静默**——什么都没产出，根本没走到第三节。失败有三种形态：
静默、截断、写完但变厚变薄。细节见 `references/large-inputs.md`。

## 能声明什么，不能声明什么

这一节限定交付范围，不是免责声明。原始数据在
`analyzing-programs-workspace/iteration-8/`（上游仓库，不随 skill 发布）。

### 先说版本：下面的数字不是出货版本的数字

iteration-8 的全部数字都是在 **`b8f84e8`**（162 行）上测出来的。
**工作树与 `release/` 都到 `1.1.30`**（587 行，契约 1.3.13 / docgen 契约 1.0.3）：
归档在 `release/analyzing-programs-1.1.30/`（417 文件、33 目录），
zip 的 sha256 在 `release/SHA256SUMS`。1.1.30 改的是打包器：1.1.29 那份重写
丢掉了 `release/pack.py` 的 `NOT_SHIPPED` 与 `CRITICAL` 守卫，于是把整个测试 harness
发进了包，而 `--verify` 照报 clean——本版纳回守卫并给 `--verify` 加上
repository-only 检查。契约没有规则或阈值变化，只走 `ships_with`；docgen 契约
也不动（1.0.3 / ships_with 1.1.25），这次没碰属于它的东西。
**1.1.28 从未归档**（git 里有 bump，`release/` 里没有），从 1.1.27 直接跳到 1.1.29。
**效果**未测出结论。**

版本谱系（每一版都已归档在 `release/`，digest 见 `release/SHA256SUMS`）。
`commit` 列是本仓库的 git id，**不是** zip 的 sha256——那是 `release/SHA256SUMS` 的事。
**1.1.0 之前的 12 行沿用了上游血统的 id，在本仓库解析不了**（`git cat-file -t` 报
Not a valid object name），那几行的行数只能从 `--follow` 找到的同源提交间接印证；
1.1.0 起每行都能直接 `git show`。

| 版本 | 行数 | commit | 改了什么 |
|---|---|---|---|
| `b8f84e8` | 162 | `b8f84e8` | **唯一被端到端测过的版本**，但没出货 |
| `718f5988` | 215 | `718f5988` | 加第 6 步修复轮、事实性纪律、范例引用 |
| `0dc9f17e` | 215 | `0dc9f17e` | 1.0.0。相对上一版只改了节标题与少量措辞 |
| `006719f8` | 250 | `006719f8` | 1.0.1。加「闸门输出」一节、粘贴源码先落盘、形状闸门拆成第 7 步 |
| `fac4d5a3` | 280 | `fac4d5a3` | **1.0.3**。闸门 / 评分脚本 / 契约 / 两个测试**整组**换成未发布开发线那份；SKILL.md 补 `fence`、`fix-mislabel`、密度与三层窗口的定义，并按新闸门的实测行为重写退出码一节 |
| `d3c55463` | 321 | `d3c55463` | **1.0.4**。纯文档：Mermaid HTML 子集例外、教 `--fix`、大输入章节指向 `references/large-inputs.md`、修三处事实陈述（22 个百分点改为只留方向并标注幅度未测量 / 转写错误归属改正 / 失败形态补上静默） |
| `9a013e47` | 325 | `9a013e47` | **1.0.5**。唯一一处闸门改动：`fix-mislabel` 的判据从「每条语句都在源码某处出现过」改成「整块逐字**连续**出现在源码里」。旧判据在九份真实报告上误报 5 次、全部是真改法；新判据 5 次全消，同时保留对真引用贴错围栏的检出（测试从 95 项增至 98 项，新增的负向用例就是"各行都存在但不相邻"这一例） |
| `5b1241c` | 357 | `5b1241c` | **1.0.6**。三处闸门修复 + 文档对齐。P0-1：忠实度不再对整行中文静默放行（`WRITE / '开始'.` 被当成点评跳过，注释与字面量里的中文仍是代码）；P0-1b：省略放行只认代码部分，注释里的 `...` 不再是后门；P0-2：规则集读不到时以退出码 `2` 拒绝运行（原来未捕获异常退 `1`，而 `1` 被 SKILL.md 定义为"查过了、有缺陷"）。SKILL.md 补齐与这三处对应的说法；契约补上 `gate_start_refuses_without_a_rule_set`（1.2.3 → 1.2.4）；frontmatter 加 `version` / `contract`；测试从 98 项增至 115 项，drift 从 104 项增至 105 项 |
| `5ff381c8` | 412 | `5ff381c8` | **1.0.7**。纯文档，零闸门改动，契约保持 1.2.4。两处来自另一台设备上的现场反馈：**三层渲染成一段**——「拆分步骤」一节推荐紧凑写法，而那个示例把三层写在连续三行上，CommonMark 视为同一段落；且它与自己的范例 `example-report.md`（三层之间有空行）矛盾。12 个三层标签行现已全部后随空行。**第一层太笼统**——`:224` 的要素清单本就在，但抽象规则句没有失败示例；现补三组「笼统→具体」对照（右侧全用范例里的真实句子）、四问自检清单，以及"每层至少点名一个源码对象"。两处都**没有**加检查器：闸门只数字符数，evals 的缺陷问的是源码不是写法 |
| `25b711cf` | 473 | `25b711cf` | **1.0.8**。契约 1.2.4 → 1.2.5（新增两条 note）。来自 `zvend` 留出集的失败样本：**报告点名了那个标识符，然后转身去写下一条**。with_skill 臂的加权召回 1.476、without_skill 臂 1.571，符号检验 4:5、p=1.0，这轮测不出差别；但 9 条分歧里形状一致——被判 partial 的七条都属"说对了事实、没推到读者能行动的位置"（硬编码位图写成"跨行业遗留"、授权写成"不做权限控制"）。据此改三处：第三层新增「每个具体标识符必须紧跟运行期后果」的硬规则 + 两组对照；禁掉「需核实」当结论句；新增 `authz` 与 `ext-asset` 两条 note，两条都只在报告没给出后果时才发。测试 115 → 129，drift 105 → 107。**这三条是假设不是测量结果** |
| `748f36b2` | 476 | `748f36b2` | **1.0.9**。契约 1.2.5 → 1.2.6。三处都是复审 1.0.8 时**量出来**的，不是读出来的。**报告不是 UTF-8 时闸门抛未捕获异常**——`report_qc.py` 有三处裸读报告，cp936 报告（中文 Windows 上编辑器"另存为"的默认结果）→ traceback + 退 `1`，而 `1` 被定义为"查过了、有缺陷"，与契约自己写的 "the one false reassurance this script is not allowed to give" 同形；现在与源码一样退 `2`，并加了 28 项测试覆盖三种模式 × 三种编码。契约 `exit_codes["2"]` 三处与实测不符：说"Every trigger prints a line starting with `error`"（实际无参数与 `--fix` 路径不足这两个例外不带 error）、无模式限定地列出 `source is empty`（实际只有 `--fidelity-only` 拒，形状模式打 note 后照常返回）、用字节数指认闸门（`24224` / `45523`，实际 53462，文件一改就过期）——改成按模式列并删掉字节数。**127 条缺陷里 91 条用行号做 anchor**，源码前面插一行空行、同一个 `L5` 就指向别的语句，而 `evaluate.py` 里 7 处 `anchor` 全是打印、一个都不校验；全部换成源码文本，三份缺陷集的 `source` 字段改成能打开的真实路径。测试 129 → 157，drift 107 不变 |
| `b70980f` | 358 | `b70980f` | **1.1.0**。闸门加五条强制检查：保真改 token 序列比对、标识符/字面量/数字被改过退 1，标点级差异仍 advisory；第五节问题行必须点名源码里存在的对象；三层正文不得三行相同；散文 U+FFFD 视为失败；要求 flowchart 与 sequenceDiagram 各一张。拆分 `report_qc.py` 为 `scripts/checks/` 下四模块。**闸门变严，效果未知** |
| `301500c` | 476 | `301500c` | **1.1.1**。四轮系统性代码审查，修复 24 个问题：错误处理（OSError 未捕获）、参数校验（报告/源码同文件、-o 路径有效性）、契约对齐（exit_codes 描述、defect_line_prefixes 缺失项）、测试覆盖（all_notes 排序固定）、缓存管理（_src_identities FIFO 驱逐）、注释修正。测试 315 项全过 |
| `52e35cf` | 476 | `52e35cf` | **1.1.2**。契约 1.3.0。十二轮质量审查、53 处修复、315 项测试全绿 |
| `57c75b5` | 494 | `57c75b5` | **1.1.3**。契约 1.3.0 → 1.3.1。两处闸门崩溃改成正经拒绝：`inventory()` 对事件块取 `group(1)` 抛 IndexError（事件块的 keyword 就是名字，ANCHORS 不给它 capture group），未捕获异常退 `1`——而 `1` 被定义为"查过了、有缺陷"，模型会去改不存在的缺陷；内部异常现统一走 `die()` 退 `2`。docgen 的正则锚在 `METHOD` 后的 `(` 上，六种写法里只有带参数的那种能匹配，类方法全被漏掉。`abaplint-deps` 随 skill 一起发布、按脚本自身位置解析（装好的 skill 里 CWD 从不是 skill 目录）。SKILL.md 补退出码表与资源索引。410 个文件 |
| `75fb895` | 494 | `75fb895` | **1.1.4**。契约 1.3.1 → 1.3.2，只补文档：`exit_codes["2"]` 里"规则集读不到"这条触发器是 1.2.4 加的，1.2.6 重写那段字符串时弄丢了措辞，而它的兄弟键 `gate_start_refuses_without_a_rule_set` 一直活着——只读那张平铺表的读者已经看不到四个启动期拒绝里最早的一个。闸门行为与 1.3.1 完全一致。同批修换行符：`*.txt` / `*.js` / `*.xml` 补进 `.gitattributes`，八个 blob 重新归一化成 LF（`.gitattributes` 管不了已经提交的 blob，而 `git status` 归一化后一直读成干净），发布目录标成 `-text` 冻结以免 git 重编码破坏与 zip 的逐字节一致；`pack.py` 断言 `ships_with` 并打印与上一版的布局差异 |
| `37ea6bd` | 494 | `37ea6bd` | **1.1.5**。docgen 四处解析缺陷 + 第五个测试套件，契约不动（1.3.2）。`_find_block_end` 要求 `ENDMETHOD` 后面跟子程序名，而 ABAP 允许但不要求带名字，于是什么都不匹配、所有块都跑到文件末尾、`end` 对每个子程序都相同；`CALL FUNCTION` 的名字从 `[A-Z0-9_]` 取，漏掉带引号的 `CALL FUNCTION 'Z_BC_LOG'`——ABAP 里最常见的那种；`USING` 被 `.*?` 组进 FORM 正则，永远匹配空，FORM 从不报参数；内部表过滤用大小写敏感的 `startswith`，`lt_tab` / `ws_data` 被当成数据库表；锚点用 `^\s*` 缩进而 `\s` 也能跨换行，被空行隔开的子程序锚点早一行。新增 `tests/test_docgen_deps.py`（67 项）覆盖 docgen 与 `abap_deps_analyzer` 的解析器、锚点与命令行——写它才把这五处挖出来 |
| `74944da` | 494 | `74944da` | **1.1.6**。契约不动（1.3.2）。**分析器八处修复**：`--deps` 锚定脚本自身位置而非 CWD；类型引用先减去本地声明的类型名；`unknown_*` 改名 `unresolved_*` 并降为 `info`（「不在随包桩库里」不等于「SAP 里没有」）；补冒号形 `PERFORM` / `METHOD` 与类内裸调用、取标识符前先剥行内注释、每次 `analyze()` 复位状态、修 `->+` / `=>+` 的自身回归、支持 ALV 回调的字符串字面量。`tests/test_docgen_deps.py` 67 → 95，含一个「decoy CWD 放同名 deps 目录」的负向用例。**范例报告过不了自己的闸门**：`row-src` 只在传了源码时才跑，而守护它的两个测试都不带源码，§5 里 P2-3（只有 `+1` / `MIN/MAX`）、P2-4（无拉丁标识符）、P2-5（只有 `PERFORM` / `ENDFUNCTION`，均在关键字排除表内）、P3-2（只有源码外的 `c05_abap_unit`）四行被自己的规则判死——带源码跑是 exit 1。四行各补一个真实源码对象名，exit 0；`test_skill.py` 加一项带源码跑，drift 的变异探针原来同样传不出源码，现在在范例上专门跑 `row-src` 并带负向对照。168 → 169，121 → 123。**闸门文档三处与实测不符**：退出码表只列了契约 15 个缺陷前缀中的 8 个、`--fidelity-only` 输出格式写错（实际先打 `SUBSTANT` / `PUNCT-` 分级行）、退出码 `2` 的触发条件漏了「报告与源码同一文件」及 `--fix` 的三个输出路径拒绝 |
| `aa609d5` | 513 | `aa609d5` | **1.1.7**。契约不动（1.3.2）。四处 SKILL.md 措辞修复 + 一处索引说明，全部来自**在两个真实程序上跑 skill 的实测**，不是读出来的。**`enc` 在正文里零覆盖**：它在退出码表里，但 495 行里既没有 `enc` 也没有 U+FFFD / 替换字符 / 乱码——撞上的写作者不知道改什么，更不知道修法是从源文件重新另存 UTF-8、而不是删掉替换字符。**SKILL.md 有一条事实错误**：说两条 note「都只在报告没给出后果时才发」，但只有 authz 有消音门槛，`ext_asset_note` 只要源码里有一个位图/图标字面量就必然发（它自己的 docstring 就是这么写的）。authz 的门槛本身是个十词正则，写作者完全没有可能看见，SKILL.md 现在把它列出来了。第 5 步补一个预检：这两条 note 问的东西第 6、7 步补不上——那两步不许动分析，`--fix` 也只修 `ln` 与 `mm`——必须收笔前就写进去。`references/abap-syntax` 自称一份资源，实际是上游约 30 份 cheat sheet 里的 8 份，其内部 13 处交叉引用指向从未收录的兄弟文件；索引现在写明这一点，否则 SKILL.md 一边让人「查这里」、一边禁止「凭记忆」，落到中间的题就无路可走 |
| `51957ef` | 513 | `51957ef` | **1.1.8**。契约不动（1.3.2）。`abap-syntax` 从上游 SAP `abap-cheat-sheets` 收录第 9 份：`11_Internal_Tables_Grouping.md`（6794 B，照抄原文）。九份与上游 `main` 的 git blob SHA-1 逐一核对过、全数吻合——顺带量出一件与旧版同源的偏差：本仓库 `core.autocrlf=input`，上游 8 份 CRLF 结尾的 cheat sheet 进库时被归一化成 LF，发布包带的是归一化后的 blob（`11_...` 为 `cefecc33411f`），只有上游本来就是 LF 的 `27_Exceptions.md` 对得上；这是换行符归一化，不是内容改动，但拿包去核对的人会当成被改过，索引与契约现在都写明，免得误判。它补上的正是 1.1.7 记下的那个死角：SKILL.md 让人「查这里」，同时禁止「凭记忆」，而 `references/README.md` 明说目录里没有的语义就没有——落到这两句中间的主题没有合法路径可走。`LOOP AT ... GROUP BY` 就是这个死角：它的行为由用哪一种绑定形式决定（代表式绑定与显式键绑定、`INTO` 附加项、`GROUP INDEX` / `GROUP SIZE`、`WITHOUT MEMBERS`、成员循环），而这层语义此前只存在于未收录的兄弟文件里。索引同步改为 9 份 / 上游 37 份，补上 Apache-2.0 出处与坏链清单；收录这份带进一个未收录兄弟链接 `02_Structures.md`、同时移出 `11_Internal_Tables_Grouping.md`，唯一缺失文件名数保持 12 个。闸门不读任何参考资料、只读契约，419 项检查全过 |
| `5336b94` | 535 | `5336b94` | **1.1.9**。契约 1.3.2 → 1.3.3，**文档修正、闸门行为一字未动**（`gate_io` 不被闸门读取，只被契约自身与 `test_contract_drift.py` 消费）。全部来自**实测对照**而非读代码：把范例报告复制出来篡改一句引用，形状模式实际打印 `SUBSTA   line 152 ...` 然后 `FAIL  (1 defect(s))` 再跟一条 note，退出 `1`——**四个说法因此作废**：exit 0 格说「没有形状缺陷」，实际还要「且无实质改写」（`report()` 只在 `not bad and not n_sub` 时退 0）；文档写分级名 `SUBSTANTIVE`，实际是 `tier[:6]` 截出的六个字符 `SUBSTA`；文档说 verdict 是末行，实际形状与 `--fix` 都在 verdict **之后**再打最多七条 note；文档说最多六条 note，实际 `all_notes()` 最多五条 + `fidelity_report()` 每级一条 = 七条。**authz 消音关键词表是照抄错版**：1.1.7 说"把十词正则列出来"，列出的十个词里有四个在正则里根本不存在（`任何人` / `其他用户` / `全部用户` / `并发权限` 一个都不命中），而真正会命中的 `任何能运行` / `任何可运行` / `任意用户` / `全体用户` / `数据权限` 一个都没写——写「其他用户」想让 note 消失，它不会消失。**其余修正**：`--fix` 零修复时不写 `.bak` 但仍原地写回；空源码在形状模式打两条 note 不是一条；崩溃那行补回被截掉的尾部；exit-2 表删掉「报告与源码同一文件」——那个守卫不可达，扩展名分流保证同一个路径不可能同时进两边；第 6/7 步补上当前目录必须是 skill 根目录（闸门不像 `abap_deps_analyzer` 那样自我定位）以及 `--help` 会被当成没给报告而退 `2`；`184 个对象` 定义清楚（191 个 `.abap` 文件里带 `.clas` / `.intf` / `.prog` 的子集）并补上未使用清单的已知假阳性（`SET HANDLER ... FOR` 注册的事件回调一律报「未使用」，实际都在跑）；Mermaid 补上方法引用 `->` / `=>` 的两种写法与「标签措辞是机械残留，不受『不许改分析』约束」。README 修掉三处互相矛盾的「出货版本」、358 → 535、22 → 23 个锚点、skip note 从三条诊断改回五条、缺陷清单 112 / 6 → 127 / 7（`ztest7.defects.json` 15 条此前两个索引都没列）、changelog 行数 `301500c` 358 → 476 与 `74944da` 495 → 494，并把列名从「sha256 前 7 位」改正为 `commit`（填的一直是 git id，且 1.1.0 之前的 12 行沿用了上游血统、在本仓库解析不了） |
| `510902c` | 535 | `510902c` | **1.1.10**。契约不动（1.3.3）：没有规则、阈值或 `gate_io` 行变化。发布 1.1.9 后把它装进 `~/.agents/skills/` 验了一遍才发现 README 说错了一句话——它把 `test_skill.py` 写成「自足检查，不依赖项目数据」，跑法一节也说「169 项，自足」。**从仓库根跑是这样，从安装位置跑不是。** 五个 suite 都用 `HERE = dirname(abspath(__file__))` 往上数出仓库根，再去根下找同级的 `Test-source/` 与 `analyzing-programs-workspace/`；这两棵树明确不随 skill 发布。实测（`C:\Users\DzwU\.agents\skills\analyzing-programs`）：`test_skill.py` 168 / 169，挂的那一项是 `the exemplar's source is present`——`row-src` 的守护检查，它必须拿到 `Test-source/real/` 里那份 `zbc_show_error_log`；另外四个在第一个 fixture 就 `FileNotFoundError`。**闸门本身与它的脚本在装好的位置是正常的**：同一位置 `python scripts/report_qc.py references/example-report.md <源码>` 退 `0`、打 `PASS`，实测。所以那 419 项是仓库侧的说法，README 现在把这个区别写明，而不是让拿到发布包的人以为能在消费它的那台机器上自验。契约只把 `ships_with` 挪到 1.1.10，`version` 留在 1.3.3，并记了一段说明为什么 |
| `f3eab57` | 535 | `f3eab57` | **1.1.11**。契约不动（1.3.3）。**上一版只是把「tests/ 在包里跑不起来」写进了 README，这一版直接把文件不发出去。** 理由很直白：包里不该有跑不通的东西。做法在 `release/pack.py` 加一个 `NOT_SHIPPED = ("tests/",)` 排除名单，打包时会打印 `excluded 5 repository-only file(s)`；旁边配一条 `CRITICAL` 守卫，把 `schemas/` / `scripts/` / `references/` / `evals/` 四个闸门真要读的目录列进去，误填一个就让打包直接 `AssertionError`，而不是悄悄少发。**契约和闸门一字未动**：五个 suite 从不被 `scripts/` 导入、也不读任何契约键，所以包小 5 个文件、行为完全一致。README 的目录表把 `tests/*.py` 一行改标为「不随包发布」，「跑一遍」拆成两段——包里装好就能跑的（`report_qc.py` / `evaluate.py` 五条），和只在仓库里跑的（五个 suite，419 项）。`references/README.md` 与 `evals/README.md` 里各有一处指向 `tests/` 的交叉引用，那是指向仓库侧套件的，读包的人找不到很正常，保留 |
| `8b4e8ca` | 536 | `8b4e8ca` | **1.1.12**。契约 1.3.3 → 1.3.4。**`--fix` 会给一份还没过闸门的报告发 `PASS`。** 量出来的：把范例报告复制出来，在一个代码块里给 `ENDFUNCTION.` 后面加一个词（形状完全没动），三个模式各跑一次——形状模式退 `1`，打 `SUBSTA   line 187 ...`、`FAIL  tampered.md  (1 defect(s))` 再跟一条 note；`--fidelity-only` 退 `1`，打 `FAIL  ...  (1 rewrite(s), 0 punctuation-only)`；`--fix` 退 **`0`**，打 `PASS`。**同一个报告，两个模式，两个不同的答案。** 原因在 `--fix` 分支：`fidelity_report()` 其实已经调了，但 `n_sub` 只喂给了 note，返回值是 `1 if left else 0`，`left` 是形状检查——**note 说了实话，退出码没听。** 而契约 `exit_codes["0"]` 本来就把「没有实质改写」写成了 `0` 的条件，所以契约和闸门说的是两件不同的事；第 6、7 步的循环只看退出码，循环会停在一个伪造的引用上。修法是让忠实度计算提到 verdict 之前、返回值改成 `1 if left or n_sub`；**note 的顺序一个字没动**，形状与 `--fix` 仍然 verdict 在前、note 在后（`notes_follow_the_verdict` 断言、`test_contract_drift.py` 钉住的就是这条）。verdict 顺手不再用一个数把两类混在一起，改成各数各的、都收在 `need the model` 上——`1 shape defect(s)`、`1 rewrite(s)`，或 ` and ` 连起来——一个总数会让读的人以为剩下的都能机械修掉。契约侧：`exit_codes["0"]` 补上「三种模式一致」，`exit_codes["1"]` 与 `conclusion_lines` 带上新措辞，`release._comment` 记下这个洞。SKILL.md 说明 `--fix` 一行分级行都不打，只用一条 note 报改写数，所以在那里 grep `SUBSTA` 是空的；README 补上 `score` / `compare` 的 `--legacy`；`test_skill.py` 加三条检查（形状模式失败、`--fix` 非零、`--fix` 不打 `PASS` 且指名 rewrite），169 → 174、合计 419 → 424 项 |
| `e0f7612` | 536 | `e0f7612` | **1.1.13**。契约 1.3.4 → 1.3.5。**契约写了「三种模式一致」，闸门只在一种模式里兑现。** 量出来的：把 `RuntimeError` 注进 `report_qc` 的检测器，三个模式各跑一次同一个报告——形状模式退 `2`、打 `error  internal error checking ...`、无 traceback；`--fidelity-only` 退 **`1`** 加 traceback；`--fix` 退 **`1`** 加 traceback，**而且先把输出文件写完了**。`exit_codes["2"]` 从 1.3.1 起就说「in every mode」，SKILL.md 也这么说——但守卫只加在形状模式的检查循环外面，另两个分支的 `classify()` / `fix()` / `check()` / `fidelity_report()` / `all_notes()` 全是裸调用。**`1` 的意思是「查过了、有缺陷」**，第 6、7 步的循环盯着退出码，崩溃被当成缺陷：模型去修不存在的缺陷，`--fix` 还把一次没查过的运行的结果落盘。修法是 `run_detector()`——**一份**守卫、三个分支都过它——而且**消息也放进这个函数里**：按分支各抄一份正是另外两个漏掉的原因。`test_skill.py` 注入异常，三种模式各断言无 traceback、退 `2`、输出含 `the gate crashed`，共九条；在改动前的代码上 `--fidelity-only` 与 `--fix` 两条全挂（180 → 186 项）。顺手抓到两处自己引入的回归：新守卫的签名先是 `run_detector(fn, report, *args)`，而 `report()` 需要两个实参，形参名又正好叫 `report`——第一个版本把参数吞掉了，形状模式基线当场崩，`baseline report passes the gate` 这条把它挡在打包之前。契约侧：`conclusion_lines` 补上它**漏掉的唯一一种可打印形式**——`--fidelity-only` 在只剩建议级时打 `PASS  <name>  (N punctuation-only)`，verdict 仍是 `PASS`、退出码仍是 `0`，照 `conclusion_lines` 分类输出的读者会撞上契约从没提过的一行；`exit_codes["1"]` 说明，测试构造这个用例（把引用里一个空格挪进括号）并**匹配整行**，所以悄悄丢掉括号里的数也抓得住。另修两行契约自相矛盾：`source_is_optional.verdict_still_printed` 说「three diagnostics」，而 note 与 `needs_source` 都是五条；`diagnostics.enforcement` 说「note -- never changes the exit code」，而 `advisories[fidelity].enforcement` 说它的 SUBSTANTIVE 级**就是**缺陷行、进 N、进退出码——fidelity 又列在 `diagnostics` 下面，顺着读就读成纯建议，这条是真的会误导人的那一处，`enforcement` 现在把例外写出来了。README 的 `--legacy` 段是**写反的**（「加了它就跳不过去」——它是跳过校验的那个旗子），且把缺的字段说成 `evidence.quote`，实际必需的是 `evidence.<id>.report_line`；照 `evaluate.py` 重写，列出四种拒绝原因、`--report` 的要求，以及**它不豁免 `false_claims`** |
| `1aa800f` | 536 | `1aa800f` | **1.1.14**。契约 1.3.5 → 1.3.6。**「源码是空的」和「源码只有一个空格」在闸门眼里是两件事，于是同一份干净报告能读出 28 个缺陷。** 量出来的：把范例报告对着一个只含空格和制表符的文件跑——形状模式退 `1`、打 `FAIL  (28 defect(s))`，18 条 `row-src` 加 10 条 `SUBSTA`；同一个文件喂给 `--fidelity-only` 却是 `error source is empty` 退 `2`。三个模式，一个输入，三种答案。根因是两套判空不一致：`report_qc.py` 用 `not src.strip()`，六个吃源码的检测器用 `not src`——空白串是 truthy，于是照常进来了。`classify()` 数到 0 个标识符，把每句引用判成实质改写；`row-src` 算出的 `flat_src` 是空串而不是 `None`，绕过了它自己那句 `no source given: cannot judge, so do not fail` 的出口，把每一行问题判成「没指向源码里的东西」。这是 `ReadError` 那道守卫要挡的同一类假判：判不了的被报成了结论。修法只有一处：`checks/text.py` 加 `_src_of()`，三个模块本来都从那里 import。顺手补两处对不上的文档：skip note 和 `diagnostics.needs_source` 都说五项，而 `row-src` 是第六个吃源码的、也跟着一起跳过——1.3.5 那次只把 three 改成 five，漏了它。另修 `--fix` 的写盘顺序：写文件原来夹在第二个检测器和后面三个之间，所以后三个一崩就退 `2` 说「一个字都没查」，可输出文件已经落盘了；现在四个检测器都跑完才写，拒绝运行时不留任何文件。test_skill 186 → 194。 |
| `d4d99cb` | 536 | `d4d99cb` | **1.1.15**。契约 1.3.6 → 1.3.7。两处都是**一行**的改动，但两处都把写下来的承诺弄假了。 **忠实度的 note 没有分母。**它只数失配的那几条，于是「一份长报告里 3 处改写」和「一份短报告里 3 处」打印得一模一样——而短报告那种正是闸门分不出的情况。量出来的：把范例报告分别对着**一个只含注释的文件、一份英文散文、另一个无关的 ABAP 程序**跑，三份都打出与「引用全是编的」完全相同的 10 条 `SUBSTA`、退出 `1`；对着它自己的源码是 `PASS`、退 `0`。修法是 note 改成 `N of M`（`M` 是报告里引用语句的总数），**只有 `N=M` 时才多问一句「源码是不是拿错了文件」**——这是唯一一个不需要阈值的边界，因为按标识符个数卡阈值根本分不开：只含注释的源码有 6 个标识符、英文散文有 20 个，两个都非零。`classify()` 只返回失配的，于是把探针集合提成 `_quote_probes()`，分母与失配数共用同一份，免得两处再漂开。 **拒绝运行的行有三张脸。**`die()` 打的 `error` 前面缩进两格，而两处导入期拒绝是顶格的，于是契约 `conclusion_lines` 记的 `"error  <what is wrong>"`（顶格）与 `die()` 那一路不一致，SKILL.md 那句「输出以 `error` 起首」对所有走 `die()` 的拒绝都不成立。现在三处都顶格，触发条件一字未动。 test_skill 194 → 200（三条拒绝形态、三条分母），合计 444 → 450 项。 |
| `b7e8ba7` | 536 | `b7e8ba7` | **1.1.16**。契约 1.3.7 → 1.3.8。**`--fix` 把「存不回去」报成「有缺陷」。** 量出来的：`-o` 指向一个已存在的目录、指向一个只读文件、或者原地模式下 `<报告>.bak` 已经是个目录——三种都退 `1` 加 traceback，一个字都没写出去。`1` 的意思是「查过了、有缺陷」，第 6、7 步的循环盯着退出码，模型就去修从未被查出来的缺陷。检测器有 `run_detector()` 那道守卫，**写盘没有**；预检只查 `-o` 所在目录、从不查 `-o` 本身，所以没有一条测试能碰到它。修法是 `write_text()`走同一套拒绝路径：`error` 顶格、退 `2`；消息说**没写出去、这次运行不是结论**，**不说「没查」**，因为报告确实先读完了、缺陷也确实查到了，只是存不回去。`.bak` 在报告之前写、`-o` 跳过 `.bak`，所以三种情况下都不留半修好的文件。**`--fidelity-only` 会让 `2` 跟在一条已经打出来的 `PASS` 后面。**它接受多份报告，却在循环里逐个校验路径：前面几份的判决已经打印完，后面的路径不存在才拒绝——按「`2` = 一个字都没查」处理的调用方会丢掉一个真实的 `PASS`，而同一个调用在形状模式下是先拒绝、什么都不打。现在它和形状模式一样先校验完所有路径再读第一份。**忠实的引用只要超过 30 个 token 就永远是实质改写。**标识符窗口按位置最多枚举 30 个 token，更长的探针根本不在集合里，于是「查不到」被 `classify()` 的并集规则读成改写——哪怕那句引用是源码原文。量出来：81 个源码、177092 条语句里 8 条超窗，最长 40 个 token，每一条都是永不消失的 `SUBSTANTIVE`，第 6、7 步会在一个不存在的缺陷上循环到底。那些探针改成直接对源码的 token 序列线性搜一遍，窗口上限照旧，管住的还是绝大多数情形。**顺带把 1.3.7 记错了的那句注释改了。**`release._comment` 写「只有 `M` 等于失配数才多问一句源码是不是拿错了」，而 1.3.7 的代码数的正是失配数——`sub` 加 `PUNCT-ONLY`。于是那句 note 会在「有一条引用只差标点」时问你要不要换源码文件，而那恰恰是**证明源码没错**的配置：那条引用的标识符确实在源码里，只是标点不同。量出来：一条只差标点加一条实质改写，打印 `1 of 2 ... rewrite the source, and not one quotation matches the source`，下一行又说第一条只是标点差异。条件改成 `len(sub) == total`。**目录被当成源码时，报的是编码错。**`open()` 在目录上抛 `PermissionError`，`OSError` 分支把它写成 `not readable as utf-8`——戴了编码错误口罩的权限错误，读的人会去文件夹里找 BOM。现在三种模式都报 `is a directory, not a source file`。**顺手修了本文件自己。**上一行原来断在四个物理行上、前面还空了一行，表格其实在 1.1.14 就结束了，1.1.15 是段落不是表格行。已合并成一行，1.1.16 也按一行写。gate 侧在 `b7e8ba7`，契约与 SKILL.md 在 `4b05e4d`。test_skill 200 → 231（十二条写盘拒绝、四条 hint 边界、四条多报告拒绝、两条长引用、九条目录），drift 123 → 124（契约多一条 `skill_anchor`），合计 450 → 482 项。 |
| `f7c1e7a` | 536 | `f7c1e7a` | **1.1.17**。契约 1.3.8 → 1.3.9（docgen 契约 1.0.0 → 1.0.1）。一轮把 1.1.16 之后读出来的问题一次性清掉，**十条里八条是「写了却没写出来」**。 **`--fix` 静默丢掉第一份以外的报告。**一次给两份报告，它修完第一份就退 `1`，第二份字节不变、输出里一个字的交代都没有——按批处理目录跑的调用方拿到一份修好的报告和一句「还剩一个改写」，以为只有一份有问题。现在多于一份直接拒绝、两份都点名，一个字不写。 **原地模式比的是字符串。**`-o` 写成 `./rep.md`、报告传 `rep.md`，字符串不等所以被判成「写到别处」，于是就地改写而不留 `.bak`——原地改坏的唯一副本没得救。现在比 `abspath`。 **`--fidelity-only` 一条 note 都不打。**它调的是 `classify()`，那个函数只返回失配的、不返回 note，于是分母、以及「源码是不是拿错了文件」那一句——整条诊断最有用的信息——在**唯一以忠实度为目的的一步**里从来没出现过。现在调 `fidelity_report`，三种模式打同一条 note。 **`docgen --format html --validate` 用自己的输出当靶子然后判它不合格。**`validate()` 有 `format` 参数、默认 `markdown`，而唯一调用它的地方传了三个参数，所以 html 那份是按 markdown 章节清单检查的——五条假「缺章节」，而且 FAIL 分支在写出文件之前就 return 了，**磁盘上什么都没有**。现在传第 4 参；FAIL 时文件照样写出，判决在退出码里。 **契约读不到就当没规则。**`load_contract()` 吞掉 `OSError` / `JSONDecodeError` 返回 `{}`，而空契约意味着没有必需章节、没有任何校验开关——`--validate` 于是对着空气判 PASS。现在让异常上浮，`main()` 按 `report_qc` 同一条路径拒绝。 **三个校验开关是装饰。**`required_sections` / `encoding_utf8` / `code_fences_closed` 在契约里声明着，代码里没有任何调用方读它们，检查无条件跑，设成 `false` 什么都不发生。现在是真开关、默认 `true`，行为不变而标志名实相符。 **`docgen._die` 打 stderr，`report_qc.die` 打 stdout**，而契约写的是 stdout——只读一个流的调用方拿到 `2` 却拿不到任何解释。现在统一 stdout。 **依赖分析器用 `1` 拒绝运行**，而 `1` 是「查过了、有结果」；中文前缀「错误：」也和契约的 `error  ` 不符。现在退 `2`、统一前缀。 **契约自己的错。**`validated_by` 三个值写成 `docgen.py --check-class` 这类根本不存在的 flag（argparse 拒收），而真正存在的 `--validate` **从未出现在任何文档里**——现在改成真实调用，SKILL.md 也第一次提了它；`exit_codes["2"]` 那句「prints no verdict」过宽：写盘拒绝前缺陷行已经先打出来了，现在改成「prints no verdict **line**」并说明`error` 不是输出的第一行。 删了三处永不可达的「报告与源码不能是同一文件」守卫。 test_skill 231 → 241（五条 `--fix` 单报告与就地备份、五条 `--fidelity-only` note），test_docgen_deps 95 → 117（html+validate、契约读不到、`validated_by` 可执行、三个开关真的能关），合计 482 → 514 项。gate 侧在 `f7c1e7a`，契约与文档在下一个提交。 |
| `f34b7dc` | 536 | `f34b7dc` | **1.1.18**。契约 1.3.9 → 1.3.10、docgen 契约 1.0.1 → 1.0.2。把 1.1.17 复审读出来的 9 条全部修完，其中两条是**契约/SKILL.md 写了闸门没做到**：`exit 2` 仍会跟在一条已打印的 `PASS` 后（报告的可读性没进预检），`abap_deps_analyzer` 的 `exit 1` 是到不了的死代码。另加三条 docgen 拒绝（目录 / markdown / 空源码）、零引用时补一条 note、`-o` 写在 `--fix` 之外点明原因。测试 540 项：九条修复新增 24 条，另加 8 条 —— 5 条**契约词表探针**（`gate_io` 里点名的 `--flag` 与 `.py` 必须真在代码里出现，带一个把 `--root` 注进去、要求变红的变异自检），3 条分析器把目录当源码时拒绝（此前落到裸 `except`，打出原始 `IsADirectoryError` 文案，跟另外两个脚本对同一种输入给的三种拒绝对不上）。修 3 时发现两处测试自身不对（`required_sections` 那条开关从未被真正验证过），一并改掉。同一轮把契约里编出来的 `--root` 触发条件、不可读 contracts 目录三条叙述删掉，补上第 2 条修欠下的 SKILL.md 半段与 `validation._comment` 里 7 个开关的实际作用范围。 |
| `5cd6ef3` | 536 | `5cd6ef3` | **1.1.19**。契约不动（1.3.10）：没有规则、阈值或 `gate_io` 行变化，只有 `ships_with` 走。**忠实度的身份序列会在一句注释里跑丢。**`checks/tokens.py` 的字面量分支是 `'(?:[^']|'')*'`，而 `[^']` 也匹配换行——注释里一个不配对的撇号（`Don't` / `It's`）就开着一个字面量，一路吞到下一个撇号。量出来：`zalvtree.abap` 的 identity 从 **635 个 token 掉到 429**（`APPEND` 12 → 1、`fieldcatalog` 20 → 2）。同一份报告的 150 条引用里有 **66 条判成 `SUBSTANTIVE`**、退出 `1`；逐字回读源码，**150 条全是原文、0 条改写**——闸门把「有实质改写」安在了一份诚实的报告上。分层只看 identity，`classify()` 里压平子串那一半救不了它们。**改一行**：字面量不许跨行（ABAP 语句以句点结束、注释到行尾，引号必在同一行闭合），`''` 仍算一个字面量。两条回归：**注释撇号不能开一个字面量**、**撇号后面的语句还在 token 序列里**——第一条在改前的代码上就是红的，所以它确实是探针。测试 540 → **542** 项。改前同一份报告两个模式都退 `1`，改后退 `0`、打 `PASS`，与退出码表一致。`ships_with` 移到 1.1.19：**一个写着 1.1.18 的副本，在注释里含撇号的程序上会报出从未写过的改写。** |
| `d951b4e` | 541 | `d951b4e` | **1.1.20**。契约不动（1.3.10）：没有规则、阈值或 `gate_io` 行变化，只有 `ships_with` 走。**新增 `scripts/recon.py`**，把 Analysis Flow 第 1、2 步合成一次调用：校验源码、带行号打印、再跑 `docgen.py` 读回它写出的子程序清单。原来这是三轮——docgen 只在 stdout 打四行回执（`Generated:` / `Type:` / `Format:` / `Size:`），清单在文件里，得单独读一轮。退出码只有 `0` 与 `2`、**没有 `1`**：它不判报告，所以没有东西可报成缺陷，而「任何非零都是缺陷」的调用方会去修一批从未被查过的缺陷；五条拒绝（不存在 / 目录 / markdown / 非 UTF-8 / 空文件）全部先打 `error` 再退 `2`，**且不会先打出半个源码**。清单仍由 docgen 生成，recon 只做子进程与读回，两者不会各说各话。行号用 `split("\n")` 而非 `splitlines()`——后者丢末尾空行会让整个 dump 后移一位，引用就与闸门实际检查的源码对不上（第 1、42、265 行逐字比对过）。它按自身路径定位 docgen，不要求当前目录是 skill 根目录，与 `report_qc.py` 正好相反。**没加检查**：recon 无测试守着，五个套件仍是 542 项全绿、计数不变 |
| `63c16cc` | 541 | `63c16cc` | **1.1.21**。契约不动（1.3.10）：没有规则、阈值或 `gate_io` 行变化，只有 `ships_with` 走，SKILL.md 仍是 541 行。**给 `recon.py` 补上 42 项测试**，`test_skill.py` 241 → 283，五个套件 584 项全绿。1.1.20 发布时五个套件一条都没碰它。**两条新测试第一次跑就失败，两条都是 `recon.py` 自己的缺陷**：一是它的 `stdout` 被 Windows 翻译了——dump 每行结尾都带一个源码里不存在的回车，而闸门读源码不翻译，dump 和闸门对同一行永远差一个字符；二是它的守卫只证明「那个路径上有文件」，上一次跑留下的同名旧文件足以让一份它没生产的清单被当成自己的产出报成功（记录未修）。`_comment` 增到 312 条 |
| `ca8e133` | 546 | `ca8e133` | **1.1.22**。契约不动（1.3.10）：没有规则、阈值或 `gate_io` 行变化，只有 `ships_with` 走，SKILL.md 541 → 546 行。**拒绝之前不再打印任何东西**：`recon.py` 先跑 `docgen.py` 再写 dump，否则 docgen 拒绝时整份源码已经打出去了（最大的语料文件是 29564 行 / 1517397 字节）。header 第二行现在给出这次会打印的总字节数，按字节算，中文注释一个字三个字节。`test_skill.py` 283 → 287，五个套件 588 项全绿。补上 1.1.21 漏掉的那条断言——docgen 拒绝必须不留下任何编号行。顺带修掉 SKILL.md 第 6 步一句说反了的话：两个脚本都自定位。
| `dc3e95d` | 546 | `dc3e95d` | **1.1.23**。契约不动（1.3.10）：没有规则、阈值或 `gate_io` 行变化，只有 `ships_with` 走，SKILL.md 仍是 546 行。**四条没有测试守着的拒绝路径**：`recon.py` 违背了自己文档里的「没有 exit 1」——读回 docgen 写出的文件用的是没有守卫的 `read_text()`，docgen 写了非 utf-8 字节就以 traceback 退 `1`，而 `1` 正是「缺陷判决」；docgen 缺失时报「docgen 退出了 2」，给一个从未运行的 docgen 编了个退出码，python 写在 stderr 里的原因被丢掉；只转发 docgen 的 stdout，崩溃时退出码成了唯一交代；`report_qc.py` 把「读不到」报成「不是 utf-8」——`read_report` 与 `read_src` 都捕 `(UnicodeDecodeError, OSError)`，两种异常同一句话，1.3.10 只修了目录那一种。段标题改成 `== DOCGEN OUTPUT`、摘要行的数改成 `docgen block`。`tests/test_skill.py` 287 → 311 项，5 个套件 612 项全绿。 |
| `143b290` | 546 | `143b290` | **1.1.24**。契约不动（1.3.10）：没有规则、阈值或 `gate_io` 行变化，只有 `ships_with` 走，SKILL.md 仍是 546 行。**九条 1.1.23 没有测试守着的缺陷**：`recon.py` 读 docgen 时 `child.stdout` 回来 `None`，`+ child.stderr` 抛 `TypeError`——拒绝以崩溃的形式到达；`checks/contract.py` 在 load 之后的推导里抛 `KeyError`，拿「有缺陷」的退出码报一份被重排过的规则集；`evaluate.py` 三处假定输入就是它写代码时那个形状；`docgen.py` 加载契约漏了 `UnicodeDecodeError`、`_read_source` 把两个子句合成一个；`recon.py` 把自己拥有的 `-o` 交给 docgen 诊断；`.strip()` 收下一个全 null 字节的源；`SKILL.md` 还把那段叫「清单」。`tests/test_skill.py` 311 → 365 项，五个套件 666 项全绿。 |
| `0b7322f` | 546 | `0b7322f` | **1.1.25**。契约 1.3.10 → 1.3.11、docgen 契约 1.0.2 → 1.0.3，SKILL.md 仍是 546 行。**四条读出来的「形状错」：三条是拒绝以崩溃的形式到达，一条是静默判 PASS**。`checks/contract.py` 的守卫只包住「规则在不在」、包不住「规则都在之后怎么算」——四条派生量在 `try` 之外算，`buckets` / `patterns` / `advisories` / `forbid_in_display_text` 给错类型分别抛 `StopIteration` / `LookupError` / `TypeError` / `re.error`，全部 traceback 退 `1`，而规则集能解析、键也齐，只是类型错了；1.1.24 记的「catch 已盖住 `json.load` 能返回的任何形状」当时就是错的，存在检查与派生量是两条 `try`。docgen 契约**一道形状检查都没有**：根节点是 `{}`、一条规则都没有时，`validate()` 拿空章节表对一份报告判 PASS——必需章节一项不落地「通过」，因为一项都没要求。「源码有没有内容」原来四个地方三个写法互不一致：`.strip()` 收下全 null 字节的源，`isprintable()` 收下只有 U+FFFD 的源——而 U+FFFD 正是 `encoding` 那条规则存在的理由，于是给一个**不存在的程序**生成了文档。现在合成一个谓词 `has_content()`，落在新增的 `scripts/checks/source.py`；它不 import 规则集，`docgen.py` 与 `recon.py` 才能读它而不把 report 契约一起背上（第一版放进 `checks/text.py` 时，`docgen.py` 在 report 契约缺失时会拿那份契约的词拒绝自己——一份关于错误文件的拒绝）。三处消息对齐到 `recon.py` 早就用的那句 `no analysable content`。`tests/test_skill.py` 365 → 396 项、`tests/test_docgen_deps.py` 129 → 171 项，五个套件 666 → 739 项全绿。复审另读出的五条本轮明确不动，量与理由记在下面的 changelog |
| `ed2aa21` | 545 | `ed2aa21` | **1.1.26**。契约不动（1.3.11）：没有规则、阈值或 `gate_io` 行变化，只有 `ships_with` 走；docgen 契约也不动（1.0.3 / ships_with 1.1.25），这次改的两个脚本都不属于它。SKILL.md 仍是 545 行——只动了 frontmatter 的 `version`。**上一轮记下的理由写错了**：`evaluate.py` 与 `abap_deps_analyzer.py` 没有 stream `reconfigure`，理由写的是「它们不是被别的脚本读的子进程，所以那个失效方式到不了它们」——入口是它们**自己的** stdout，不是子进程的。分析器的报告整篇是中文，在 cp936（中文 Windows 的默认）或 cp437 上 `print()` 抛 `UnicodeEncodeError`，被外层 `except Exception` 抓住、打一行 error、退 `2`——「拒绝了、没查过」，而这个运行跑完了分析、产出就在手里，一个字都没送到调用方。量在同一份源码上：默认编码 `rc=0`，cp437 与 cp936 修前都是 `rc=2`，修完三种都是 `rc=0`；cp936 下漏出去那半截本身还是乱码。同一缺陷 1.1.10 修过一次、只把它藏了：当时 handler 的前缀是中文，cp437 下 handler 在自己那两个汉字上崩，traceback 顶掉诊断、退 `1`（「跑完了、有缺陷」），而报告根本没产出；后来把前缀改成 ASCII 的 `error`，traceback 没了、**退出码还停在 2**，就这么活到本轮。守这个 guard 的断言只列了两个脚本，`report_qc.py` 从 **1.1.0** 就有它、**从来没有断言过**，循环现在列全五个。`tests/test_skill.py` 396 → 399 项，五个套件 739 → 742 项全绿。另记一处记错的行数：SKILL.md 从 1.1.22 起就是 545 行，1.1.22–1.1.25 四行写的 546 都多了一行 |
| `487b002` | 548 | `487b002` | **1.1.27**。契约 1.3.11 → 1.3.12，动的两行都是 `gate_io`；docgen 契约不动（1.0.3 / ships_with 1.1.25），这次改的 `--fix` 不属于它。SKILL.md 545 → 548 行。**上一节记下没动的两条，都是「写一个已存在的路径时，旧内容不留一份」。** **`--fix -o` 对已存在的文件静默覆盖。**重新量：`-o` 指向一个 33 字节的文件，运行完它变成 889 字节、打印 `repaired 1 mechanical defect(s)`、退 `0`，临时目录里**一个 `.bak` 都没有**。根在两边：写盘前的预检只看 `-o` **所在目录**存不存在、可不可写，**从不看 `-o` 本身**；备份的条件是 `dest == rep and n`——只在原地、且确实修了一处才写 `.bak`，`-o` 那半边永远用不上备份，且什么都检不出来报。「预检只涵盖 `-o` 所在目录、从未涵盖 `-o` 本身」这句还是契约自己记的，记完没动。 **第二轮 `--fix` 覆盖第一轮的 `.bak`。**连跑两轮原地修复、每轮都确实修了一处，`.bak` 先 833 字节、再 829 字节：第一轮那份没了，没有 `.bak.2`，也没有一个字的交代；而只有第一轮那份才是能退回的——第二轮写下的是第二轮前的文本，它没帮你找得更早。修法是在写之前看 `.bak` 那个路径是否已存在，**存在就拒绝**，文件或目录都算。之前只有目录形态会到达（`IsADirectoryError`，测试里有一条），而**文件才是常态**。`exit_codes[2]` 的触发条件一字未加，只把「`.bak` 是目录」扩展成「`.bak` 存在」。 **换行不是统一，是逐个位置带回去。**原来用一个布尔：报告里有没有 CRLF。一份 1 处 CRLF + 55 处 LF 的报告输出成 56 处 CRLF + 0 处 LF，回执却印 `repaired 0 mechanical defect(s)`——**报告没改动一处，文件却整篇换了换行**。改成把每个换行带回自己的位置（修复只改行内文本、不增减行数），回执与文件于是在**构造上**一致：1 处 CRLF + 55 处 LF 进去，1 处 CRLF + 55 处 LF 出来，字节完全一样。 **改的是备份的条件，不是备份的时机。**条件从「确实修了什么」换成「这次写入会不会丢掉什么」：一次什么都没修出来的运行，只要它把一个别人的文件换成了报告，同样先留备份；字节完全一样（原地零修复）就不留——这正是原地 `--fix` 能连着跑两次的原因。`.bak` 那份是上一次运行留下的版本、是退回时唯一的路，覆盖它等于把退路删掉，所以拒绝而不是覆盖；消息仍是 `could not write ... -- nothing was written`。 `tests/test_skill.py` 399 → 416（17 项：全 CRLF / 全 LF / 混合三种风格各要带回原换行、各要确实修到；`-o` 写出前先救已存在的文件并比字节；`.bak` 已存在时拒绝写入；其中两条在修前的代码上是红的，所以它们确实是探针），五个套件 742 → **759** 项全绿（416 + 171 + 129 + 9 + 34），`test_contract_drift.py` 的两个 pin 与两个 `_comment` 条数同步，`verify_ship.py` 14/14。另记一条**不动**：契约声明 11 个必须存在的键，其中 `gate_io`、`loop_position`、`claim_separation` 三个没有读取方——不是崩溃，是契约设计问题（写进契约而不让闸门读，是文档还是规则），保持记录。 |
| `9cc86fd` | 565 | `9cc86fd` | **1.1.28**。契约不动（1.3.12）：没有规则、阈值或 `gate_io` 行变化，只有 `ships_with` 走。SKILL.md 548 → 565 行。**六个元工具**，都是维护 skill 本身用的、不被闸门调用：`lint_skill.py`（SKILL.md 对照 `schemas/skill-contract.json` 检查）、`dedup.py`（语义重复章节）、`lift.py`（两份 verdict 的 recall 差异与符号检验）、`security_probe.py`（17 组对抗输入压测 `--fix`）、`index.py`（`references/` 的 TF-IDF 搜索索引）、`evolve.py`（历史报告 P0-P3 模式挖掘与更新建议）。同一提交加 `schemas/skill-contract.json` 58 行——SKILL.md 自己的规则第一次有了可机检的来源，之前那套写法纪律只存在于人眼。五套新测试：`test_lint_skill` 41、`test_dedup` 33、`test_lift` 35、`test_index` 37、`test_evolve` 25。**这一版没有归档**：git 里有 `9cc86fd` 与 bump 提交 `7639efc`，但 `release/` 里没有 `analyzing-programs-1.1.28/`、`SHA256SUMS` 里也没有它的一行——下一个归档直接是 1.1.29。装 `release/` 的人拿到的仍是 1.1.27。**提交消息里的「986 项（759 existing + 227 new）」两个数都不对**：五个新套件是 171 项、再加 `security_probe.py` 的 17 项共 188 项，加上原五个套件的 759 项是 947——而且 drift 与 gate_enforcement 在 1.1.29 又各增了一些。这个数当时是从提交里抄进 README 的，1.1.30 换成实测值 |
| `5784c52` | 587 | `5784c52` | **1.1.29**。契约 1.3.12 → 1.3.13，SKILL.md 565 → 587 行。**新增 `esc` 缺陷类型**：源码里的转义序列（`%_` / `+CONCAT` / 字符串拼接）被报告写成转义残留的字面形态，读的人以为那是程序里真的字符串。新增 `scripts/checks/escape.py`（69 行），`esc` 进 `defect_line_prefixes`，`test_gate_enforcement.py` 34 → 41、`test_contract_drift.py` 129 → 138。同批 `0243ce2` 把散落的检查入口收成一个 `run_tests.py` 与一个 `package_release.py`，版本从 SKILL.md frontmatter 读而不是从参数读——参数会是那串版本号活着的第四个地方。归档 `461` 个 zip 条目、sha256 `2545abab`。**这个包带着自己的测试 harness**，见下一行 |
| `0243ce2` | 587 | `0243ce2` | **1.1.30**。契约不动（1.3.13）：没有规则、阈值或 `gate_io` 行变化，只有 `ships_with` 走；docgen 契约也不动（1.0.3 / ships_with 1.1.25）。SKILL.md 仍是 587 行——只动了 frontmatter 的 `version`。**`0243ce2` 重写打包器时丢掉了 `release/pack.py` 里的那条守卫**：旧版有 `NOT_SHIPPED = ("tests/",)` 加一条 `CRITICAL` 断言，新版只有 `EXCLUDE_DIRS`，于是 1.1.29 把十个测试文件连同整个 harness 发进了包。量出来：`--verify` 在那个 461 条目的包上照报 `zip contents match` 与 `SHA256SUMS matches` 两条 `ok`——那版**根本不存在** NOT_SHIPPED 这份名单，`--verify` 只比 zip 与目录、查 digest，而这两件都真的对上了（461 条目两边一致，digest 也吻合），所以它没有东西可查。新检查加进来之后就必须小心一件事：`verify()` 的目录侧若走 `walk_clean()`，会被过滤掉的正是它要抓的东西——被污染的包在那份视图里显得自洽，检查永不触发。所以目录侧走 `walk_all()`，两份视图都是不过滤的，比对与检查都成立。装到仓库外才量得出失败：四个 suite 在第一个 fixture 就 `FileNotFoundError`，`test_skill.py` 与 `test_contract_drift.py` 各挂一条 `the exemplar's source is present`。修法是三处：`NOT_SHIPPED` 与 `CRITICAL` 补回并加**双向**前缀断言（旧版只查 `_p not in CRITICAL`，`"scri"`、`"schema"`、`"scripts/checks/"` 都会漏过去，现在 `NOT_SHIPPED ⊆ CRITICAL` 也不放行）；`verify()` 改用 `walk_all()` 这份**不过滤**的遍历，并新增 repository-only 检查；`ship()` 从拷贝树里 prune 掉 NOT_SHIPPED（`copytree` 的 `ignore` 按 basename 匹配，路径前缀交给它不生效）。验证：`--verify 1.1.29` 退 `1` 并列出 11 个 repository-only 文件（`tests/` 目录条目加十个测试），`--verify 1.1.27` 全绿退 `0`。**1.1.29 本身不修**：`release/` 是 append-only，它记的 digest 对得上它自己那个带 harness 的 zip，改它等于篡改一份已签发的归档。归档 `450` 个 zip 条目（417 文件、33 目录）。同批把 README 同步到现状：目录清单补上 `scripts/checks/` 与六个元工具、`schemas/` 另两份契约、`abaplint-deps/` 与四份失败模式记录；「跑一遍」补五套新测试并改成实测的 946 项（十个套件）与 `run_tests.py`；`tests/` 一节把 1.1.10 量到的失败形态改成本轮的实测、把 `release/pack.py` 改成 `package_release.py` 并记下这次回归；`五个脚本` 的 UTF-8 守卫改成十一个；版本表与本节补齐 1.1.28 起三行 |

**契约版本与发布版本是两条独立的轴。** 契约 `version` 只在该文件自己的规则、
阈值或 `gate_io` 行变化时递增；发布版本对措辞和闸门行为的变化也递增。
所以两者只在契约恰好一起动的时候才相等——1.0.6 与 1.0.7 都带契约 1.2.4，1.0.8 带了 1.2.5，1.0.9 带了 1.2.6。这个映射记在契约的 `release.ships_with` 里，否则光看数字分不出
`1.2.6` 比 `1.0.9` 新还是旧。已部署的副本要能自报版本，
所以 frontmatter 也带 `version` 与 `contract` 两个字段。

| | b8f84e8（唯一端到端测过） | 748f36b2（出货） |
|---|---|---|
| 六节结构 / 三层格式 | 有 | 有（原样保留并扩充） |
| 第 6 步：写完后只修引文的独立一轮 | 无 | 有 |
| 事实性纪律章节 | **无** | 有 |
| 逐字符忠实、不展省略的代码块规则 | 部分 | 有 |
| 范例报告 / schemas / 评分脚本引用 | 无 | 有 |

**这张表比对的两个版本都已不是出货版本。** 写这张表时出货的是 `301500c`（1.1.1），
现在出货的是 `1.1.9`。这一栏过去一直停在一个更早的版本（1.0.5 / `9a013e47`），
而真正的出货版本一直在往前提——是版本表先更新、这处没跟上；到 1.1.1 时仍然没跟上，
现在对齐。表里的结论只对那两个版本成立。

对齐时实测过 1.0.5 与 1.0.9 两版的 SKILL.md：上表五项**全部仍在**，没有一项被
删改；1.0.5 之后新增的是「第 6 步」这类独立一轮、`fix-lang` 之外的第六条 note、
第三层的运行期后果硬规则，以及「禁把『需核实』当结论句」。所以

结构类规则从 `718f5988` 一路加到 `748f36b2`，是原样保留再加码的，下面的结构结论
**很可能**仍然成立；但严格说它是在 1.0.5 那次比对上量出来的。1.0.1、1.0.3、1.0.4
新增的内容只涉及闸门怎么判读与文字准确性，而那些说法是逐条对着
`scripts/report_qc.py` 的控制流**实测**出来的（见契约 `gate_io`），
**这不是效果证据**：符合性探针只证明模型照着做了，没有一轮测过照做之后报告会不会更好。

**`b8f84e8` 的效果类数字不属于它当时对着的那个出货版本，这件事没有变。**
写这张表时出货的是 `748f36b2`：它在结构一致性上有 n=9 的证据（见上一节），
在效果上**零证据**。现在出货的是 `1.1.9`，效果类**仍然零证据**——中间没有任何一版
补上这一块。

1.0.3 的闸门比 1.0.2 严在三处，且都是 1.0.2 的缺陷：源码路径写错时**拒绝运行**
（原来照跑并打印 `PASS`、零 note）、不带源码时**明说**三项诊断没跑（原来静默跳过）、
报告与源码按扩展名分工而不是靠 `.abap` 后缀猜（原来会把 `.txt` 源码当报告检查，
报出一堆不存在的缺陷）。这一版还多两类检查：`fence`（未闭合围栏会吞掉后续全部内容）
与 `fix-mislabel`（`abap-fix` 围栏里逐字出自源码的语句 = 贴错围栏的真引用）。

`b8f84e8` → `718f5988` 的对比（迭代 9）回答的正是"形状缺陷有没有减少"，
判据已在生成之前预注册在上游仓库 `analyzing-programs-workspace/iteration-9-plan.md`
（不随 skill 发布），只跑过 6 格 harness 验证、主判据未执行。
它**不**回答"分析是否更准确"。

### 能声明：报告结构一致性（b8f84e8）

六节结构、三层格式、优先级分桶的通过率 **0.980 vs 无技能 0.554（+42.6pp）**，
390 个配对单元上 McNemar 精确检验 **p = 5.55e-44**（170 个仅技能通过、
5 个仅基线通过）。本 skill 的价值主张就是这套结构，在 b8f84e8 上证据充分。

### 能声明：某一版出货字节产得出闸门合规的报告（`fac4d5a3`，n=9）

同一批派发里顺手产生的 **9 份报告**，全部在 `fac4d5a3`（1.0.3）下生成，
覆盖 `flow_logic`（1114 行）与 `objects_program`（1597 行）两份真实 ABAP。
九份**全部**经发布版闸门独立复核 `PASS`、退出码 0，展开密度 1.7–2.2（下限 0.5），
无 skip note。

**这条能支持什么**：`fac4d5a3` 这版字节能产出闸门合规的报告，n=9，真实源码
1114–1597 行。**它不覆盖 `748f36b2`** —— 从 1.0.3 到 1.0.9 闸门换了六次、SKILL.md
换了九版，中间没有任何一轮在这个 n=9 的批次上重跑过。1.0.9 的形状闸门与 1.0.3
是否产生同样结果，**未测**。

`fac4d5a3` 是 1.0.3。1.0.9/1.1.0 另有一批 n=3 的当前版本证据，**与这批不可合并**——
程序不同（`zvend.abap` 356 行 vs 这里的 1114–1597 行），派发条件不同（盲判 vs 单批）。
两批各自成立，凑不出更大的 n。

能说的还有一条更窄但能直接验的：1.0.9 自己那份 476 行的 SKILL.md 与
`references/example-report.md`，对 1.0.9 自己的闸门是 `PASS`、退出码 0，
`test_skill.py` 有两项专门守它（`the shipped example report still passes`
不带源码，`...against its own source` 带 `zbc_show_error_log` 源码）。
那是 n=1，但它是当前版本上唯一有的一条。

**这条不能支持什么**：

- **不能**支持任何"比不带 skill 更好"的结论 —— 单臂，无 baseline 对照。
  上面那个 +42.6pp 才是带对照的数，而它属于 `b8f84e8`。
- **不能**支持任何关于准确率、召回、缺陷发现率的断言。
- **不能**当完成率断言：这 9 份里有一批是刻意选了写得完的输入。

原始报告留在上游仓库 `analyzing-programs-workspace/`（不随 skill 发布），
对应两轮符合性探针与完成率第三、四轮。

### 1.1.0 的闸门变严了，效果仍然未知

1.1.0 给闸门加了五条强制检查：编造源码、问题行写空话、三层写同一句、删光 Mermaid、
散文坏字节，以前都能拿到 `PASS`。现在不能。

**这些改动不产生任何效果证据。** 它们改的是闸门能拦住什么，不是报告分析得好不好。
本 skill 的效果至今没有一轮测出过结论——最近一轮是 n=3 的盲判，结论是**不支持假设**
（两臂各 1/3 达到满档，10/12 vs 9/12），详见 `analyzing-programs-workspace/exp-1.0.9/`。

### 一条比召回数字更该先看的东西：这套缺陷集的区分度

1.0.9 那轮 n=3 盲判里，21 条缺陷有 **7 条（33%）在六次判定中完全一致**——两臂三次
都判 `yes`，或都判 `no`。剩下 14 条才有区分空间。

也就是说整体 recall 的差距（技能臂中位 1.476 / 基线臂 1.333）**主要由生成噪声决定，
不是由 skill 决定**。两臂的 yes 数序列是 [15,14,17] 与 [13,14,17]，几乎重合。

同一条缺陷在**同一臂的不同次里**可以判 `yes` 也可以判 `no`（D16 是 yes/yes/no，
D21 是 yes/yes/partial）。任何 n=1 的对比都在测噪声。这条应该排在所有召回数字前面读。

### 不能声明：分析更准确

对 77 条植入缺陷的召回，**技能 0.849 vs 基线 0.826（+2.3pp）**，
符号检验 9 高 / 8 低 / 9 平，**p = 1.000，不显著**。

评委层已经饱和：77 条里 **46 条（60%）两臂都得满分**，没有区分空间。
剩下 21 条能动的里技能赢 12 条、输 9 条 —— 方向上没输，
幅度却相互抵消到不可分辨。

### 站得住的失败：3 条（两次运行都更差）

| 缺陷 | 领域 | 技能 run1 / run2 | 基线 run1 / run2 |
|---|---|---|---|
| eval-4-D2 | 可编译性 | no / no | partial / yes |
| eval-9-D2 | CDS 语义 | partial / partial | yes / yes |
| eval-9-D6 | HTTP 资源 | partial / partial | yes / yes |

三条都是**只读源码就能判定**的缺陷：`RAISE EXCEPTION TYPE cx_sy_no_data`
（`CX_SY_NO_DATA` 是数据对象不是异常类，语法检查过不了）、CDS DDL 里写
`cast(sy-datum …)`（ABAP 运行时字段，DDL 里不成立）、多条早退分支都没调
`lo_client->close()`（连接不归还池）。它们不需要 SE38，不需要运行时语义。

值得注意的是 b8f84e8 明确写了「指出真实问题，不回避缺陷」。
所以这是**指令说了但没做到**的案例。成因没有定论 ——
2×2 的单元数不足以归因，这也是为什么该结论要留给下一轮去测。

### 不要当成失败：6 条只在单次运行上更差

eval-11-D2、eval-5-D5、eval-7-D1、eval-8-D1、eval-12-D2、eval-1-D4
各只有 1 次运行更差，另 1 次是平局或更好 ——
eval-7-D1 另一次是技能 yes、基线 partial，即技能更好。

同设计三次运行给过 0.605 / 0.645 / 0.737（SD 0.068）。
n=2 下单次差异与噪声不可分辨。**交付时按 3 条读，不按 9 条读。**

### 两条两臂全失：改 skill 无用

eval-10-D2（条件提交 `IF p_commit EQ 'X'` 导致后台作业整轮 `MODIFY marc`
随工作单元回滚，作业显示成功但一条都没落库）与 eval-13-D6（对**数值型**字段
用 `W = 12` 编辑掩码，且表头是硬编码文字而非可翻译文本元素）——
两臂两次运行全是 no。这是分析方法层的缺口，不是措辞问题。

### 所以怎么交付

按「结构化 onboarding 报告工具」交付，附本清单；**不要**按「分析更准确」交付。
后者没有正向证据，还有 3 处稳定的反向证据。

要支撑后者，得把评委清单的难度提到能区分两臂（46/77 饱和是根因）——
那不是采集更多数据能解决的：加缺陷条目无效已在当前取样下证明，
记录该次尝试的文件在上游仓库 `Test-result/noise-reduction-failed.md`
（不随 skill 发布）。

## 更新记录

只记闸门与脚本的行为变更，不记分析报告的内容。每一版都归档在 `release/`，
digest 见 `release/SHA256SUMS`。

### 1.1.17 复审 → 1.1.18 修复

6 组探针 + 4 组契约/文档一致性扫描，9 条发现。**下面九条在 1.1.18 里全部修完**，
修复记录见本节末尾。

**P1**

**1. `exit 2` 会跟在一条已经打出来的 `PASS` 后面 —— SKILL.md 的这句承诺为假。**
SKILL.md「闸门输出」的触发条件表（第 115 行）写着：「给多份报告时，所有路径
先校验完才读第一份，所以 `2` 不会跟在一条已经打出来的 `PASS` 后面。」这句只对
**路径存在性**成立。`read_report()`（`scripts/report_qc.py:314`）里另外两个拒绝
条件仍在循环内触发：`os.path.isdir()`（:323）和 `UnicodeDecodeError`（:332）。

```
$ report_qc.py good.md bad-gbk.md src.abap
  PASS  good.md
  error  bad.md is not readable as utf-8 ...
$ echo $?   →  2

$ report_qc.py good.md adir.md src.abap
  PASS  good.md
  error  adir.md is a directory, not a report file, so nothing was checked
$ echo $?   →  2
```

目录那条消息本身也自相矛盾：上一行刚打完 `PASS good.md`，这行说
「nothing was checked」。形状模式和 `--fidelity-only` 都复现，两个条件都复现。
契约 `gate_io.exit_codes["2"]` 开头那句「In every trigger except the `--fix`
write refusal below, nothing was inspected」同样为假，而 1.3.9 那条修订只把范围
收窄到「a report path does not exist」。27 条 gbk 测试全是单报告，循环位置
从没被踩到。修法现成且改动小：循环前把每个报告路径的 isdir / 可解码性先过一遍，
不用先读内容。

**2. `abap_deps_analyzer` 的 `exit 1` 是死代码，摘要里两行恒为 0。**
全脚本只有 4 处 `Issue(`（`:298 :315 :337 :353`），`severity` 的取值集是
`{'info'}`，所以 `:469` 的 `summary['errors']` 恒为 0、`:611-612` 的
`sys.exit(1)` 到不了、`:508` 那个 `❌ error` 分支也是死的。实测
`zalvtree.abap`：2 个待确认引用、`错误: 0  提示: 2`，rc=0。

也就是说这个分析器跑完永远退 `0`，不管查到几条 —— **只看退出码的调用方会把
「2 条待确认」读成「什么都没查到」**。SKILL.md 第 129 行「`1` 的意思是
『查过了，有缺陷』」说的是 `report_qc.py`（第 101 行开头限定了对象），但读者
会顺手套到第三个脚本上；摘要里 `错误 / 警告` 两行恒 0 是同一个坑的另一种表现。
修法两选一：让 severity 真的分级；或删掉 exit-1 分支并在 SKILL.md 明写「分析器
完成即退 0，结论只在正文」。建议后者 —— 现在没有任何调用方依赖 `exit 1`。

**P2**

**3. `docgen --validate` 校验不了已经存在的文档。** 它只校验自己刚生成的产物：
给一份手写文档当 source，它把这份 markdown 当 ABAP 去解析、再生成一份
onboarding 文档、然后说 PASS。契约 `document_types[*].validated_by` 把这条命令
标成该文档类型的校验器，但校验器只读 docgen 的新输出 —— 手写了一份类文档的人
没有受支持的校验路径。

**4. `docgen` 把目录报成「不存在」。** `scripts/docgen.py:52-53`（1.1.17 的代码；
1.1.18 里已改成 L52 `if path.is_dir()` 单独判断，`path.is_file()` 下移到 L58）用
`path.is_file()` 判断，目录得 False，于是报 `source path does not exist: <目录>`。
姊妹脚本 report_qc 有专门的 `is a directory, not a source file`（1.1.16 就是为它
改的）。同一份输入，两个脚本两种拒绝方式。

**5. 空源码在 `docgen` 里能过。** `docgen empty.abap --type onboarding --validate`
→ rc=0 PASS；`--type table` → rc=0 PASS；`--type class` → rc=1（3 条缺陷）。
一个不存在的程序生出来的 onboarding 文档被判合规：校验器只查结构，不查这份
文档有没有在讲东西。

**P3**

**6. `validate_json` 完全不读契约开关。** `scripts/checks/docgen.py:145` 只硬编码
`required_fields`；那 7 个开关（`required_sections` / `sections_exactly_once` /
`code_fences_closed` / `no_line_numbers_in_labels` / `mermaid_safe` /
`tables_well_formed` / `encoding_utf8`）全是 markdown/html 路径在读。一个开关管
三个格式，其中一个是静默生效的，契约里没写这层差别。

**7. 零引用的报告在 `--fidelity-only` 下静默 PASS。** 有源码、但没有一条引用代码
的报告，忠实度在空集上跑完：rc=0、`PASS`，一行提示都不打。形状模式在「没有源码」
时会打 note（density / fidelity not run），而「报告里根本没有可比的东西」这个更
该提示的情况什么都没有。1.3.7 那轮为「没有分母就读不出」加了 denominator note；
M=0 时连这一行也没有。

**8. `-o` 写在 `--fix` 之外会被当成源码。** `report_qc.py r.md src.abap -o out.md`
→ `error  more than one source: src.abap, -o (pass exactly one)`。确实拒绝了，
但消息把 `-o` 报成一个源码、把 `out.md`（真正的报告）并入报告列表；最可能的原因
—— `--fix` 写漏了 —— 没点出来。

**9. SKILL.md 第 113 行把目录的消息写成了源码版的。** 实际报告路径报的是
`is a directory, not a report file`，源码路径报 `is a directory, not a source file`。
表格里引号里只有后者。

**本轮同时确认没问题**：`--fix` 的两条新拒绝消息、`.bak` 已存在时不覆盖、
`-o == source` 带 `./` 噪声也能拦、docgen 那 7 条拒绝消息全在契约里
（上一轮报过「不在任何文档」，是匹配方式的假报警）、`-o` 指向已存在的文件、
`-o` 指向 cwd 本身（落默认文件名）、`evaluate.py` 无参仍是 rc=2。

### 1.1.18：九条的去处

| # | 修法 | 落在哪 | 谁守着 |
|---|---|---|---|
| 1 | 报告路径的**可读性**（是目录 / 不是 UTF-8）也提到循环前，形状模式与 `--fidelity-only` 两处都改；存在性检查不动 | `scripts/report_qc.py` 两处的 `read_report()` 前 | `test_gate_enforcement.py` PROBE 8（2 条件 × 2 模式 = 4 条） |
| 2 | 删掉到不了的 `sys.exit(1)`，并把「摘要里错误/警告恒 0」写进 SKILL.md，不再让人去等一个不会来的 `1` | `scripts/abap_deps_analyzer.py`、`SKILL.md` 退出码表 | `test_docgen_deps.py`「the analyzer exits 0 even when it has findings to read」 |
| 3 | `--validate` 拒绝 `.md` / `.markdown` 源码，并指向 `report_qc.py` | `scripts/docgen.py` `_read_source()` | `test_docgen_deps.py`「refuses a markdown source」+「names where the document does get graded」 |
| 4 | 目录单独判断，报 `is a directory, not a source file`，不再落到「not found」 | `scripts/docgen.py` `_read_source()` | 「docgen names a directory as a directory」 |
| 5 | 空源码三种类型一律拒绝 | `scripts/docgen.py` `_read_source()` | 三条「refuses an empty source with --type …」 |
| 6 | 契约 `validation._comment` 写明 7 个开关只对 markdown/html 生效；`validate_json` 的差别记在 `document_types[*].validated_by` | `schemas/docgen-contract.json`（1.0.1 → 1.0.2） | —（契约内自述，闸门不读这段） |
| 7 | 零引用时打一条 note：`no quoted source statement`，形状模式与 `--fidelity-only` 都覆盖 | `scripts/checks/fidelity.py` | PROBE 8 后两条 |
| 8 | `-o` 出现在 `--fix` 之外直接拒绝，消息点名 `--fix` 要写在行首 | `scripts/report_qc.py` `main()` 分发前 | PROBE 8「-o outside --fix is refused and the cause is named」 |
| 9 | 目录消息按角色分开写：报告是 `not a report file`，源码是 `not a source file` | `SKILL.md` 触发条件表、`gate_io.directory_as_source.prints` | `test_contract_drift.py` 的 `skill_anchor` 断言 |

测试：**532 项全绿**（drift 124 / gate_enforcement 34 / fidelity_tiers 7 /
skill 241 / docgen_deps 126），新增 24 条。修 3 时发现两处**测试自己也不对**，
一并改掉：`--validate` 开关那组测试是靠「把生成出来的 `.md` 再喂回去当源码」
才能测通开关，正撞第 3 条；`required_sections` 的那条扰动量
`# unrelated\n\nnothing here\n` 根本触不到任何检查，开关关不关它都是 PASS——
也就是说那条开关从来没被真正验证过。现在直接调 `validate()`，每条开关配一个
真的能触发的对照组。

契约 `1.3.9 → 1.3.10`、docgen 契约 `1.0.1 → 1.0.2`，`ships_with` 与
SKILL.md frontmatter 一起移到 `1.1.18`，已归档在 `release/analyzing-programs-1.1.18/`（407 文件、31 目录）；
zip 的 sha256 在 `release/SHA256SUMS`，打包提交晚于本文件所以不写。

### 1.1.21 → 1.1.22：拒绝之前不再打印任何东西

契约不动（1.3.10）：没有规则、阈值或 `gate_io` 行变化，只有 `ships_with` 走。
SKILL.md 541 → 546 行。

**`recon.py` 现在先跑 docgen，再写 dump。**1.1.21 的顺序是校验源码、打印整份
编号源码、然后才跑 `docgen.py`。所以 docgen 一旦拒绝，或者报了成功却没写出文件，
**整份源码已经全部打出去了**。量在最大的那个语料文件上：29564 行、1517397 字节的
输出，读的人已经花掉整个上下文，才看到 `error  docgen exited 2`。

这和 SKILL.md 自己写下来的话也是两件事。第 2 步说拒绝时「不先打出半个源码」——
源码那五条拒绝确实如此，docgen 那两条不是。而且给的不是半个，是整份：**半个 dump
读起来像中断，整份 dump 读起来像一个已经完成的产出**，比半个更容易被当成结论。

改法是把 docgen 挪到打印之前。这个顺序本来就是为了让 header 里的总数算得出来——
清单在手，总输出才可知。两件事是同一个改动。

**header 第二行现在给出这次会打印的总字节数。**
`== 265 line(s), 8306 bytes, utf-8 ok, output 12081 bytes, inventory 1333 bytes`。
按字节算，不按字符：中文注释一个字是三个字节，按字符算会少报 500 多字节。
这个数只是数，不是阈值。`references/large-inputs.md` 第 3 行写着「这是观察，不是
规则」，第 17 行写着「不要按文件大小决定要不要担心」，所以这里不给「超过多少就走
分块路径」。给数，让读的人自己掂量。

**补上 1.1.21 那套测试漏掉的那条。**当时 stub 循环只断言了退出码和报错文字，
没断言「拒绝前没有编号行」，所以整份源码打出去再报错，套件是绿的。新增四条：
header 的总数与实际送出的字节数逐个对上；字符数不出现在 header 里；
docgen 的两种拒绝各自都不留下一行编号源码。

`tests/test_skill.py` 283 → 287 项，五个套件合计 588 项全绿，`_comment` 增到 313 条。

**顺带修掉一句说反了的话。**SKILL.md 第 6 步原先写着「闸门**不会**自己定位规则集
（`abap_deps_analyzer.py` 会，`report_qc.py` 不会）」——括号里两个正好说反了。
量出来的：把整个包拷出来、删掉 `schemas/`、脚本按绝对路径调用、cwd 放到无关目录，
报错路径指向副本自己的位置（`scripts/checks/../../schemas/report-contract.json`）；
`abap_deps_analyzer.py` 同理按 `Path(__file__).resolve().parent.parent` 索引成功。
两个脚本都自定位。真正要求 cwd 的只有 `python scripts/...` 这种相对写法本身。

### 1.1.22 → 1.1.23：四条没有测试守着的拒绝路径

契约不动（1.3.10）：没有规则、阈值或 `gate_io` 行变化，只有 `ships_with` 走。
SKILL.md 仍是 546 行——只动了 frontmatter 的 `version`。

`tests/test_skill.py` 287 → 311 项。新增的 24 项里有 4 项第一次跑就失败：
3 项是测试写错，1 项是 `recon.py` 自己的缺陷。

**一、`recon.py` 违背了自己文档里的「没有 exit 1」（已修）。**
它的 docstring 写着退出码只有 `0` 与 `2`——它不判报告，没有东西可报成缺陷，
把每个非零退出码都当成「查出缺陷」的调用方会去修那些从未被检查出来的缺陷。
这句话有个洞：读回 docgen 写出的文件用的是没有守卫的 `read_text()`。
docgen 写了不是 utf-8 的字节，`UnicodeDecodeError` 就从脚本里抛出来，
打 traceback，退出 `1`。量出来：`rc=1`、有 `Traceback`、第一行不是 `error`。
**一次拒绝以崩溃的形式到达**，而 `1` 正是 SKILL.md 定义的「缺陷判决」。
所有读都加了守卫；顺带把 `doc_file.stat()` 退役了——清单大小改用已经读到手的
字节数，同一路径不再看第二次。

**二、`recon.py` 把「docgen 不存在」报成「docgen 退出了 2」（已修）。**
docgen 是按字符串路径调的，从不检查它存不存在。docgen 缺失时，退出 `2` 是
python 自己对「打不开这个脚本」的回应，recon 却照报 `docgen exited 2`——
**给一个从未运行的 docgen 编了个退出码**，读的人会去找一份不存在的诊断；
而 python 写在 stderr 里的那句原因被丢掉了，因为 recon 只转发 `child.stdout`。
现在先查 `is_file()`，缺就报 `docgen.py is not installed at <path>`。

**三、`recon.py` 只转发 docgen 的 stdout（已修）。**docgen 崩溃时 traceback
写在 stderr，于是「退出码」成了唯一交代。现在两个流都转发，**但都排在 `error`
那行之后**——否则 docgen 的 traceback 会排在 `error` 前面，recon 自己那句
「拒绝的第一行是 `error`」又变成假的。

**四、`report_qc.py` 把「读不到」报成「不是 utf-8」（已修）。**
`read_report` 与 `read_src` 都捕 `(UnicodeDecodeError, OSError)`，两种异常
同一句话。实测（icacls 拒绝读，文件本身是合法 utf-8）：

```
error  ...denied.md is not readable as utf-8 ([Errno 13] Permission denied: '...'),
so nothing was checked
```

先看到的是「不是 utf-8」，去改编码；原因其实藏在括号里。退出码 `2` 是对的，
诊断是错的。**这个坑 1.3.10 已经踩过一次**：目录会让 `open()` 抛
`PermissionError`，被同一句翻成 "not readable as utf-8"，"a reader went looking
for a BOM in a folder"——所以当时加了目录判断。**只修了目录这一种，
通用情形留着。**现在两个子句分开，拒绝读就报读不到。触发条件集没动，
所以 `exit_codes[2]` 没加东西；`directory_as_source.why_not_encoded` 同步改了，
因为它把 OSError 子句描述成会说 "not readable as utf-8"，现在不说了。

**顺手改了 `recon.py` 一个段标题。**原来写
`== SUBPROGRAM INVENTORY  (scripts/docgen.py --type onboarding)`，
指的是里面那张子程序表；但 docgen 实际写出的是一份开发者入门指南，
子程序表是七个章节之一。量出来：1334 字节、含 `FUNCTION` 的行 `0` 条、
7 个标题里 6 个与这份程序无关，两个不同程序之间 **956 字节（72–73%）逐字节相同**。
现在段标题写 `== DOCGEN OUTPUT`，摘要行那个数改成 `docgen block`——
跟收条那行的 `docgen wrote ... (N bytes)` 区分开，后者是磁盘上的文件，更大，
因为段里丢掉了末尾空白。上面 1.1.22 那节的 header 例子还写着 `inventory`、
1.1.20 那节的段标题还写着 `SUBPROGRAM INVENTORY`，两处都是当版本的记录，
按历史留着。

**4 条新测试第一次跑就失败。**3 条是测试写错：docgen stub 的转义要多一层
（stub 的正文是**另一个脚本的源码**，`\xff` 在测试里就成了那里的原始字节
0xff，stub 直接语法错误）；text 跟 bytes 比，永远不等；还有一条期待 docgen 的
收条被转发，而 docgen 是退 `0` 的，recon 不转发退 `0` 的 stdout。
**第 4 条查出 `recon.py` 自己的缺陷**：header 的总数原本跟 `text=True` 读到的
字节数比，而 `text=True` 会把 docgen 自己写进 markdown 的 `\r\n` 翻译成 `\n`，
于是 recon 声称的数比测试读到的多 **41 字节**。线上走的正是 recon 声称的 1635；
下面的 CRLF 测试早就为同样的理由按字节读——**这正是套件用字节量 dump、
却用翻译过的文本量 header 的原因**。

### 1.1.23 → 1.1.24：九条 1.1.23 没有测试守着的缺陷

契约不动（1.3.10）：没有规则、阈值或 `gate_io` 行变化，只有 `ships_with` 走。
SKILL.md 仍是 546 行——只动了 frontmatter 的 `version` 和两处措辞。

`tests/test_skill.py` 311 → 365 项，五个套件 612 → 666 项全绿。九条里
**四条是「拒绝以崩溃的形式到达」**：traceback、退 `1`，而 `1` 在本项目里
是「查过了、有缺陷」——调用方会去修一批从未被查过的东西。

**一、`recon.py` 读 docgen 时 `child.stdout` 会是 `None`（已修）。**
`subprocess.run(..., text=True, encoding="utf-8")` 没给 `errors=`：子进程写出
非 UTF-8 字节时，严格解码器把 `child.stdout` 返回 `None`，于是
`child.stdout + child.stderr` 抛 `TypeError`。量出来：`rc=1`、stdout 是空的、
首行不是 `error`。拒绝以崩溃的形式到了调用方。两个方向都修：`docgen.py` 补上
另外两个兄弟早就有的 stream `reconfigure`——它是被读的那一个，之前恰好没有；
`recon.py` 读子进程时加 `errors="replace"`，所以 `child.stdout` 永远不是 `None`。

**二、`checks/contract.py` 在 load 之后的推导里死掉（已修）。**
`json.load` 接受 `{"version": "1.3.10"}`，规则集能解析但少了 `sections`，
于是在 load 之后那段推导抛 `KeyError`，退 `1`——拿「查过了、有缺陷」的退出码
报一份只是被重排过的规则集。顶层键现在在同一个 `try` 里先查一遍，`except`
扩到 `KeyError` 与 `TypeError`：`json.load` 能返回的任何形状都被规则集那道
守卫拒绝，说的是 trigger 早就承诺的 `cannot read the rule set` /
`nothing was checked`。

**三、`evaluate.py` 假定输入就是它写代码时那个形状（已修）。**根是数组撞
`d.get`；`defects` 里一条标量撞 `x.get`；一条 verdict 的值是列表，被拿去当
dict 的键。三个都是 traceback、退 `1`。现在分别点名：
`the reference must be a json object`、`N defect(s) are not objects`、
`verdict is not a string`。

**四、`docgen.py` 加载契约时漏了 `UnicodeDecodeError`（已修）。**原来是
`except (OSError, JSONDecodeError)`：契约文件存在但不是 UTF-8，就绕过守卫成了
traceback。`ValueError` 两者都覆盖——`JSONDecodeError` 是它的子类。

**三条是「崩溃没发生，但话说不准」。**

**五、`docgen.py` 的 `_read_source` 把两个子句合成一个（已修）。**原来是
`except (UnicodeDecodeError, OSError)`：源文件存在但读不了，被报成
「不是 utf-8」。`report_qc.py` 在 1.1.23 修过同一个误诊，`_read_source` 是
第三个同样形状的读者，也是漏掉的那个。两个子句现在分开。

**六、`recon.py` 把自己拥有的 `-o` 交给 docgen 去诊断（已修）。**原来 `-o`
指错时先打 `docgen exited 2`，真原因在第二行；而 `-o` 指向一个文件时 docgen
报的是 `WinError 183`（已存在）——一个权限问题，实际是路径的种类错了。
现在 `recon.py` 先查自己的 flag 并点名：
`output path is a file, not a directory`，或
`output path is not a directory: ... (create it, or drop -o to write next to the source)`。

**七、一份没有打印字符的源被当成一行程序收下（已修）。**`.strip()` 去掉的是
空白，不是控制字节：`"\x00\x00".strip()` 非空。一份全 null 字节的文件被当成
一行程序，然后为一份不存在的程序生成了一份文档。`recon.py` 与 `docgen.py`
现在要求至少一个 `isprintable()` 的字符。

**八、`SKILL.md` 里唯一的措辞债（已修）。**它还在把 docgen 写出的那段叫
「清单」，读者照着找 `== SUBPROGRAM INVENTORY`——找的是 1.1.23 就不再出货的
那个段标题。现在写 `== DOCGEN OUTPUT`，并说明子程序表只是 docgen 那七节里的
其中一节。

**九、记下来不修的那一条。**`recon.py` 的收条会回显它收到的输出路径，所以
`output N bytes` 那个数随路径长度变，而同行的 `docgen block` 不变。总数说的是
它数的东西，只是不恒定；读者要核对的是那个不变的数，所以记进契约、不改。

另有两处按现状留着，都不属于崩溃类：`abap_deps_analyzer.py` 仍在两处用
`errors='ignore'` 解码源码（`report_qc.py` 对同一件事是拒绝），`evaluate.py`
与 `abap_deps_analyzer.py` 都没有 stream `reconfigure`——但它们都不是被别的脚本
读的子进程，所以第一条那个失效方式到不了它们。

trigger 集合没动，所以 `exit_codes[2]` 没加东西：1.1.23 时是 traceback 的那些
拒绝，现在是拒绝本身。契约 `_comment` 增到 315 条。契约 `1.3.10` 不动，
`ships_with` 与 SKILL.md frontmatter 一起移到 `1.1.24`，
已归档在 `release/analyzing-programs-1.1.24/`（408 文件、31 目录）；
zip 的 sha256 在 `release/SHA256SUMS`，打包提交晚于本文件所以不写。

### 1.1.24 → 1.1.25：四条读出来的「形状错」

契约 `1.3.10 → 1.3.11`、docgen 契约 `1.0.2 → 1.0.3`：各有一条 `gate_io` 行动了
（一条改触发措辞、一条加成员），`release.ships_with` 与 SKILL.md frontmatter
一起走到 `1.1.25`；SKILL.md 仍是 546 行——只动了 frontmatter 那两个字段。

`tests/test_skill.py` 365 → 396 项、`tests/test_docgen_deps.py` 129 → 171 项，
五个套件 666 → 739 项全绿。四条里**三条是「拒绝以崩溃的形式到达」**：
traceback、退 `1`，而 `1` 在本项目里是「查过了、有缺陷」——调用方会去修一批
从未被查过的缺陷。第四条更糟，是**静默判 PASS**：一个字都不报，读的人会以为
报告是干净的。

**一、`checks/contract.py` 的守卫只盖住前半段（已修）。**
1.1.24 把顶层键检查挪进了 `try`，但那个 `try` 包住的是「规则在不在」，
包不住「规则都在之后怎么算」——四条派生量在 `try` 之外算。
`buckets` 给个数字、`patterns` 给个字符串、`advisories` 给个空表、
`forbid_in_display_text` 给个非字符串形状，四种写法分别让派生量抛
`StopIteration`、`LookupError`、`TypeError`、`re.error` 之一，
全部 traceback、退 `1`——**规则集能解析、键也齐，只是类型错了**。
派生量现在在同一个 `try` 里，`except` 补上这四个异常名，
说的是 trigger 早就承诺的 `cannot read the rule set` / `nothing was checked`，
退 `2`。`gate_start_refuses_without_a_rule_set.trigger` 的措辞跟着改：
原来只写「missing or not parseable」，现在补上「或者某条规则在、
但类型不是派生量要的那个」。**1.1.24 那句「catch 已盖住 `json.load` 能返回的
任何形状」当时就是错的**——存在检查与派生量是两条 `try`，
它的 `_comment` 里记的是理想而不是代码。

**二、docgen 契约一道形状检查都没有（已修）。**
`checks/docgen.py` 的 `load_contract()` 读到就返回，`validate()` 直接假定形状。
根节点是 `{}`、一条规则都没有时，`validate()` 拿空章节表对着一份报告判 **PASS**——
必需章节一项不落地「通过」，因为一项都没要求；`document_types` 给个数字时
`contract.get("document_types", {}).get()` 抛 `AttributeError`，退 `1`。
前者是 `--validate` 存在就是为了不给的那句假保证，而且是读的人会假定 1.0.1 那条
「契约读不到就拒绝」已经盖住的场景——读不到会拒绝，读得到但一条规则没有不会。
现在 `load_contract()` 在**读的同一个调用里**检查存在与形状：根节点必须是对象、
`document_types` 与 `validation` 必须在且是对象、`required_sections` 必须是 list、
每节的 `heading_anchor` 必须是字符串；`main()` 的 `except` 从
`(OSError, ValueError)` 扩到再加 `KeyError` 与 `TypeError`。
report 契约那道守卫从 1.2.4 就有、1.1.24 与 1.3.11 两轮都拓宽过并记在
它自己的 `_comment` 里，这份一份都没有。

**三、`has_content()`：同一个判断原来有三个互不一致的写法（已修）。**
「源码有没有内容」散在四个地方，三处各说各话：`.strip()` 去空白不去控制字节，
全 null 字节的源判「有内容」，闸门照常打分，报出**从来不是缺陷**的忠实度缺陷；
`isprintable()` 对 U+FFFD 返回 `True`，一句只有替换字符的源也判「有内容」——
而 U+FFFD 正是 `encoding` 那条规则存在的理由，于是给一个**不存在的程序**
生成了文档。现在合成一个谓词 `has_content()`，落在新增的
`scripts/checks/source.py`。
**这里有个坑值得记：**第一版把它放进 `checks/text.py`，
结果 `docgen.py` 在 `report-contract.json` 缺失时开始拿**那份契约的词**拒绝自己——
一份关于错误文件的拒绝。`source.py` 不 import 规则集，
`docgen.py` 与 `recon.py` 才能读它而不把 report 契约一起背上。
`recon.py` 另留一份 fallback 给 stub 测试那种布局（它旁边只有 `docgen.py`），
并加了一条测试把两份谓词喂同一批输入逐个比对，让它们漂不了。
三处消息对齐到 `recon.py` 早就用的那句 `no analysable content`：
`report_qc.py` 与 `docgen.py` 原来都说 `is empty`，现在三处说同一件事。

**顺带量出一件事：**`schemas/report-contract.json` 不是任何 `json.dumps` 设置
能复现的——它保留手写键序、CJK 以原始 UTF-8 存，还有一行 3 空格缩进
夹在一群 4 空格里。用 `ensure_ascii=True, sort_keys=True` 重写一遍
会动 500 行只为改 4 个值。这版的补丁是在原文上做字符串替换，只动该动的行
（两份契约各 14 与 12 行）；`docgen-contract.json` 正好相反，
`json.dumps(d, ensure_ascii=False, indent=2)` 能逐字节复现它，那份照常用 dumps。

**记录、本轮不动的五条**，都在复审那轮的量里，不是没看见：
`evaluate.py` 与 `abap_deps_analyzer.py` 都没有 stream `reconfigure`
（上一节记下的那两条，理由也还是那条：它们不是被别的脚本读的子进程）；
`--fix` 的 `-o` 指到别处会直接覆盖目标、不留 `.bak`，33 字节被 36966 字节顶掉；
`--fix` 的收条与实际改动对不上——CRLF 数 1 → 348，收条报 `repaired 0`；
`abap_deps_analyzer.py` 的 cp936 渲染失败会被报成 `rc=2`，
也就是「查过了、没有东西可报」；契约里 11 个「必须存在」的键有三个
（`gate_io`、`loop_position`、`claim_separation`）除了契约自己的存在检查与
`test_contract_drift.py` 之外没有任何读取方，闸门不读它们——所以「存在」这条
检查对它们等于检查文档自述。

### 1.1.25 → 1.1.26：那个「到不了」的理由是错的

契约不动（1.3.11）：没有规则、阈值或 `gate_io` 行变化，只有 `ships_with` 走。
docgen 契约也不动（1.0.3 / ships_with 1.1.25）：这次改的两个脚本都不属于它，
它上一次随 1.1.25 动过。SKILL.md 仍是 545 行——只动了 frontmatter 的 `version`。

`tests/test_skill.py` 396 → 399 项，五个套件 739 → 742 项全绿。
上一节记下五条、明确不动，这轮关掉第一条与第四条，其余三条记在这节结尾。

**一、失效方式到得了它们，入口只是不是子进程的 stdout（已修）。**
上一节记的理由原话是「它们不是被别的脚本读的子进程，所以那个失效方式到不了它们」。
前半句是对的，结论是错的：`abap_deps_analyzer.py` 的报告整篇是中文，它自己的
`print()` 就是那个入口。cp936 是中文 Windows 的默认 codepage，收得了 CJK，
但收不了报告里的箭头与书名号之类的符号；cp437 什么都收不了。`print()` 抛
`UnicodeEncodeError`，落在最外层那个 `except Exception` 里，打一行 error、退 `2`。
`2` 的意思是「拒绝了、没查过」——而这个运行**跑完了分析**，产出就在手里。
调用方被告知工具没跑，而它跑了、查到了东西，那些结果一个字都没送到。

量在同一份源码上（本轮没改那份源码）：默认编码 `rc=0`；cp437 与 cp936 修之前
都是 `rc=2`，修完三种都是 `rc=0`。cp936 下更麻烦：`print()` 是流式的，
前面那半截已经出去了，而且是按 cp936 编的字节——调用方拿到一小段乱码
加一个「没查过」的退出码，两种都没法用。

**二、同一个缺陷 1.1.10 修过一次，那次只把它藏了。**
1.1.10 时那个 `except` 的前缀是中文的。于是 cp437 下 handler 在**自己那两个汉字**上
抛 `UnicodeEncodeError`，traceback 顶掉诊断，退 `1`——本项目里「分析跑完了、有缺陷」
的码，而报告根本没产出。后来把前缀改成 ASCII 的 `error`，traceback 没了、
**退出码还停在 `2`**，缺陷就凭这一手活到了 1.1.26。

它也解释了上一节为什么没看出来：1.1.24 → 1.1.25 那条把 `rc=2` 注解成
「查过了、没有东西可报」，正好写反了——`2` 是拒绝，`0` 才是查过没有缺陷。
一个跑完了分析的运行被报成「查过了、没事」，和报成「拒绝了」一样都是假保证，
而后者还更符合直觉，所以没人去问。

**三、`evaluate.py` 也补上，它本来不会崩（预防性）。**
`evaluate.py` 自己的源码里一个非 ASCII 字符都没有，这个缺陷在它身上从来不会发生。
但它的 `tasks` 子命令打印的是**判分者给的缺陷参考里**的 anchor 与标识符——
那份文件是作者用什么语言写就用什么语言，而 `tasks` 是唯一打印外部文本的确定性子命令。
`recon.py` 也是源码零非 ASCII 却照样带着这个 guard，同一个理由：它打印输入源文件的内容。

**四、守这个 guard 的断言只覆盖了两个脚本（已修）。**
断言循环原来是 `("docgen.py", DOCGEN), ("recon.py", RECON)` 两项。`report_qc.py`
从 **1.1.0** 就有这个 guard——量的是 `release/` 里各版的归档，1.1.0 那份第 65 行
就是那个循环，上面的注释写的理由是「契约里的优先级桶标记是 emoji」——
**从来没有断言过**。所以后补的脚本可以静悄悄掉出去，事实上就是这样掉的：
1.1.21 给 `recon.py` 补 `newline=""` 的那 42 项新测试全是 `recon.py` 自己的，
没有一条问「别的脚本有没有」。循环现在列全五个脚本，`test_contract_drift.py`
的 `ships_with` 同步走到 1.1.26，version 仍是 1.3.11。

顺带量出来两个记错的版本号：`recon.py` 的编码 reconfigure 是 **1.1.20** 就有的
（它第一次进包的那版，两参形式），1.1.21 加的是第三个参数 `newline=""`；
`docgen.py` 的 **1.1.24** 是对的。契约 `_comment` 里那两处写的是 1.1.11 与 1.1.21，
已从归档逐个量过、改回。

**五、顺手量出一处记错四版的行数。**
SKILL.md 从 1.1.22 起就是 **545 行**。版本表里 1.1.22、1.1.23、1.1.24、1.1.25
四行全写成 546，状态块也写着 546。这轮只改状态块与新增的行，那四行留原样，
改的数记在这里。

**这一版没动的三条。**`--fix` 的 `-o` 指向已存在的文件会直接覆盖、不留 `.bak`
（33 字节被 36966 字节顶掉）；`--fix` 的收条与实改对不上（CRLF 数 1 → 348、
收条报 `repaired 0`）。两条是同一个函数的两半，要动就得把 `--fix` 的输出路径预检
与收条计数一起重写，不是加一个判断能收的活，留下一轮。契约里 11 个「必须存在」
的键有三个（`gate_io`、`loop_position`、`claim_separation`）没有任何读取方，
这条仍然成立——它属于契约设计而非本轮的崩溃类，理由与上一节相同。

### 1.1.20 → 1.1.21：给 `recon.py` 补上 42 项测试

契约不动（1.3.10）：没有规则、阈值或 `gate_io` 行变化，只有 `ships_with` 走。
SKILL.md 仍是 541 行——只动了 frontmatter 的 `version`。

**`tests/test_skill.py` 241 → 283 项，新增的 42 项全在 `recon.py` 上。**
1.1.20 发布时五个套件一条都没碰它。新断言覆盖：退出码域只能是 `0` 与 `2`；
6 条拒绝各自先打 `error  ...` 再退 `2`，且拒绝前不打出任何一行源码；
行号对齐被编号的那一行；头部报的是字节数而不是字符数；CRLF 原样保留；
清单与 docgen 写出的文件逐字一致；docgen 的两个结局——用 stub 顶替 docgen 才能触达。

**两条新测试第一次跑就失败，而两条失败都是 `recon.py` 自己的缺陷，不是测试写错。**

**一、`stdout` 被 Windows 翻译了（已修）。**`recon.py` 的 `reconfigure` 没传
`newline=""`，于是 `print()` 把 `
` 翻成 `
`：dump 每一行结尾都带 ``，
源码有没有 CRLF 都一样。按字节读一行 dump，会多出一个源码里根本不存在的字符。
而 `report_qc.py` 读源码用的是 `newline=""`（不翻译），`recon.py` 读源码用的是
`read_bytes()`（也不翻译）——**它读得对、写得错，自己跟自己不一致**：
拿它输出的 dump 去对闸门实际检查的那一行，Windows 上永远差一个字符。
加了 `newline=""` 之后，LF 源码的 `stdout` 里 `` 计数为 0，CRLF 源码的 ``
只剩源码自己那一个。

**二、守卫只证明「那个路径上有文件」（记录，未修）。**测试里的 stub 让 docgen
返回 `0` 却写了什么也没有，`recon.py` 本该拒绝，实际退出了 `0`——
因为 `-o` 指向的目录里已经躺着上一次真跑出来的同名单文件。
也就是说 `recon.py` 会把一份它没有生产的清单当成自己的产出报成功。
要修就得比对 mtime，代价是可能出现「合法运行被误拒」；
而 `recon.py` 的全部身份就是「绝不安静出错」，权衡之后留下这一条，
在测试注释里写明，不去碰一个只在特定残留条件下才触发的边界。

顺带把上一节的「四条拒绝」改成「五条」——那句话列了五项。

`_comment` 增到 312 条，`test_skill.py` 283 项，五个套件合计 584 项全绿。

契约 `1.3.10` 不动，`ships_with` 与 SKILL.md frontmatter 一起移到 `1.1.21`，
已归档在 `release/analyzing-programs-1.1.21/`（408 文件、31 目录，与 1.1.20 一字不差）；
zip 的 sha256 在 `release/SHA256SUMS`，打包提交晚于本文件所以不写。

### 1.1.19 → 1.1.20：第 1、2 步合成一轮

契约不动（1.3.10）：没有规则、阈值或 `gate_io` 行变化，只有 `ships_with` 走。

**新增 `scripts/recon.py`（5432 B），把 Analysis Flow 的第 1、2 步合成一次调用。**
它做三件事：校验源码（不是 UTF-8 / 是目录 / 是 markdown / 是空的，一律拒绝）、
把源码带行号打出来、然后把 `docgen.py` 当子进程跑一遍、读回它写出的子程序清单。
原来这三件事是三轮调用——docgen 只在 stdout 打四行回执（`Generated:` / `Type:` /
`Format:` / `Size:`），清单在文件里，所以清单还得单独读一轮。

```
== SOURCE  Test-source/zalvtree.abap
== 265 line(s), 8306 bytes, utf-8 ok
  1 | *&-----------------------------------------------------
  ...
== SUBPROGRAM INVENTORY  (scripts/docgen.py --type onboarding)
...
== docgen wrote .../zalvtree.onboarding.md (1381 bytes)
```

**退出码只有 `0` 与 `2`，没有 `1`。**它不判报告，所以没有东西可报成缺陷；
一个把「任何非零退出」都读成「有缺陷」的调用方，会去修一批从未被查过的缺陷。
五条拒绝（不存在 / 目录 / markdown / 非 UTF-8 / 空文件）全部先打 `error  ...`
再退出 `2`，**且不会先打出半个源码**——拒绝运行不能被一段看起来像结论的输出垫在前面。

**清单仍然由 docgen 生成，不是 recon 自己解析。**recon 跑子进程、读回它写的文件，
这样 docgen 的提取逻辑改了什么，写报告所依据的清单就跟着变，两者不会各说各话。

**行号用了 `split("\n")` 而不是 `splitlines()`。**后者会丢掉文件末尾的空行，
整个 dump 的编号后移一位，写出来的引用就和闸门实际检查的源码对不上。
第 1、42、265 行逐字比对过，全对。

**它按自身路径定位 docgen，不要求当前目录是 skill 根目录**——和 `report_qc.py`
正好相反，后者必须从 skill 根目录跑。SKILL.md 第 2 步的指针里写明了这条差别。

**没加检查。**`recon.py` 没有测试守着，五个套件一个都没碰它。它是薄封装：
判断逻辑是五条手写验证过的拒绝，提取逻辑在 docgen（`test_docgen_deps.py` 129 项守着）。
所以五个套件仍是 542 项全绿，计数不变。1.1.21 补上，见上一节。

契约 `1.3.10` 不动，`ships_with` 与 SKILL.md frontmatter 一起移到 `1.1.20`，
已归档在 `release/analyzing-programs-1.1.20/`（408 文件、31 目录）；
zip 的 sha256 在 `release/SHA256SUMS`，打包提交晚于本文件所以不写。

### 1.1.26 → 1.1.27：上一节记下没动的两条，都是静默丢掉已有内容

这两条同属一类：`--fix` 写一个已经存在的路径时，旧内容不留一份。

**先说改了什么：写之前先比一次字节。**目标文件已有的内容跟要写的不一样，
就先把已有内容另存为 `<目标>.bak`。原地时目标是报告本身，通常也是唯一那份；
`-o` 指向别的文件时，那个文件也可能是别人要的交付物。条件从「确实修了什么」
变成「这次写入会不会丢掉什么」：一次什么都没修出来的运行，只要它把一个别人的文件
换成了报告，同样先留备份；字节完全一样（原地零修复）就不留，
这正是原地 `--fix` 能连着跑两次的原因。`.bak` 那个路径已经存在就**拒绝写**，
文件或目录都算，报 `could not write ...`：那份备份是上一次运行留下的版本，
是退回时唯一的路，覆盖它等于把退路删掉。换行则是**逐个位置**带回去的：
报告里几处 CRLF、几处 LF，输出还是那样，不整篇统一成一种风格——
修复不该顺手把报告重存一遍。

**一、`--fix -o` 对已存在的文件静默覆盖（已修）。**上一节提了这条。
本轮重新量了一遍：`-o` 指向一个 33 字节的文件，运行完它变成 889 字节，
打印 `repaired 1 mechanical defect(s)`，退 `0`，临时目录里**一个 `.bak` 都没有**。

根在两个地方。写盘前的预检只看 `-o` 所在目录【存不存在、可不可写】，
**从不看 `-o` 本身**；另一侧备份的条件是 `dest == rep and n`——
只在原地、且确实修了一处时才写 `.bak`。两者叠一起，
`-o` 的那一半永远用不上备份，且什么都不会检出来报。
「预检只涵盖 `-o` 所在目录、从未涵盖 `-o` 本身」这句还是契约自己记的，
只是记完没动。

**二、第二轮 `--fix` 覆盖第一轮的 `.bak`（已修）。**连跑两轮原地修复，
每轮都确实修了一处，`.bak` 先是 833 字节、然后是 829 字节：
第一轮那份版本没了，没有 `.bak.2`，也没有一个字的交代。
而只有第一轮的那份才是能退回的——第二轮写下的已经是
第二轮前的文本，它没有帮你找得更早。

修法是在写之前看 `.bak` 那个路径是否已经存在，**存在就拒绝**，
文件或目录都算。之前只有目录那一形态会到达（`IsADirectoryError`，
测试里有一条），而**文件才是常态**。先拒绝再写，
与「写不出去就不留文件」是同一条线；另一侧它比「无声覆盖」少失一份。
消息仍是 `could not write ... -- nothing was written`，
`exit_codes[2]` 的触发条件一字未加，
只把「`.bak` 是目录」扩展成「`.bak` 存在」。

**三、换行不是统一，是逐个位置带回去（已修）。**恢复报告自己的换行
原来用一个布尔：报告里有没有 CRLF。于是一份 1 处 CRLF + 55 处 LF 的报告
输出成 56 处 CRLF + 0 处 LF，而回执印 `repaired 0 mechanical defect(s)`：
**报告没改动一处，文件却整篇换了换行**。

改成把每个换行带回自己的位置（修复只改行内文本，不增减行数），
所以回执与文件**在构造上**一致：1 处 CRLF + 55 处 LF 进去，
1 处 CRLF + 55 处 LF 出来，字节完全一样。这也正是上一节把这条列入未修的理由——
当时说的是「要把 `--fix` 的输出路径预检与回执计数一起重写」，
本轮就是这次重写。

**测试。**`tests/test_skill.py` 399 → 416，新增 17 项：三种换行风格
（全 CRLF / 全 LF / 混合）各要带回原换行、各要确实修到；
`-o` 写出前先救已存在的文件并比字节；`.bak` 已存在时拒绝写入。
其中两条在修复前的代码上是红的，所以它们确实是探针。
五个套件 742 → **759 项全绿**（416 + 171 + 129 + 9 + 34）。

契约 `1.3.11 → 1.3.12`：`fix_writes_a_backup` 的守卫换了、
`exit_codes[2]` 的 `.bak` 触发器扩展了，两行都是 `gate_io` 行。
`test_contract_drift.py` 的两个 pin 与两个 `_comment` 条数同步，
`verify_ship.py` 14/14，`docgen` 契约不动（1.0.3 / ships_with 1.1.25）。

**还有一条不动：契约里没有读者的三个键。**契约声明 11 个「必须存在」的键，
其中有三个（`gate_io`、`loop_position`、`claim_separation`）没有任何读取方。
这不是崩溃，而是契约设计：写入契约而不让闸门读的，
是文档还是规则。保持记录。

SKILL.md 545 → 548 行：`--fix` 那段把备份的条件、拒绝写入、换行三件事
告诉写作者的那句原来只写了「原地重写并且确实改了东西」，
与修完的守卫已经不是同一回事了，重写。`1.1.22 – 1.1.25` 四行的 546
仍然留原样，同上一节。

### 1.1.27 → 1.1.28：六个元工具，以及一个没有归档的版本

契约不动（1.3.12），只有 `ships_with` 走；SKILL.md 548 → 565 行。

这一版加的东西全是**维护 skill 本身**的，闸门不读它们，报告也不经过它们：
`lint_skill.py` 让 SKILL.md 对照 `schemas/skill-contract.json` 被机器检查——之前那套
写法纪律只存在于人眼，改一句不会有任何东西变红；`dedup.py` 找语义重复的章节；
`lift.py` 比两份 verdict 的 recall 差异并做符号检验；`security_probe.py` 用 17 组
对抗输入压 `--fix`；`index.py` 给 `references/` 建 TF-IDF 索引；`evolve.py` 挖历史
报告的 P0-P3 模式。五套新测试随之落地：41 + 33 + 35 + 37 + 25 = 171 项。

**这一版没有归档。**git 里有 `9cc86fd` 和 bump 提交 `7639efc`，但 `release/` 里没有
`analyzing-programs-1.1.28/`，`SHA256SUMS` 里也没有它的一行。下一个归档直接跳到
1.1.29，所以从 `release/` 装的人拿到的还是 1.1.27——六个元工具和五套新测试
在他们手里不存在。1.1.30 起归档恢复连续。

**提交消息里的「986 项」是错的，而且错了两个数。**`9cc86fd` 写
「759 existing + 227 new」。新的部分是 171（五个套件）加 17（`security_probe.py`）
共 188，不是 227；原五个套件在 1.1.29 又各增了些，drift 129 → 138、
gate_enforcement 34 → 41。这个 986 当时被抄进了 README 的「跑一遍」一节并活了两版。
1.1.30 换成实测值：十个套件 946 项，`run_tests.py` 另外跑两个元脚本。

### 1.1.28 → 1.1.29：`esc` —— 转义残留写成散文

契约 1.3.12 → 1.3.13，SKILL.md 565 → 587 行。

源码里用 `%_` / `+CONCAT` / 字符串拼接做转义的写法，报告有时把它写成转义残留的
字面形态——读的人以为那串字符是程序里真实存在的字符串。新增 `scripts/checks/escape.py`
（69 行）与 `esc` 缺陷类型，`esc` 进 `defect_line_prefixes`；
`test_gate_enforcement.py` 34 → 41，`test_contract_drift.py` 129 → 138。

同批的 `0243ce2` 把散落的检查入口收成一个 `run_tests.py` 和一个 `package_release.py`。
后者从 SKILL.md frontmatter 读版本号而不是从参数读——参数会是那串版本活得着的
第四个地方（目录名、zip 名、`SHA256SUMS` 条目已经占三个了）。归档 461 个 zip 条目、
sha256 `2545abab`，提交消息记的是 427 文件。

**这个包带着自己的测试 harness。**见下一节。

### 1.1.29 → 1.1.30：打包器丢掉的守卫

契约不动（1.3.13），只有 `ships_with` 走；SKILL.md 仍是 587 行，只动了 frontmatter
的 `version`。

`0243ce2` 重写打包器时，`release/pack.py` 里的 `NOT_SHIPPED = ("tests/",)` 和它旁边
的 `CRITICAL` 断言一起没了，新版只剩 `EXCLUDE_DIRS`（`__pycache__` 一类）。于是 1.1.29
把十个测试文件连同整个 harness 发进了包。

量出来的失败形态有两层。**第一层**：`--verify` 在那个 461 条目的包上照报 clean。
它只比 zip 与目录、查 digest，而这两件都真的对上了——两个文件都带 harness，461
条目两边一致，digest 也吻合。没有 NOT_SHIPPED，就没有东西可查。
**第二层**：装到仓库外才量得出危害。四个 suite（`test_gate_enforcement.py`、
`test_fidelity_tiers.py`、`test_docgen_deps.py`）在第一个 fixture 就 `FileNotFoundError`，
`test_skill.py` 与 `test_contract_drift.py` 能一路跑到最后、各只挂一条
`the exemplar's source is present`（它需要 `Test-source/real/` 里那份
`zbc_show_error_log`）。在仓库里跑是绿的，因为往上数层恰好能走到真的仓库根——
这句话 1.1.10 就写过，1.1.11 靠不发它解决了，1.1.29 把这条路重新打开。

修法是三处，全在 `package_release.py`：

1. `NOT_SHIPPED` 与 `CRITICAL` 补回，并加**双向**前缀断言。旧版只查
   `assert _p not in CRITICAL`，那是精确成员检查——`"scri"`、`"schema"`、
   `"scripts/checks/"` 全都会放行，而它们一样会删掉闸门要读的目录。现在两个方向都拦。
2. `verify()` 的目录侧改用新增的 `walk_all()`——**不过滤** NOT_SHIPPED 的遍历——
   并新增 repository-only 检查。这一步不能省：新检查要抓的正是过滤会删掉的东西，
   目录侧若也走 `walk_clean()`，被污染的包在那份视图里显得自洽，检查永不触发。
3. `ship()` 从拷贝树里 prune 掉 NOT_SHIPPED。`copytree` 的 `ignore` 按 basename
   匹配，路径前缀交给它不生效；而 zip 侧走 `walk_clean` 是干净的，目录侧若不 prune
   就会过不了自己新加的 `verify()`。

验证：`--verify analyzing-programs-1.1.29` 退 `1`，列出 11 个 repository-only 文件
（`tests/` 目录条目加十个测试）；`--verify analyzing-programs-1.1.27` 全绿退 `0`。
打包侧 461 → 450 条目，少的正是那 11 个。

**1.1.29 本身不修。**`release/` 是 append-only，`package_release.py` 拒绝覆盖已存在的
归档；而它记的那条 digest 确实对得上它自己那个带 harness 的 zip。改它等于篡改一份
已签发的归档，不如让它带着这条记录留着。`release/pack.py` 也没有删——它是 `NOT_SHIPPED`
与 `CRITICAL` 这两个名字的出处，留着当参照。

归档 450 个 zip 条目（417 文件、33 目录）。

同批把 README 同步到现状：目录清单补上 `scripts/checks/`、六个元工具、
`schemas/` 另两份契约、`abaplint-deps/` 与四份失败模式记录；「跑一遍」补五套新测试，
测试数改成实测值（drift 129 → 138、gate_enforcement 34 → 41），删掉那个 986、
补 `run_tests.py` 入口；`tests/` 一节把 1.1.10 量到的失败形态换成本轮的实测、
把 `release/pack.py` 改成 `package_release.py`；`五个脚本` 的 UTF-8 守卫改成十一个；
本表的 1.1.28 起三行与这三个节补齐。



