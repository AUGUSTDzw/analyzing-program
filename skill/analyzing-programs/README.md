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
python tests/test_skill.py                # 38 项，自足
python tests/test_contract_drift.py       # 35 项，契约 <-> SKILL.md 双向对齐
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

## 能声明什么，不能声明什么

这一节限定交付范围，不是免责声明。原始数据在
`analyzing-programs-workspace/iteration-8/`（上游仓库，不随 skill 发布）。

### 先说版本：下面的数字不是出货版本的数字

iteration-8 的全部数字都是在 **`b8f84e8`**（162 行）上测出来的。
**出货版本是 `718f5988`（215 行），它从未被端到端测过。**

| | b8f84e8（已测） | 718f5988（出货，未测） |
|---|---|---|
| 六节结构 / 三层格式 | 有 | 有（原样保留并扩充） |
| 第 6 步：写完后只修引文的独立一轮 | 无 | 有 |
| 事实性纪律章节 | **无** | 有 |
| 逐字符忠实、不展省略的代码块规则 | 部分 | 有 |
| 范例报告 / schemas / 评分脚本引用 | 无 | 有 |

结构类规则在 718f5988 里是原样保留再加码的，所以下面的结构结论
**很可能**仍然成立；但严格说它属于前一个版本。

`b8f84e8` → `718f5988` 的对比（迭代 9）回答的正是"形状缺陷有没有减少"，
判据已在生成之前写死、尚未执行；那份预注册计划（iteration-9-plan.md）已随
删除事故丢失，未重建。它**不**回答"分析是否更准确"。

### 能声明：报告结构一致性（b8f84e8）

六节结构、三层格式、优先级分桶的通过率 **0.980 vs 无技能 0.554（+42.6pp）**，
390 个配对单元上 McNemar 精确检验 **p = 5.55e-44**（170 个仅技能通过、
5 个仅基线通过）。本 skill 的价值主张就是这套结构，在 b8f84e8 上证据充分。

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
记录该次尝试的文件已随删除事故丢失，未重建。


