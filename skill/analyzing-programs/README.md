# analyzing-programs

给 ABAP/SAP 源码生成结构化中文分析报告：固定六节结构，每个引用源码的代码块后面
跟三层（做什么 / 为什么 / 风险与改进），问题按 P0–P3 分桶。

## 目录

```
SKILL.md                       规则本体（约 200 行）
scripts/report_qc.py           格式闸门：逐条列出违规位置，可自动修两类
scripts/evaluate.py            内容评分：对冻结缺陷清单判分，算召回与错误论断
references/example-report.md   完整范例（真实报告，逐字未改，闸门零缺陷）
references/large-inputs.md     大输入的实测行为（观察，不是规则）
references/README.md           范例的出处与局限
evals/README.md                缺陷参考的格式、用法与边界
evals/*.defects.json           112 条缺陷 / 6 个真实源码
tests/test_skill.py            自足检查，不依赖项目数据
tests/test_contract_drift.py   契约与 SKILL.md 的双向对齐检查
schemas/report-contract.json   闸门规则与 skill 教学锚点的唯一来源
```

## 三件工具各管什么

| 工具 | 回答 | 答不了 |
|---|---|---|
| `report_qc.py` | 形状对不对：六节、三层、四桶、无行号、Mermaid 可渲染、密度 | 分析是否正确、漏没漏 |
| `evaluate.py` | 对着冻结清单，报告漏了几条、有几条错误论断 | 判分本身对不对 |
| `tests/test_skill.py` | 上面两个还灵不灵，尤其是**拒绝**路径与退出码 | — |
| `tests/test_contract_drift.py` | 契约里的每条规则 SKILL.md 教了没有，反之亦然 | — |

**判分是模型工作。** `evaluate.py` 的 `tasks` 子命令把问题打印出来让判分者逐条回答，
`score` 与 `compare` 是确定性的。它保证参考完整、聚合正确、缺项不能冒充完整；
它不保证判分是对的。

## 跑一遍

```bash
python tests/test_skill.py                # 30 项，自足
python tests/test_contract_drift.py       # 34 项，契约 <-> SKILL.md 双向对齐
python scripts/report_qc.py REPORT [SOURCE]                    # 格式
python scripts/report_qc.py --fix REPORT SOURCE -o OUT         # 格式 + 自动修两类
python scripts/evaluate.py tasks  --defects evals/zcl_fi_toolkit.defects.json
python scripts/evaluate.py score --defects D.json --verdicts MY.json
python scripts/evaluate.py compare --defects D.json --a V1.json --b V2.json
```

**退出码是契约的一部分。** 所有模式在仍有缺陷时返回非零，包括 `--fidelity-only`
与 `--fix` —— SKILL.md 第 6 步让模型"重跑到干净为止"，那条循环只能靠退出码终止。
两个脚本都自己把 stdout 重配为 UTF-8：契约里的优先级桶标记是 emoji，
在默认 cp936 的 Windows 控制台上打印会抛 `UnicodeEncodeError`，
而且是从缺陷循环里抛的，诊断信息会被 traceback 顶掉。
Windows 上不需要设 `PYTHONUTF8`。

自动修只做两类改不动的判断：位置标签写成行号 → 改成最近的前置构造名；
Mermaid 标签里的裸 `<` `>` `#` → 改成全角。三层缺失**只报位置不修**，
因为那需要判断后面的散文本该属于哪一层，猜错会把风险论述标成"做什么"。

## 两条实测边界

- **20 条缺陷的配对比较分辨不出小效应。** 低于约 30 个百分点记作**未测量**。
  同一 skill 同一文件重判，召回在 0.625–0.700 之间动。
- **大输入下预期一次任务写不完。** 失败都死在第三节内部，且与文件大小无关。
  截断的报告比缺失的更危险 —— 它还是文件、会被计数。详见
  `references/large-inputs.md`。
