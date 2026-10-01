# Analyzing Programs

ABAP/SAP 源码分析报告 Skill。给定一个 ABAP 程序文件，自动输出结构规范的中文分析报告。

## 功能说明

针对 ABAP 程序（报表、FORM/事件块、OO 类、函数组、ALV 等）生成一份 **6 章结构**的中文分析报告：

| 章节 | 内容 |
|------|------|
| 一、程序定位与业务背景 | 问题陈述、业务背景、设计范式定性 |
| 二、程序执行流程总览 | Mermaid 流程图 + 责任链表格 |
| 三、分组分析 | 每个子程序：做什么 / 为什么 / 风险（三层格式） |
| 四、执行流程全景图 | Mermaid 时序图，展示数据流转 |
| 五、问题清单与改进建议 | P0–P3 分级问题，用子程序名标注位置 |
| 六、整体评价与启发 | 优点、短板、设计经验总结 |

## 目录结构

```
analyzing-programs/
├── SKILL.md                          # Skill definition (prompt rules)
├── evals/                            # 评测素材
│   ├── evals.json                    # 评测定义（提示词、预期输出）
│   ├── ztest7.abap                   # 评测 1 源文件：ALV 可编辑合计示例
│   └── zmmr_vend_list.abap           # 评测 2 源文件：过程式供应商报表
└── analyzing-programs-workspace/     # 迭代产物
    ├── build_benchmark.py            # 从 grading_summary.json 生成 benchmark.json
    ├── grade.py                      # 评分驱动脚本（iteration-1）
    ├── grade3.py                     # 评分驱动脚本（iteration-3）
    ├── iteration-1/                  # 第一轮评测
    │   ├── benchmark.json            # 评测结果
    │   ├── grading_summary.json      # 原始分数
    │   ├── review.html               # 人工审查页面
    │   └── eval-*/{with,without}_skill/outputs/
    ├── iteration-2/                  # 第二轮（部分完成）
    └── iteration-3/                  # 最新一轮
        ├── benchmark.json
        ├── grading_summary.json
        ├── review.html
        └── eval-*/{with,without}_skill/outputs/
```

## 评测流程

每轮迭代遵循相同流程：

1. **运行 skill** 对每个源文件生成报告 → `eval-*/with_skill/outputs/report.md`
2. **运行基线**（同一提示词，无 skill 引导） → `eval-*/without_skill/outputs/report.md`
3. **评分** → 生成 `grading.json`（单条）+ `grading_summary.json`（汇总）
4. **构建 benchmark** → `benchmark.json`（跨轮对比摘要）
5. **人工审查** → 浏览器打开 `review.html` 进行对比

脚本说明：
- `grade.py` / `grade3.py` — 批量运行评分器
- `build_benchmark.py` / `build_benchmark3.py` — 聚合生成交叉轮次摘要

## 最新结果（Iteration 3）

| 配置 | 通过率 | 说明 |
|------|--------|------|
| **with_skill** | 100% (12/12) | 全部结构断言通过 |
| **without_skill** | 18–55% | 缺少 A2（责任链表）、A4（时序图）、A7（P0/P3 分级）、A8（三层格式） |

Skill 显著提升了对 6 章结构和三层分析格式的合规率。

## 核心规则（来自 SKILL.md）

- **不引用源码行号** — 使用子程序/方法名标注位置
- **三层格式强制** — 每个 ` ```abap ` 代码块后必须跟「做什么 / 为什么 / 风险」
- **Mermaid 标签安全** — 节点标签中不得出现裸 `<` / `>` 符号
- **按执行流分组** — 而非源码出现顺序
- **默认中文输出** — 用户指定其他语言时跟随
