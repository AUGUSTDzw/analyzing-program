# INCIDENT：仓库被外部进程删除，部分恢复

**发现时间**：2026-10-05 22:55 左右，在做 completion-diagnostic 的确认轮时。
**状态**：交付物（skill）完好；研究记录大部分丢失；已恢复 iteration-8 的全部证据。

---

## 1. 发生了什么

执行 completion-diagnostic 确认轮时，`D:\Workspace\Skills\analyizing-programs`
整个仓库被清空：

| 路径 | 状态 |
|---|---|
| `.git` | **目录还在，内容被清空**（`git status` 报 not a git repository） |
| `skill/` | 清空，0 文件 |
| `evals/` | 清空，0 文件 |
| `Test-source/` | 清空，0 文件 |
| `Test-result/` | 清空，0 文件 |
| `reference/` | 清空，0 文件 |
| `analyzing-programs-workspace/` | 只剩 `completion-diagnostic/` 和 `iteration-9b/` |

顶层目录壳都还在，只是内容没了。这不是 git 操作造成的——git 仓库本身就没了。

同时发现一个**拼写错误的镜像目录** `D:\Workspace\Skills\analyizing-programs`
（少了一个 n），创建时间 2026-10-05 20:36，与本次派发时间吻合。
其中一个子代理（D3-k2）在自己的结果里承认向该路径写了一份副本。
镜像目录也被同样清空，只剩 2 份报告。

**成因未定。** 我能确认的是：`.git` 被清空、仓库内容被删、
且写入 `skill/` 子目录的文件会在数秒内再次消失（已实测：
复制进去 18 个文件，立即 hash 校验通过，随后目录变空）。
而 `analyzing-programs-workspace/` 下的文件和
`C:\Users\DzwU\.agents\skills\` 下的文件都不受影响。

这是定向清理，不是随机损坏。我无法从这里判断它是谁做的。

## 2. 幸存

| 内容 | 位置 | 状态 |
|---|---|---|
| **skill 本体（718f5988）** | `C:\Users\DzwU\.agents\skills\analyzing-programs\` | 18 个文件完整 |
| **旧版本 skill（b8f84e8）** | `C:\Users\DzwU\.agents\skills\analyzing-programs-b8f84e8\SKILL.md` | 9815 B |
| **iteration-8 全部证据** | `C:\Users\DzwU\AppData\Local\Temp\opencode\i8\` | 133 个文件 |
| **i9probe 三臂探针证据** | `...\Temp\opencode\i9probe\` | 完整 |
| **neg 负对照证据** | `...\Temp\opencode\neg\` | 完整 |
| D3-k2 报告（178296 B） | 镜像目录 | 幸存 |
| C1-k3 报告（157000 B） | 真实目录 | 幸存 |

digest 已核对：

```
718f5988 臂  718f598878c549d0   14117 B   与迭代 8/9/9b 使用的版本一致
b8f84e8  臂  b8f84e805a2a2aec   9815  B   与 pin 记录一致
```

**iteration-8 是修正后（grade_v2）那一轮**，已在 temp 副本中核实：

```
paired_format: with_only_pass 170 / without_only_pass 5 / concordant_pass 215
               McNemar exact two-sided p = 5.553e-44
format_pass_rate: with_skill 0.980 / without_skill 0.554
judge_pass_rate:  with_skill 0.849 / without_skill 0.826
skill_sha256: b8f84e805a2a2aec...   <- 该数字描述的是前驱版本，不是 718f5988
```

即之前对外说明过的口径仍然成立：**这批召回数字属于 b8f84e8，不是出货版本。**

## 3. 丢失

- **全部 git 历史**（iteration-1 至 9b 的所有提交）
- `Test-source/` 58 个真实语料文件（abapGit 三个源文件在内）——可从 GitHub 重取，
  但重取后的 digest 未必与记录一致
- `evals/` 16 个合成夹具——**无法恢复**，无副本
- `analyzing-programs-workspace/` 下全部脚本：
  `gate_ab.py`、`truncation.py`、`pin_skill_versions.py`、`preflight.py`、
  `build_benchmark8.py`、`build_benchmark8_html.py`、`grade_v2.py`、
  `merge_judge.py`、`validate_html.py`、`validate_judge.py`、`smoke_benchmark8.js`、
  `coverage_audit.py`、`check_*.py` 等——**无法恢复**
- 三份预注册计划：`iteration-9-plan.md`、`iteration-9b-plan.md`、
  `completion-diagnostic-plan.md`
- `README.md` 的交付边界一节
- iteration-1 至 7 的数据
- iteration-9、iteration-9b 的报告与 `results.json`
- `reference/` 目录、`MANIFEST.json`、`Test-result/` 的 markdown 结论

## 4. 这意味着什么

1. **交付物没丢。** skill 本体字节级完好，两个版本都在，digest 对得上。
   这是唯一真正要交付的东西。
2. **iteration-8 的证据链完整幸存**，包括所有报告原文与 benchmark 输出。
   结论可以复述，但不能重新跑——生成它们的脚本没了。
   重跑出来的数字与幸存的数字**不可比**，因为脚本已非原物。
3. **iteration-9 / 9b / completion-diagnostic 的结论只剩对话记录里的表述**，
   文件证据没了。这些结论本身当时就判为"不可判定"，损失有限。
4. **合成夹具没了**，所以基于合成语料的任何评测无法重现。
5. 任何"重建"脚本并据此重算历史数字的做法都**不应做**——
   那会产生看起来像证据、实际是凭空捏造的数字。

## 5. 已采取的动作

1. 从 `C:\Users\DzwU\.agents\skills\` 复制 skill 回仓库（首次成功，随后被再次清空）
2. 从 `Temp\opencode\i8\` 复制 iteration-8 全部 133 个文件回
   `analyzing-programs-workspace\iteration-8\`（**幸存**）
3. 本文件记录完整损失清单

**注意**：任何写入 `skill/` 目录的内容都可能被再次清掉。
因此 skill 的**权威副本是 `C:\Users\DzwU\.agents\skills\`**，不是仓库。
仓库只放已经确认能存住的东西（`analyzing-programs-workspace/`）。

## 6. 待决

- 是否重建仓库与 git 历史（可以 `git init` 一个新历史，但那不是原历史）
- 是否从 GitHub 重取 abapGit 语料（可以，但 digest 会变）
- 合成夹具无法恢复，所以基于合成语料的评测线到此为止
- 谁在删文件、还在不在删——未查明。在查明之前不应把关键产物放在
  `D:\Workspace\Skills\analyizing-programs\skill\` 下
