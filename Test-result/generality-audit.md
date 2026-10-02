# 通用性与正确性实测：analyzing-programs skill

测试对象：`zr.abap`（自有，159 行）、`zvend.abap`（自有，357 行）、
以及从网络获取的 10 个真实开源 ABAP 文件（见 `Test-source/real/MANIFEST.json`）。

Skill 版本全程未变：SHA256 `B8F84E805A2A2AEC6ECFF58F35AC7E6C55874308B4559A73EFDB068FC5F00A1B`（`b8f84e8`）。
因此两次独立运行之间的差异反映的是**运行间随机性**，不是版本差异。

派发子代理时**只说"使用 analyzing-programs skill"**，不给任何额外提示——否则测的就不是出货状态。

---

## 1. 语料来源

真实语料全部来自公开开源仓库，逐文件记录了 URL、分支、许可证与 sha256：

| 来源 | 许可证 | 文件 | 行数 |
|---|---|---|---|
| [abapGit](https://github.com/abapGit/abapGit) | MIT | `zabapgit_forms.prog.abap`（INCLUDE 层，多 FORM） | 332 |
| abapGit | MIT | `zabapgit.prog.abap`（主程序，INCLUDE 编排） | 80 |
| abapGit | MIT | `zabapgit_password_dialog.prog.abap`（模态密码对话框） | 201 |
| abapGit | MIT | `zcl_abapgit_object_fugr.clas.abap`（函数组序列化） | 1530 |
| abapGit | MIT | `zcl_abapgit_objects_program.clas.abap`（程序/INCLUDE 序列化） | 1598 |
| abapGit | MIT | `zcl_abapgit_flow_logic.clas.abap`（UI 流逻辑） | 1115 |
| [SAP-samples/cloud-abap-rap](https://github.com/SAP-samples/cloud-abap-rap) | Apache-2.0 | `zdmo_c_rapg_projecttp.bdef.asbdef`（RAP 行为定义 BDL） | 76 |
| SAP-samples/cloud-abap-rap | Apache-2.0 | `zdmo_c_rapg_projecttp.ddls.asddls`（CDS DDL 源） | 83 |
| [SAP-samples/abap-platform-reuse-services](https://github.com/SAP-samples/abap-platform-reuse-services) | Apache-2.0 | `zreusebp_r_salesordertp_002.clas.abap`（RAP 行为池） | 16 |
| SAP-samples/abap-platform-reuse-services | Apache-2.0 | `zcl_zreuse_so_002_chdo.clas.abap`（变更文档） | 131 |

补齐了原语料缺失的构造：`FIELD-SYMBOL`（4/10 文件）、`FORM ... TABLES`（5/10）、
`EXIT`/`CONTINUE`（5/10）、嵌套 `PERFORM`、`MOVE-CORRESPONDING`、INCLUDE 层、
全局类、以及 RAP/BDL/CDS 这条现代栈。**仍然缺失**：AMDP/SQLScript、BADI 实现、
函数模块、类池、动态 SQL、`COMPUTE`/`MOVE TO` 等过时语句。

规模上补齐了最关键的缺口：此前最大被测对象 332 行，现已有 1115 / 1530 / 1598 行的真实类。

---

## 2. 格式合规性：全部报告

用脚本逐块检查（不依赖子代理自述）：

| 报告 | 行数 | 六章 | abap 块 | A8 违反 | Mermaid 风险标签 | 行号标注 | 问题行 |
|---|---|---|---|---|---|---|---|
| `zr.skill-b8f84e8.md` | 659 | 6/6 | 20 | **5** | 0 | 0 | 27 |
| `zr.skill-b8f84e8.run2.md` | 531 | 6/6 | 15 | 0 | 0 | 0 | 33 |
| `zvend.skill.run1.md` | 1090 | 6/6 | 33 | **10** | 0 | 0 | 30 |
| `zvend.skill.run2.md` | 785 | 6/6 | 21 | **1** | 0 | 0 | 31 |
| `real/abapgit_forms.skill.md` | 833 | 6/6 | 22 | 0 | 0 | 0 | 24 |
| `real/abapgit_flow_logic.skill.md` | 1599 | 6/6 | 40 | 0 | 0 | 0 | 41 |
| `real/abapgit_password_dialog.skill.md` | 609 | 6/6 | 19 | 0 | 0 | 0 | 18 |

**六章结构、Mermaid 可渲染性、不用行号定位** 三项零违反，7/7 报告全部达标。

**A8（每个 abap 块后三层标签）违反 16/170 = 9%**，且分布高度不均：

- `zr` 首跑 5 处、`zvend` 两次 10 + 1 处
- 三个真实语料报告 **0 处**

关键规律：**A8 违反只出现在"贴出修复建议代码"的位置**，也就是分析完问题后给出正确写法时，
作者会用无标签散文点评自己的修复代码。`zvend.skill.run1.md` 第 2 个代码块是典型：
连续两个 abap 块（ALV 句柄声明 + 工作内表声明）之间零散文零标签，三个图层全部落在第二块之后。

这与 skill 文档里的反模式说明一致——**规则已写明，但在这个场景下仍会复发**。

---

## 3. 技术正确性：zvend.abap 双次运行

由**独立 judge 从源码自行推导**缺陷清单（21 条，含 compile/activation 阻断、错误变量、
缺 `sy-subrc`、`FOR ALL ENTRIES` 未判空、同族查询口径不一致、声明但从不填充的字段、
类型窄化、错误处理不真正中断、标准表性能、硬编码文本、安全），再对两份报告打分。
judge 未参与报告撰写。

| | yes | partial | no | 加权 |
|---|---|---|---|---|
| run1 | **17**/21 | 1 | 3 | 0.833 |
| run2 | **13**/21 | 5 | 3 | 0.738 |

8 条判定两次不一致（D1/D4/D8/D11/D13/D15/D18/D19）。同一份源码、同一份 skill，
**加权分相差 9.5pp，逐条分歧 8/21 = 38%**。

### 系统性盲点（两次都漏）

**D6（可编译性）**：`JOIN ekko AS a JOIN ekpo AS b` 之后，`WHERE` 里的 `bedat`、`lifnr`
未加表别名前缀。两次运行**都明确背书"不歧义"**——run1 判为"当前能解析"，run2 说
"`BEDAT` 只存在于 `EKKO`，故不歧义"。这正是前一轮发现的失败模式的复现：
**碰到自己不确定的语法/环境细节时，倾向于断言其合法性，而不是标注不确定。**

### 两次的共同强项

以下 13 条两次都判 yes，说明在"读得懂业务语义"的维度上 skill 是稳定的：
报价段缺 `sy-subrc` 兜底致整行丢失（D9）、`EXIT` 不终止程序致初始引用崩溃（D3）、
空 `CATCH` 吞异常（D2/D17）、`FOR ALL ENTRIES` 未判空（D11）、5 次重复聚合（D10）、
O(n²) 回填（D12）、`t_disp-bedat` 恒空（D14）、`INCLUDE <color>` 残留（D16）、
无判空仍显示空表（D20）、**无 `AUTHORITY-CHECK`（D21）**。

---

## 4. 事实性错误抽查

对 `real/abapgit_password_dialog.skill.md` 做了 8 项核查（独立子代理，逐项对源码）：

- 结构六章、Mermaid 两图、责任链含「调用者」、三层标签 **19/19 全过**、Mermaid 无裸尖括号、
  定位用方法名不用行号、四级优先级 18 行 —— **7/8 PASSED**
- **第 8 项 FAIL：报告与源码不符**，4 处虚构/篡改 + 1 处错误论断：
  1. 代码块里多出一个源码中不存在的 `ASSERT sy-dynnr = c_dynnr.`（源码只有 2 个 `ASSERT`，
     报告代码块出现 3 个，且报告自己的 P2 行又把 `ASSERT` 归给两个方法——自相矛盾）
  2. 三处 `PARAMETERS: p_user/p_pass/p_cmnt` 被去掉冒号（源码是 `PARAMETERS:` 带冒号形式）
  3. `ELSE.` 被写成 `ELSE:`
  4. 论断"单个 `PARAMETERS` 用了冒号，与后续逗号风格不一致"——**源码四处全部是冒号形式，
     不存在逗号变体**，该论断凭空捏造
  5. 引用了 `Ctrl+F3` 作为被 `WHEN OTHERS` 捕获的动作码，源码中不存在

另外漏掉源码第 3 个 `SELECTION-SCREEN SKIP.`（源码 3 个、报告 2 个），
而报告正文却按"3 个 SKIP"在计数。

**结论：skill 会产出看似精确的技术论断，但其中一部分是虚构的。**
这类错误比"漏报"更危险——读者会把它当作经过核实的结论。

---

## 5. 运行稳定性

| 文件 | 运行 1 | 运行 2 | 差异 |
|---|---|---|---|
| `zr.abap`（159 行） | 24/32 = 75% | 32/32 = 100% | 8 条新增，0 条丢失 |
| `zvend.abap`（357 行） | 17/21 加权 0.833 | 13/21 加权 0.738 | 8/21 判定分歧 |

`zr` 上是**单调改进**（第二次是第一次的超集）；`zvend` 上是**双向波动**。
样本量小（每格 n=2），无法区分这是真实方差还是 judge 自身的抖动，但足以说明：

**不能保证任何单次运行会抓到致命缺陷。**

另需记录两个工程事故（均为子代理侧，非 skill 缺陷）：
`zvend.skill.run2.md` 首次生成时**被截断在 101 行**（第四章起缺失），重跑才得到完整 785 行；
`abapgit_flow_logic.skill.md` 首次生成被截断在第三章中段，接续补完才到 1599 行。
长文件上必须显式要求"单次 write 调用写完整文档"。

---

## 6. 可以信任 / 不可信任

### 可以信任
- **格式合规性**：六章、两张图、责任链、不用行号——7/7 报告零违反，稳定。
- **结构与完整性**：格式层 0.980 vs 0.554（p=5.55e-44 / 780 格），跨 13 种程序类型成立。
- **业务语义与数据流**：能稳定抓出"回填缺兜底致整行丢失"、"`EXIT` 不终止程序"、
  "字段声明但从不填充"、"重复聚合"、"无权限校验"这类需要读懂意图才能发现的缺陷。
- **规模泛化**：1598 行的真实类、1115 行的 UI 逻辑、RAP 行为定义都产出完整六章报告，
  1600 行规模未触发截断或质量塌陷。

### 不可信任
- **单次运行的完备性**：逐条分歧 38%，`zr` 上两轮覆盖差 25pp。
- **对具体语法/环境细节的断言**：两轮都把 JOIN 后未加别名的字段判为"不歧义"并背书。
- **代码块的字面忠实度**：出现过虚构语句（多一个 `ASSERT`）、篡改标点（`ELSE.`→`ELSE:`）、
  以及凭空捏造的对比论断。
- **A8 三层标签在"贴修复代码"场景**：9% 的代码块缺标签，且全部集中在这一场景。
- **未经人工复核就据此决定是否上线**。

### 定位建议
当作**第一遍读代码的思考清单**用：它能可靠地帮你把"该看哪里"标出来，
但它标出的每一条技术结论都需要人工或 ATC 复核。
致命缺陷（编译阻断、越权、数据丢失）必须有第二道防线。

---

## 7. 若要提升，按投入产出排序

1. **要求对不确定项显式标注**——零成本，直接消除 D6 这类"自信的错误背书"。
   例如"此写法是否合法需在 SE38 语法检查确认"，而不是断言不歧义。
2. **代码块字面忠实**——加一条"贴出的代码必须逐字符与源码一致，不确定处标 `<...>`"，
   可消除虚构 `ASSERT` / `ELSE:` 那类问题。
3. **A8 延伸到修复代码场景**——现有规则已覆盖但会复发，可加一句
   "贴出改进代码时同样需要三层标签"。
4. **语料继续补**——AMDP、BADI 实现、类池/函数模块、动态 SQL 仍未覆盖。
5. **judge 加第二评审员**——本次 38% 的 run 间分歧里，无法区分多少来自报告、多少来自 judge 抖动。
