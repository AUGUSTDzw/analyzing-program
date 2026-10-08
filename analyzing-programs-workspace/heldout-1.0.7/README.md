# 1.0.8：留出集暴露的「看到了但没推到底」

2026-10-08。来源是 `zvend` 留出集的失败样本。

## 实验：同一个程序，两条臂，21 条冻结缺陷

- 源码 `Test-source/zvend.abap`（357 行，10 个方法，SALV 报表）
- 缺陷集 `skill/analyzing-programs/evals/zvend.defects.json`（21 条，2026-10-02 建立，本次首次打开）
- 两个**全新上下文**的 subagent 各写一份报告：一个加载 SKILL.md，一个明确不使用任何规范
- 第三个 subagent 盲判，**不知道哪份用了 skill**

为什么必须是 subagent：写 without_skill 臂的人不能是我自己——skill 已经在我上下文里，
无法"卸载"。这是这条设计里唯一无法妥协的条件。

## 结果：测不出差别

```
                       yes  partial  no   weighted
A (with_skill)           12       7   2     1.476
B (without_skill)        13       7   1     1.571
差值 (A - B)                         -0.095
9 条判定分歧：A 胜 4 | B 胜 5，精确二项双侧 p = 1.0000
```

**p=1.0 说明 4:5 和 5:4 分不出。** 单元数太少。按项目自己的规矩
（契约 `magnitude_is_unmeasured`：单元数少就不写幅度），这一轮**既不能支持
"skill 提升召回"，也不能支持"skill 降低召回"**。

报告规模：A 1028 行 / 110 KB（闸门两道 exit 0，六节 6/6，28 组三层，2 张 Mermaid）；
B 739 行 / 51 KB（六节 1/6，0 组三层，无 Mermaid）。

**结构收益是真的，内容收益测不出来。**

## 但 9 条分歧的形状一致

这是本轮唯一有价值的产出。逐条看 A 的证据原文：

| 缺陷 | A（with_skill）写的 | B（without_skill）写的 |
|---|---|---|
| D18 硬编码位图 | 「是硬编码的外部依赖，属于跨行业遗留」 | 「缺失/无权限时无保护」 |
| D16 INCLUDE 在方法体 | 「保留了 INCLUDE <color> 这类老写法」 | 「已过时，无必要」 |
| D19 区间判空 | 「s_bedat-low 为初始时 WRITE 会输出 00/00/0000」 | 「对内表做 IS NOT INITIAL 判定的是整条区间」 |
| D21 授权 | 「不做权限控制、不做公司代码级数据隔离」 | 「无 AUTHORITY-CHECK，任何人可看全量供应商数据」 |

**左边都"看到了"。** 标识符被点名了，事实也说对了。但都停在了**描述**，
没推到**后果**——读者拿不到能行动的信息。

被判 partial 的七条里，两种病型：

- (a) 停在现象、给不出结论：D1/D8/D15。三次用「需在 SE11 核实」或
  「只是选型洁癖，不影响运行」收尾——**结论被悬空了**。
- (b) 点到名词、不追机制：D16/D18/D19/D21。

只有 D6（JOIN `EKKO`+`EKPO` 后 WHERE 裸字段名的二义性）是真正的知识缺口——
那需要 Open SQL 的字段消歧规则，skill 里没有。

## 据此改的三处（1.0.8 / 契约 1.2.5）

1. **第三层硬规则**：每写出一个具体标识符，必须紧跟一句它的运行期后果；
   只有名词没有后果不算写完。自检动作是把第三层的反引号逐个过一遍。
2. **禁「需核实」当结论句**：先给基于源码可判的推理，再补「需核实」。
   判据是"能不能只靠源码读出来"。
3. **两条新 note**（契约 1.2.5）：`authz`（取了数据却全文无 `AUTHORITY-CHECK`）、
   `ext-asset`（位图/图标名写成字面量）。两条**只在报告没给出后果时才发**。

### 第三条踩过一次坑

`authz_note` 初版把"报告里出现 `权限控制`"当作"报告已回答"。结果 with_skill
报告那句「不做权限控制」正好命中，note 被吞——**而那恰恰是被判 partial 的原句**。

改成要求后果陈述（越权 / 看到全量 / 任何能运行…）之后 note 才在该发的时候发。
教训：**提到话题不等于回答**。这与 1.0.7 记下的"闸门只查标签在不在"是同一类问题。

## ⚠️ 这三条是假设，不是测量结果

全部从失败样本反推。**目前没有任何证据**说它们会让那 4 条 partial 变 yes。

验证方案（未做）：改完重跑 `zvend`，每臂 3 次，看 D16/D18/D19/D21 是否稳定变 yes。
成本约为本轮的 3 倍。

## ⚠️ 本实验的方法论缺陷

1. **每臂只跑一次。** 单次生成的方差完全未知，4:5 的分歧可能就是噪声。
2. **缺陷集区分度不够。** 21 条里 12 条两臂同档，其中大量两边都是 yes。
   应该专门挑"两臂会分歧"的条目，否则跑了也测不出差别。
3. **判官仍是我派的 subagent。** 它读到了 21 条清单（那是必须的），但没读我的分析。
   不等于独立人类判官。
4. **`without_skill` 臂不是"无 skill 的模型"。** 它是"不加载 SKILL.md 的同一个模型"。
   与训练阶段是否见过 ABAP 规范无关。

## 产物清单

| 文件 | 说明 |
|---|---|
| `with_skill/report.md` | A 臂，1028 行，闸门两道 exit 0 |
| `without_skill/report.md` | B 臂，739 行，闸门 25 defect |
| `judge-A.json` | A 臂判分，21 条带 `report_line` + `quote` |
| `judge-B.json` | B 臂判分，同上 |

判分文件的 `report` 字段已改为**仓库相对路径**。历史上
`analyzing-programs-workspace/iteration-*/judge/*.json` 存的都是绝对路径，
换机即失效，只能靠 `--legacy` 绕过引用校验；新文件不该这样。

复现：

```bash
python skill/analyzing-programs/scripts/evaluate.py score \
  --defects skill/analyzing-programs/evals/zvend.defects.json \
  --verdicts analyzing-programs-workspace/heldout-1.0.7/judge-A.json \
  --report analyzing-programs-workspace/heldout-1.0.7/with_skill/report.md
```

（不需要 `--legacy`，引用已逐条校验。）
