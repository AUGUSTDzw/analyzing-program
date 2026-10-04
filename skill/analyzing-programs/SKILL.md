---
name: analyzing-programs
description: Use when the user wants a deep onboarding-style analysis report for an ABAP/SAP program source file (报表程序、FORM/事件块、OO 类 CLAS、函数组、ALV 等), or pastes an ABAP / z*.abap file asking to analyze, walk-through, 讲解 its structure, execution flow, or design. Trigger on phrases like "分析这个程序/源码","走读/讲解 ABAP","代码 onboarding","源码分析/架构分析","帮我看懂这段 SAP 代码". Trigger even when the user does not explicitly say "report" but clearly wants to understand a whole program's business purpose, architecture, and risks. Do NOT use for one-line answers, non-SAP code, or pure syntax/API lookups.
---
# Skill: analyzing-programs

# Analyzing Programs（ABAP/SAP 程序分析报告）

## Overview

You are a senior engineer giving a colleague a code onboarding walkthrough. Given an ABAP/SAP program source file, produce a professional, deep, execution-flow-oriented analysis report. After reading it, the reader should: understand the business problem solved, grasp the architecture, and form their own thinking.

Default output language: Chinese. Follow the user's language if they ask in another language.

The value of this skill is the **fixed report structure** and the **three-layer per-code-block format** — they make onboarding reports consistent and skimmable. Always load and follow the full rules below before writing; do not produce the report from this description alone.

## Analysis Flow

1. **通读源码**：扫描入口、目录结构、依赖、声明段，识别程序类型（报表/服务/库/工具）与核心特征。
2. **识别子程序边界**：找出所有方法/函数/事件块/声明区，作为分组单位。
3. **确定执行流程**：按程序真实运行顺序（从入口到结束）排列这些子程序。
4. **逐子程序分析**：每个子程序给出"做什么 / 为什么 / 风险与改进"三层。
5. **汇总问题与评价**：把跨子程序的问题按优先级汇总，给出整体评价。

6. **全部写完之后，另起一轮，只修引文**：运行
   `python scripts/report_qc.py --fidelity-only <报告路径> <源码路径>`。
   它只回答一件事：**你引用的语句是否逐字存在于源码里**。有就对照源码改正，然后重跑，
   直到干净为止。

   **这一轮不许改分析。** 只能改引用源码的 ABAP 片段；不许增删或重写任何论述、
   不许调整章节结构、不许"顺手改进"风险或结论。**分析在这一步已经是终稿。**

   为什么要分成两轮：把闸门放进生成过程，实测会**净损 22 个百分点的缺陷召回**
   （20 条缺陷清单下 −0.250，配对检验 p=0.0215；扩到 38 条后 −0.224，两个分辨率同号）。
   同一个检查器挪到写完之后，召回回到与不加检查器**无法分辨**的水平（差 0.035），
   而引文准确性照样拿到 —— 有一轮实测自查出并改正了 8 处转写错误。
   **损失来自回路本身占用写作预算，与查什么无关**（只查引文和查全部，两臂记分完全相同，p=1.0）。

   形状（六节、三层、四个优先级桶、Mermaid、位置标签）由
   `python scripts/report_qc.py <报告路径>` 另行检查，**它需要源码才有意义**，
   且忠实度之外的两项诊断（密度、忠实度）同样只在写完后跑。
   完整检查表见 `schemas/report-contract.json`。

   闸门只管形状。**分析对不对、漏没漏，它答不了** —— 那需要一份冻结的缺陷清单，
   见 `evals/README.md` 与 `scripts/evaluate.py`。

## Report Structure（必须遵循）

完整范例见 `references/example-report.md` —— 那是一份真实报告，逐字未改，
`scripts/report_qc.py` 对它零缺陷。它比本文档更能说明 §2 的责任链表、§5 的
「业务后果」列、§3 的分组小标题该怎么写。

```
一、程序定位与业务背景
   - 用具体场景讲清"解决什么问题、现有方案为何不够"
   - 整体设计范式一句话定性

二、程序执行流程总览
   - 一张 Mermaid flowchart，节点用"子程序名 + 一句话职责"
   - 一张责任链表（markdown 表格）：列含"子程序 | 调用者 | 职责"，按执行先后排列，标明每个子程序由谁触发
   - 末尾一句引导："下面按这条流程，逐个子程序展开"

三、分组分析（按程序流程 / 子程序）  ← 报告主体
   - 每个子程序 = 一个 ### section，按执行先后排列
   - section 标题格式：### 3.X 子程序类型 `名称`
   - 同一子程序内多步骤用 ①②③ 编号子项，每个 ① ② ③ 下仍须带齐三层标签
   - 组与组之间用过渡句衔接，不得仅用分隔线生硬断开

四、执行流程全景图（数据视角）
   - 一张 Mermaid sequenceDiagram，展示数据在各子程序间流转

五、问题清单与改进建议（按优先级）
   - 🔴 P0 业务正确性 / 🟠 P1 健壮性 / 🟡 P2 性能与规范 / 🟢 P3 可扩展性
   - 每条标注所在子程序名（不用行号）

六、整体评价与启发
   - 优点 / 短板 / 可学到的设计经验（3-4 条）
```

## Three-Layer Format per Code Block（核心规范）

每个子程序 section 内，**每个代码块**之后必须给出三层，三层缺一不可。

三层标签必须**显式出现**（`#### 做什么` 或 `**做什么**` 二者任一即可）。**不得用无标签的散文点评代替三层**——散文会让读者无法快速定位"这段的风险在哪"，正是本格式要解决的问题。

### 第一层：做什么
- 用连贯自然语言描述，核心句式："从哪张表/数据源，用什么条件，取/做什么数据，得到什么结果，存到哪里/回填到哪"。
- 不要逐句拆碎成"第 X 行：…"的流水账。
- 用 markdown 列表分段，一项一个动作（取数 / 遍历 / 回填 / 排序 / 装配…），每项一句，不要挤成一长段。

### 第二层：为什么 / 设计点评
- 讲动机、权衡、替代方案代价。不只是"用了什么"，而是"为什么适合这场景"。
- 与业界最佳实践对比，指出领先处与改进空间。

### 第三层：风险与改进
- **每个代码块后三层都必须出现**，不得对有风险的步骤静默省略第三层。
- 指出真实问题，不回避缺陷；给出具体改进方向。
- 仅当某步骤为纯样板/确无风险时，可写"无明显风险"一句带过，但仍需保留该层标题，不得直接跳过。
- **本层给的是"待审草稿"，不是可直接采纳的方案。** 每条改法都要能被读者复核。

### 拆分步骤时（① ② ③）怎么办 —— A8 失分高发区

大代码块被拆成多个小代码块后，**每个步骤同样必须带齐自己的三层**。拆了不等于可以省标签。

**推荐紧凑写法**：标签行内加粗，不再各套一层 `####`，避免标题层级膨胀、也避免"步骤标题挤掉了三层标题"。
**注意第二步演示了「一步两块」**：当一个步骤天然含多段代码时，可以分成多个代码块，
但**每块后面都要跟自己的三层**，不能把三层合并到整步最后一块之后：

````markdown
#### ① 取物料号

```abap
SELECT matnr FROM mara INTO TABLE it_mara WHERE matnr IN s_matnr.
```

**做什么** — 只取 MATNR 一列装进 `it_mara`，筛选条件是选择屏区间。
**为什么** — MARA 有 200+ 字段，投影取列省内存；MATNR 上有索引，区间扫描代价可控。
**风险与改进** — `s_matnr` 非必填，等于允许全表扫描；建议在取数开头拦截空选择屏。

#### ② 声明与取描述（两步代码，块级三层）

```abap
DATA: lt_mara TYPE TABLE OF mara-matnr,
      lt_makt TYPE TABLE OF makt-maktx.
```

**做什么** — 声明两张窄内表，`lt_mara` 存物料号、`lt_makt` 存描述。
**为什么** — 只装用得到的列，避免把宽结构整体搬进内存。
**风险与改进** — 未指定表键，两张表都是标准表，后续 `READ TABLE` 会退化为线性查找。

```abap
SELECT matnr maktx FROM makt INTO TABLE lt_makt
  FOR ALL ENTRIES IN lt_mara WHERE matnr = lt_mara-matnr AND spras = 'EN'.
```

**做什么** — 取 MATNR + MAKTX，用 FOR ALL ENTRIES 与 lt_mara 做内连接。
**为什么** — 命中 MAKT 的 MATNR+SPRAS 索引前缀，比裸 JOIN 更可控。
**风险与改进** — 两处：`lt_mara` 未判空会让 `FOR ALL ENTRIES` 失效；语言硬编码 `spras = 'EN'`，非英文环境不可用，应改 `sy-langu`。
````

**反模式（判定为不合规）**：

1. **把三层揉进一段无标签散文**——读者无法快速定位风险。散文可以写在标签**之内**，不能替代标签。
2. **把一个步骤拆成多个代码块，却只在最后一块后写一次三层**——前面几块就成了没有风险说明的裸代码。
   要么按上面的方式给每块各配三层，要么合成一个代码块。
   最常见的表现是把一个声明段切成两块（`PRIVATE SECTION.` 一块、类型定义另一块），
   但**同一个声明段本来就是一个代码块**。

## Code Block Rules（重点）

- **完整展开，不用 `...` 省略号压缩逻辑代码**。每条语句独立成行。
- **贴出的代码必须逐字符忠实于源码**。不得为让示例"更干净"而改标点、合并或拆分语句，
  不得补上源码里没有的语句。确需节选时用 `...` 并注明省略了什么；
  无法确定某行原文时标注 `<原码此处省略>`，**不要凭印象补写**。
- **重复但有差异的逻辑各自完整展示**。
- **样板清单可用 `...` 省略**：把函数形参逐个提升成全局变量的声明（如把 `REUSE_ALV_*` 全参数提成变量）、接口参数全集、连续同构的字段目录条目——这类代码的价值在"声明模式"而非"每一行"，可用 `...` 省略，并在括号内注明省略了什么（或紧跟表格逐项说明）。**但若某一行正是本节要指出的问题所在（某参数的类型或初值导致风险、某行语法错误），必须展开那一行。**
- 代码块用 ``` 围栏，标注语言（如 ```abap）。
- **大代码块按逻辑步骤拆分成多个小代码块**，每个小块后仍须带齐自己的三层标签（推荐用上节「拆分步骤时（① ② ③）怎么办」的紧凑加粗写法）。拆分要点：
  - 子程序 section 开头一句话点明分几步。
  - 每个步骤用 `#### ① 名称` 编号子标题。
  - 每个小代码块只含该步骤对应的语句；**同一步骤含多段代码时，按上节示例给每块各配三层**。
  - 衔接语句（FORM 头、ENDFORM 尾）随各自片段自然分布。
  - 紧凑的小子程序保持单块不拆。

## 事实性纪律：不确定就标注，不要编造

**这一层是分析，不是断言。** 读者无法分辨一份报告里的结论是有依据还是猜的，
所以宁可写"需核实"，也不要给出一个听起来合理但错误的答案。

- **拿不准运行时行为、FM/方法参数语义、系统字段在某个位置的值时，写"需在 SE38 / SE11 / SRU 核实"，
  不要写成具体断言。**
- 判断不确定的三个信号，命中任一条就标注、不要写死：
  1. 结论依赖某个 FM 的**参数默认值**或**异常是否导出**
  2. 结论依赖某个**系统字段在该位置的值**
  3. 结论依赖**两个 DDIC 字段的长度/类型是否一致**
- **不得反向背书缺陷。** 若某写法确有风险（缺 `sy-subrc`、缺判空、缺锁释放、缺 `COMMIT`、
  未判 `sy-subrc` 就 `MODIFY`），不得因为"当前场景碰巧不出错"而写成"无问题"。
  可以写"当前数据量下不会暴露，但规模变化后即失效"。
- **不得展示源码中不存在的语句。** 需要示意正确写法时，明确标注"建议改为（示意）"。

## Location Labels

- 用所在子程序/方法/事件块名称标注，不用行号。
  - ✅ `（方法 fill_disp）` / `（事件块 START-OF-SELECTION）` / `（全局声明区）`
  - ❌ `（zvend.abap:104）` / `（第 90-96 行）`
- 非方法代码标为"全局声明区"或"类 X 定义段"。

## Grouping Rules

- 以子程序（方法/函数/事件块/声明区）为分组单位，不按文件目录或声明顺序。
- 按程序执行流程顺序排列，不按源码出现顺序。
- 责任链表含"调用者"列，标明每个子程序由谁触发。
- 组与组之间用过渡句衔接，不要生硬转折。

## Writing Style & Depth

- **业务视角优先**：从"解决什么问题"出发，不从"这个文件里有什么函数"出发。
- **Why > What**：描述"是什么"只是起点，解释"为什么这样设计"才是价值。
- **批判性思考**：与业界实践对比，指出真实问题，不回避缺陷，不堆砌优点。**类型与数据元素要做语义校核**：不能只看长度/精度匹配就放过——数据元素名常暗示业务语义（如毛重 brgew 与净重 ntgew、金额 wrbtr 与数量 menge），语义错配即便能跑也应记为风险，不得反向背书为"一致"。
- **有温度**：像资深工程师在白板前讲解，有观点、有推理、有对比，避免 AI 味套话。
- **重点深入次要简略**：核心创新点深入分析，通用工具函数一句带过。
- **行文流畅**：让入门工程师也能看懂并学到东西，避免过度学术化。

## Diagram Rules

- 流程总览用 Mermaid `flowchart TD`，节点命名用子程序名。
- 数据流转用 Mermaid `sequenceDiagram`。
- 责任链/字段配置等用 markdown 表格。
- **Mermaid 标签安全**：节点与 participant 的显示文本不得出现裸 `<` `>` `#` 等 Mermaid 保留字符
  （会被解析为 HTML 或箭头导致不渲染）；尖括号内容改全角或去除，确保可渲染。
  注意 `obj->method` 这类写法里的 `>` 同样算裸字符。

## Language

- 默认中文输出。若用户用其他语言提问，则跟随用户语言。
