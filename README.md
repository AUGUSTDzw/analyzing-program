# analyzing-programs

给 ABAP/SAP 源码生成结构化中文分析报告的 skill 及其度量环境。

**skill 本身的文档只有一份：[`skill/analyzing-programs/README.md`](skill/analyzing-programs/README.md)。**
那份 README 是规则本体、闸门语义、测试计数、版本谱系与证据边界的唯一出处。
本文件只做仓库地图，不重复那些数字——重复过一轮之后，这里的 6 处数字
（测试项数、SKILL.md 行数、出货版本号）和目录清单（列了 5 个只存在于
`research/` 的 references 文件）全都漂了，而 skill README 那份是对的。

## 目录

| 路径 | 是什么 |
|---|---|
| `skill/analyzing-programs/` | **skill 本体**。SKILL.md、闸门与评分脚本、契约、评测集、测试。发版来源 |
| `release/` | 已归档产物。每个版本一个 zip + 一个解包目录 + `SHA256SUMS` |
| `research/` | 未发布开发线的快照（`unreleased-root-tree/`）。不是 skill，不随 skill 发布 |
| `Test-source/` | 真实 ABAP 语料：开源 ABAP 库、SAP 示例、教学代码 |
| `Test-result/` | 历轮派发产出的报告、裁判结论与汇总（含判分 JSON） |
| `analyzing-programs-workspace/` | 上游实验仓库的副本：迭代目录、基准脚本、预注册计划 |
| `evals/` | 早期评测集（`evals.json` + 植入缺陷语料）。与 skill 内的 `evals/` 是两套东西 |
| `diff_claims.py` | 开发期脚本：对每份报告逐个列出 `_claims()` 判定变化的行 |
| `sweep_fidelity.py` | 开发期脚本：把归档报告全量过一遍忠实度诊断，记录结论 |
| `sweep_result.json` | 上面那次 sweep 的原始结果 |

## 改 skill 后怎么验证

```bash
cd skill/analyzing-programs
python tests/test_skill.py           # 115 项
python tests/test_contract_drift.py  # 105 项
```

两项都绿再发版。计数以 skill README 为准，不在这里重复。

## 发版

`release/` 里的产物一律 `git archive` 自 `skill/analyzing-programs/` 生成，
digest 记在 `release/SHA256SUMS`。zip 与解包目录应当逐字节一致——换行符会
破坏这一点，所以仓库有 `.gitattributes` 把文本文件统一成 LF，
且 `*.zip` / `*.pyc` 标成 `-text`（zip 是发布物，被当成文本重编码会让 SHA256 失效）。

## 能声明什么，不能声明什么

按「结构化 onboarding 报告工具」交付，**不要**按「分析更准确」交付。
后者没有正向证据，还有 3 处稳定的反向证据。完整论证、
数字对应的确切版本与协议标签、以及哪些失败不能当失败读，
都在 [`skill/analyzing-programs/README.md`](skill/analyzing-programs/README.md)
的「能声明什么，不能声明什么」一节。
