# 1.0.9 效果实验：不支持假设，也不构成反对

预注册见 `prereg-1.0.9-effect.md`（写在跑之前，见结果后未改）。

## 问题

1.0.8 从 `zvend` 留出集的失败样本反推出三条改动：第三层运行期后果硬规则、禁把
「需核实」当结论句、新增 `authz` 与 `ext-asset` 两条 note。上一轮（1.0.8，n=1）
这三条没被验证，只是被写进了 skill。

**假设**：它们能让上一轮被判 `partial` 的 D16 / D18 / D19 / D21 稳定变 `yes`。

## 设计

- 源码 `Test-source/zvend.abap`，21 条冻结缺陷不变
- **1.0.9 臂 3 次**、**without_skill 臂 3 次**，六个全新上下文的 subagent
- 报告打乱顺序复制成 R1–R6（种子 20261009），映射封存在 `SEALED-mapping.txt`，
  判官拿不到
- 判官盲判六份，逐份判完不回头改，每份都要过 `evaluate.py` 的引用校验（exit 0）
- 六份 with_skill 报告的 fidelity 与形状闸门均 exit 0

## 结果

六份的真面目：

```
编号   臂               run   yes  part  no  weighted
R1   with_skill      run3   15     1   5     1.476
R2   without_skill   run2   13     2   6     1.333
R3   with_skill      run1   14     3   4     1.476
R4   without_skill   run1   14     0   7     1.333
R5   with_skill      run2   17     2   2     1.714
R6   without_skill   run3   17     1   3     1.667
```

### 主判据：目标四条

```
臂              run      D16    D18    D19    D21   yes/4
with_skill     run3     yes    yes  partial   yes     3/4
with_skill     run1      no    yes    yes    yes     3/4
with_skill     run2     yes    yes    yes    yes     4/4
                    合计 10/12

without_skill  run2     yes    yes     no    yes     3/4
without_skill  run1     yes    yes     no    no     2/4
without_skill  run3     yes    yes    yes    yes     4/4
                    合计  9/12
```

**两臂各有 1/3 达到 4/4**，三次合计 10/12 vs 9/12 —— 只差一次翻转。

### 次判据：21 条整体

```
with_skill      weighted 1.476 1.476 1.714   中位 1.476   yes [15,14,17]
without_skill   weighted 1.333 1.333 1.667   中位 1.333   yes [13,14,17]
```

### 区分度体检

**21 条里 7 条（33%）六次判定完全一致。** 两臂的 yes 数序列
[15,14,17] 与 [13,14,17] 几乎重合，整体 recall 的 0.14 差距主要由生成噪声决定。

臂内方差肉眼可见：with_skill 的 D16 是 `yes/yes/no`，D21 是 `yes/yes/partial`；
without_skill 的 D19 是 `no/no/yes`。**单次生成的结果不可靠。**

## 结论

- **不能说这三条改动有害**：10/12 vs 9/12，方向甚至略微有利
- **不能说它们有效**：两臂各 1/3 达到满档，差异只有一次翻转
- **能说的**：上一轮那个"with_skill 在四条上全判 partial"的形态**没有复现**——
  1.0.9 臂三次最差也是 3/4。方向一致，但幅度不可信
- **能说的**：预注册在跑之前写下的功效上限被确认——21 条缺陷、每臂 n=3，
  这个规模不足以给出显著性结论

预注册的三档判据里，本轮落在"≤1/3 → 反对"那一档（10/12 换算成"三次全满"
是 1/3）。但这个"反对"是**功效不足的产物**，不是"改动无效"的证据——把它读成后者
就是预注册想避免的事后解释。

## 这轮最有价值的产出是方法论的

上一轮 n=1 就下了"with_skill 输 5 条"的结论。本轮 n=3 直接显示**同一条缺陷在
同一臂的不同次里可以判 yes 也可以判 no**（D16: yes/yes/no）。也就是说上一轮那个
差异有多少是生成噪声，无从判断——而当时我把它当成了发现。

## 顺带的附带产出

六份 with_skill 报告在 **1.0.9 的闸门下全部 fidelity 与形状双 exit 0**。这是
n=3 的当前版本形状合规证据，不能替代 1.0.3 那批 n=9（程序与派发条件都不同），
但至少是当前版本上有的。

## 复现

`SEALED-mapping.txt` 是种子 20261009 生成的映射。判官在跑之前拿不到它；
这个文件与 `judge/R*.md` 一并提交，所以任何人都能复核盲判是否成立。

六份判分都过 `evaluate.py score` 的引用校验（每条 `yes`/`partial` 的
`report_line` 与 `quote` 都逐条对得上报告原文），所以不需要 `--legacy`。

```bash
cd skill/analyzing-programs
python scripts/evaluate.py score --defects evals/zvend.defects.json \
  --verdicts ../../analyzing-programs-workspace/exp-1.0.9/judge/J1.json \
  --report ../../analyzing-programs-workspace/exp-1.0.9/judge/R1.md
```

## 产物里有一处 U+FFFD，保留不改

`with_skill/run3.md`（即打乱后的 `R1.md`）第 297 行有两个相邻的 U+FFFD：

```
…会出现在 QUOT 查询结果里、却不出现�� RFQ 结果里…
```

是一个被截断的多字节字符（原文应是"不出现**在** RFQ 结果里"之类）。它在**围栏
之外**，是报告自己的散文，不在任何 ```abap 围栏里，所以引文校验不受影响——
六份判分文件全部过 `evaluate.py score` 的引用校验（exit 0）就是证据。

**刻意不修**。报告是评测对象不是待编辑的草稿，改一个字就等于替被测臂补漏。
同一个字符如果出现在 ```abap 围栏里，那才是引文损坏、要按忠实度问题处理；
这里不是。这个判断本身就是这次实验的产物之一：**报告文件里出现坏字节，
和闸门该怎么反应，是两件事。**

顺带值得记：这六份里唯一一处编码损坏出现在 with_skill 臂，且是散文而非引文。
n=1，方向性都不成立，仅作为一条观察记录。

## 未能排除的污染（预注册里已列）

- 目标四条 D16/D18/D19/D21 的措辞是我写的，措辞可能已提示答案
- 判官是我派的 subagent，不是独立人类
- 1.0.9 臂读的 SKILL.md 是我拿这四条失败样本改的
