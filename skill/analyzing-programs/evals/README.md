# 缺陷参考与评分

`report_qc.py` 只能回答报告**形状**对不对。它答不了两件事：

- **分析是否正确。** v1 报告通过了全部结构检查，同时有 6 条错误论断。
- **召回率。** 报告自己不会说自己漏了什么 —— 漏掉的缺陷不留痕迹。

这两件事都需要一样东西：**有人读过源码，把它哪里不对写下来，然后这份清单不再变。**
这样召回才可测，而且报告重写之后指标不会跟着漂。

## 用法

```
python scripts/evaluate.py tasks   --defects evals/zcl_fi_toolkit.defects.json
python scripts/evaluate.py score  --defects evals/D.json --verdicts MY.json
python scripts/evaluate.py compare --defects evals/D.json --a V1.json --b V2.json
```

`tasks` 打印判分者要逐条回答的问题、锚点、以及 `yes`/`partial`/`no` 的确切含义。
**这一步是模型工作，脚本代替不了。** 其余两步是确定性的。

## 参考文件格式

```json
{
  "source": "ZCL_FI_TOOLKIT.abap",
  "defects": [
    {"id": "D1", "area": "业务正确性",
     "question": "报告是否指出 zzstjah 取自当前行的财年，而 zzstblg 取自另一行……",
     "anchor": "zzstjah = <ls_items>-gjahr"}
  ]
}
```

`question` 的写法很关键：**要让判分者只凭报告文本就能决定 yes/partial/no，不必猜意图。**
`id` 必须稳定，判分文件靠它引用。

判分文件：

```json
{"report": "路径.md",
 "verdicts": {"D1": "yes", "D2": "partial", "D3": "no"},
 "false_claims": [{"claim": "...", "why_wrong": "..."}]}
```

## 校验是刻意的，不是顺手加的

本项目有三个 merge 脚本**静默失败** —— 不抛异常，只是聚合值被清空或覆盖，
靠人工重算才发现。所以判分文件必须能被拒绝，而不能被打分：

| 情况 | 结果 |
|---|---|
| 完整 | 接受 |
| 少判一条 | 拒绝，列出未判的 id |
| 判定值不在 `{yes, partial, no}` | 拒绝，指出具体 id 和值 |
| 出现未知缺陷 id | 拒绝 |
| `false_claims` 条目缺 `claim` 或 `why_wrong` | 拒绝 |
| `false_claims` 是整数而非列表 | 拒绝（无法审计，且静默当成空会把错误论断率报低） |

`analyzing-programs-workspace/check_evaluate_validation.py` 逐条验证这六种情况。

## 自带参考

94 条缺陷 / 6 个真实源码：

| 文件 | 缺陷数 | 源码 |
|---|---|---|
| `zcl_fi_toolkit.defects.json` | 20 | ZCL_FI_TOOLKIT（Keremkoseoglu，1702 行，CLASS） |
| `z_ave_standalone.defects.json` | 22 | z_ave_standalone（ysichov，29.5k 行，CLASS-POOL） |
| `zvend.defects.json` | 21 | zvend.abap |
| `zbc_show_error_log.defects.json` | 10 | 函数组 / EXCEPTIONS |
| `screen_manager_o01.defects.json` | 10 | SALV 屏幕管理器（OO 继承） |
| `dialog_zmsa_r_chapter4_8.defects.json` | 11 | PROCESS BEFORE/AFTER INPUT（经典 PBO/PAI） |

另有 `evals/judge-defects.json`：13 个 eval 的**植入缺陷**共 77 条，属性于测试源码而非报告。

## 已知边界

- **20 条缺陷的配对比较分辨不出小效应。** 一次运行 4 升 4 降、delta 0.000、p=1.0 是噪声，
  不是"两版一样"。低于约 30 个百分点一律记作**未测量**。
- **`compare` 用精确符号检验**（McNemar），因为同一份报告两条判定高度相关，
  独立样本假设不成立。
- **判分本身是模型判断。** 脚本保证的是：参考完整、聚合正确、判分不能缺项蒙混过关。
  它不能保证判分是对的。
- **单文件单次判分不稳。** 同一个 skill 同一文件重复判，召回在 0.625–0.700 之间动
  （20 条里差 1–2 条）。任何小于这个幅度的差异都不要当结论。
