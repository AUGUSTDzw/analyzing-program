# 参考资料索引

本目录里除了 `example-report.md`，其余都是**失败模式的记录，不是规则**。
规则已经写进 `SKILL.md` 的「分析流程」与「闸门输出」两节。

每份都写了测量数字与样本量。**样本量小的不能当结论用**——那正是它们自己
写在开头的原因。

## 范例报告

`example-report.md` 是一份**真实报告**，对 `scripts/report_qc.py`
**零缺陷**——带它自己的源码一起跑也是零缺陷。

不是手写的。手写的示例只能证明作者想得通；这份证明得了**这个格式可达** ——
它是 23 份在盘报告里唯一同时满足「闸门通过 + 六节齐全 + 四桶完整 + 含 Mermaid」
且由当前 skill 版本生成的。

### 选它的理由

从 23 份里筛，条件是：闸门 PASS、四个优先级桶齐全、含流程图与时序图、体量可控。
11 份合格，取最小的当前版本：`ZBC_SHOW_ERROR_LOG`，305 行，14 个子节。

| 它演示了什么 | 在哪 |
|---|---|
| 六节骨架与命名 | 全文 |
| §1 先讲业务问题、不讲文件里有什么函数 | §1.1 |
| §2 责任链表（含"调用者"列） | §2 |
| §3 分组小标题 `### 3.X 子程序类型 \`名称\`` | §3.1–3.5 |
| 一步两块、每块各自三层 | §3.2、§3.3 |
| 流程图 + 时序图 | §4 |
| 四个优先级桶，每桶一张表 | §5 |
| **「业务后果」列** —— 后果而非仅现象 | §5 的 P0-1、P0-3 |
| 跨子程序的边界问题（本文件看不到的东西） | §3.5、P0-3 |

其中**责任链表**和**「业务后果」列**闸门查不出来，只能靠范例传达。

### 它不演示什么

- **只有一种程序类型**：函数组 / FM。报表、OO 类、CLASS-POOL 的分组差异
  看 `evals/` 里对应缺陷集所附的源码。
- **不含超大文件**。29.5k 行的 CLASS-POOL 见 `evals/z_ave_standalone.defects.json`
  所指源码；那种规模一份报告写不完，原因见 `evals/README.md` 的边界一节。

### 保持有效

`tests/test_skill.py` 里有两项跑闸门确认本文件仍然零缺陷，改坏了会 fail：
`the shipped example report still passes`（不带源码）与
`the shipped example report still passes against its own source`（带
`Test-source\real\` 下那份 `zbc_show_error_log` 源码，专治 §5 某行不标
源码对象这种缺陷——不带源码时 `row-src` 根本不跑）。已做负向对照：
改掉一个桶标题即失败。

## 交付方式的失败模式

只记录**已测量的观察**，不给建议——没测过的解法给了就是又一次基于弱证据的改动。

| 文件 | 内容 |
|---|---|
| `large-inputs.md` | 为什么一份任务写不完；**静默 / 截断 / 变薄** 三种失败形态分别长什么样 |
| `delivery-methods.md` | 三种交付结构的完整率与 Fisher p 值，都分辨不出（整体 29%，n=14） |
| `slice-and-write.md` | 切片-即写的唯一可辨认差异，**n=1**。它指出的方向是「失败要可见，不要静默」，不是「用切片-即写」 |
| `output-rate.md` | 行/子程序比。结论：成本在**预算**里，不在格式里 |
| `truncated-reports.md` | 事故记录：465 行的 AVE 残篇被当成完整报告计入聚合，误报出「A8 从 50 降到 15」 |

## 语法与语义

`abap-syntax/` —— 9 份语法资料 + `ABAP_keywords_master.txt` 关键字总表
+ `ABAP.tmLanguage` / `ABAP_notepad.xml`（编辑器语法定义）。

核对语法与关键字语义用。**它是参考资料，不是闸门的一部分** ——
闸门只读 `schemas/report-contract.json`。

**这 9 份是上游 SAP `abap-cheat-sheets` 集合（Apache-2.0）的子集，不是全集。**
上游 `main` 分支有 37 份，本目录只收了 9 份，逐份是上游原文的逐字节拷贝
（可与上游 git blob SHA-1 复算核对，例如 `11_Internal_Tables_Grouping.md` 对
`3080642a8dba2d4f13208048c3e712a069ddbf9e`）。因此这几份资料内部的交叉引用会
指向本目录里不存在的兄弟文件（`02_Structures.md`、`05_Constructor_Expressions.md`、
`06_Dynamic_Programming.md`、`08_EML_ABAP_for_RAP.md`、`10_ABAP_SQL_Hierarchies.md`、
`14_ABAP_Unit_Tests.md`、`15_CDS_View_Entities.md`、`16_Data_Types_and_Objects.md`、
`17_SAP_LUW.md`、`22_Released_ABAP_Classes.md`、`31_WHERE_Conditions.md`、
`37_Logical_Expressions_and_Functions.md`）——
**这些链接在本目录里点不开，是收录范围所致，不是文件损坏。** 文件名是刻意保留的：
它告诉你该去上游集合找哪一份。需要的语义在上游找到后，若与本目录的口径冲突，
以 ABAP Keyword Documentation 为准。

反过来说：**这 9 份里没有的语义，本目录里就没有。** 写「为什么」和「风险与改进」
要断言这样的行为时，不要凭记忆补——按 `SKILL.md` 的「事实性纪律」标注需核实。
