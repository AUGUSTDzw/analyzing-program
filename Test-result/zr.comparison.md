# `zr.abap` 三次运行对照（稳定性测量）

对照对象：

| 标签 | 文件 | 说明 |
|---|---|---|
| baseline（无 skill） | `zr.md` | 裸模型直接分析 |
| skill run 1 | `zr.skill-b8f84e8.md` | 首次按 skill 规范产出 |
| skill run 2（本次） | `zr.skill-b8f84e8.run2.md` | **同一 skill 版本重跑** |

Skill 版本三次完全一致：SHA256 `B8F84E805A2A2AEC6ECFF58F35AC7E6C55874308B4559A73EFDB068FC5F00A1B`（`b8f84e8`）。
因此 run 1 与 run 2 的差异反映的是**运行间随机性**，不是 skill 版本差异。

---

## 1. 缺陷覆盖

以 32 条缺陷指纹（从三份报告归纳，每条含多个同义正则）对第五节问题清单做匹配，
逐条明细见 `zr.comparison.txt`。

| | baseline | run 1 | run 2 |
|---|---|---|---|
| 覆盖指纹 | 23/32 = **72%** | 24/32 = **75%** | 32/32 = **100%** |

- run 2 是前两者的**严格超集**：前两次报告提到的每一条，run 2 全部覆盖，且新增 8 条。
- baseline 与 run 1 各漏 1 条已被 run 2 补上：`s_matnr` 非必填导致全表扫描。

## 2. run 2 独家发现的 8 条

| 缺陷 | 优先级 | 为什么重要 |
|---|---|---|
| `MODIFY zfinal` 中 `zfinal` **未声明** → 语法检查不通过 | 🔴 P0 | **程序根本无法编译**。这是全文件最硬的结论，两次前跑都没抓到 |
| `ty_makt-matnr` 声明为 `TYPE makt-maktx` | 🟡 P2 | 因同为 `CHAR 40` 不报错，但语义把编号字段声明成了描述字段 |
| `it_makt` 标准表线性查找 → O(n²) | 🟡 P2 | 物料上万条时明显 |
| 每行携带 `cellcolor TYPE lvc_t_scol` | 🟡 P2 | 与全表扫描叠加易触发 `CX_SY_NO_MEMORY` |
| `MESSAGE ... TYPE 'I'` 后接 `LEAVE TO CURRENT TRANSACTION` 多余 | 🟠 P1 | 额外重启事务流；应换 `RETURN` |
| 列标题 `'Material'` / `'Description'` 硬编码、无文本符号 | 🟡 P2 | 无法 SE63 翻译（与消息文案同类问题） |
| `i_callback_program = sy-repid` 隐式耦合 | 🟢 P3 | 抽到函数组即失效 |
| `matnr+0(1)` 偏移写法 | 🟢 P3 | 可读性 |

## 3. 格式合规性差异（run 1 存在 A8 违反）

用结构检查器逐块校验"每个 ` ```abap ` 代码块后是否带齐 `做什么` / `为什么` / `风险与改进` 三层"：

| | 报告章节完整性 | 责任链含「调用者」列 | Mermaid 可渲染 | 三层标签逐块覆盖 |
|---|---|---|---|---|
| run 1 | ✅ 6 章齐全 | ✅ | ✅ | ❌ **2 个代码块违反** |
| run 2 | ✅ | ✅ | ✅ | ✅ **15/15 覆盖** |

run 1 的两处违反都出现在**它自己写的修复建议代码**上——即"把缺陷修好之后贴出的正确代码"
用了无标签散文点评，恰好落入 skill 明确列为反模式的写法：

- `FORM getdata` ③ 段：贴出 `CLEAR wa_makt. READ TABLE ... IF sy-subrc = 0. ... ENDIF.` 修复代码后，
  只接了 `- 🟡 **P2｜…**` 形式的散文列表，无三层标签。
- `FORM getdata` ⑤ 段：贴出 `CONSTANTS c_col_warning TYPE c_lvc_color TYPE 6. " 绿色` 后同样无三层标签。

顺带一处内容问题：run 1 在该 `CONSTANTS` 注释里把颜色码 6 断言为「绿色」。这个映射无法从源码推出，
需要查 `c_lvc_color` 的颜色表才能确认。run 2 因此刻意**不给颜色码命名**，只指出"魔数无注释"。

> 这说明 skill 的 A8 规则（拆分步骤后每步仍须带齐三层）在**生成修复代码**这个场景下容易漏，
> 而不是在分析源码时。规则文本已覆盖该场景（"拆了不等于可以省标签"），但实践上仍会复发——
> 值得考虑在 skill 里为"贴出改进代码"的场景补一个显式提示。

## 4. 三次都稳定命中的核心缺陷（说明基线足够强）

以下 21 条三次全部命中，其中 7 条属于 P0/P1 级严重问题：

- SAVE 分支**无任何持久化**（无 `UPDATE`、无 BAPI、无 `COMMIT WORK`）
- `it_makt` / `it_zfinal` 两处 `READ TABLE` 均未判 `sy-subrc`
- `spras = 'EN'` 语言硬编码
- `MODIFY` 若指向快照会污染基准
- `&IC1` 遍历全表 + `WRITE` 全表
- `MATNR` 未设 `key` / `hotspot` → `&IC1` 永不可达
- `GET_GLOBALS_FROM_SLVC_FULLSCR` 无异常处理 → 短 dump

**结论**：裸模型在这个 159 行程序上已经能稳定抓到大部分严重缺陷，skill 的增量主要体现在
**类型/语义校核**（`makt-maktx` 误用）、**性能量级**（O(n²)、内存）、**可编译性**
（`zfinal` 未声明）和**格式完整性**（A8 三层）这四类——恰好是裸模型最容易略过的维度。
这与 iteration-7 / iteration-8 benchmark 的结论一致：skill 的价值在结构与完整性，
而非"更准的代码评审"。
