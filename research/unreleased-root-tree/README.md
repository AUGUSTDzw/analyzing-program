# 未发布的根目录开发线（unreleased root tree）

**这里不是出货的 skill，也不要把它当出货的 skill。**
出货版本是 `release/analyzing-programs-1.0.2/`（SKILL.md = `006719f8`）。
本目录原先躺在仓库根目录（`./SKILL.md`、`./scripts/`、`./references/`、
`./schemas/`、`./tests/`、`./evals/README.md` 与 6 个 `*.defects.json`），
2026-10-07 移到这里，原因只有一个：根目录那份 `SKILL.md` 最像"当前版本"，
而它不是——我自己第一眼就看错了。

## 它不是旧物，是一条更靠前但从未发布的线

一度以为它是历史遗留。核对后结论相反：**它在工具侧领先于已发布线**。

| 文件 | 本目录 | 1.0.2 出货 | 差在哪 |
|---|---|---|---|
| `SKILL.md` | `b3dae1ba` 300 行 | `006719f8` 250 行 | 本目录多「Gate Output」与「大输入」两节 |
| `scripts/report_qc.py` | `42ea0d79` 45523 B / 1038 行 | `d91d3a56` 24224 B | 本目录多 `fix_mislabel` 诊断与 `fence` 缺陷 |
| `scripts/evaluate.py` | `2410fe04` 14458 B | `d42d3623` 12359 B | — |
| `schemas/report-contract.json` | `24c9bc2a` 7844 B / 147 行 | `8cabb0b4` 8449 B | **两边各自演化，不是包含关系** |
| `tests/test_skill.py` | `325f5658` 37190 B / 771 行 | `d65a1cc8` 14832 B | 本目录 95 项且打印计数；出货版不打印计数 |
| `tests/test_contract_drift.py` | `f8db979d` 14073 B / 310 行 | `b4c53172` 6342 B | 本目录 101 项；出货版更少 |
| `references/large-inputs.md` | `d68ada1f` 2017 B | `dd6d22c0` 7387 B | 本目录是拆成五个文件后的索引 |
| `references/example-report.md` | `3bc277a5` | `3bc277a5` | 相同 |

两条线各自内部自洽：1.0.2 的 SKILL.md 教的三条诊断与它的闸门对得上，
本目录的 SKILL.md 教的四条与它那份 1038 行的闸门对得上。
**因此不能整份覆盖或整份合并**，只能逐项挑。

## 已验证可独立运行

`tests/` + `schemas/` + `scripts/` + `SKILL.md` + `references/` 五个目录
丢进一个空目录即可运行，不依赖 `evals/` 与 `analyzing-programs-workspace/`：
实测 `95 checks passed` 与 `101 drift checks passed`。
而 1.0.2 出货的那套测试更弱，且不打印计数——这是出货线的一个已知短板。

## 未决

1. 出货线是否换成这套更强的 `tests/`（可让 README 的检查项计数重新可验证）。
2. `fix_mislabel` 诊断与 `fence` 缺陷要不要进出货闸门；进了 SKILL.md 必须同步教。
3. 本目录的 `contract` 与 1.0.2 的 `contract` 已经分叉，合并前要先定哪边是基线。
4. 本目录 SKILL.md 有一条**有害条款**：「输出停在第三节中间时，在第六节里明说覆盖范围」
   ——而 `references/truncated-reports.md` 记录过一份 465 行残篇被当完整报告计入聚合、
   误报出「A8 缺陷从 50 降到 15」。合并时不要带这句。