# Analyzing Programs

A Skill for producing structured analysis reports of ABAP/SAP source code. Given an ABAP program file, it automatically generates a well-structured Chinese analysis report.

## What It Does

For an ABAP program (report, FORM/event block, OO class, function group, ALV, etc.), the skill generates a Chinese analysis report with a fixed **6-chapter** structure:

| Chapter | Content |
|---------|---------|
| 1. Program Positioning & Business Context | Problem statement, business background, design paradigm classification |
| 2. Execution Flow Overview | Mermaid flowchart + responsibility-chain table |
| 3. Grouped Analysis | Per subprogram: what it does / why / risks (three-layer format) |
| 4. Full Execution Panorama | Mermaid sequence diagram showing data flow |
| 5. Issue List & Improvement Suggestions | P0–P3 graded issues, each tagged with its subprogram name |
| 6. Overall Assessment & Takeaways | Strengths, gaps, distilled design lessons |

## Directory Structure

```
analyzing-programs/
├── SKILL.md                          # Skill definition (prompt rules)
├── evals/                            # Evaluation material
│   ├── evals.json                    # Eval definitions (prompts, expected output)
│   ├── ztest7.abap                   # Eval 1 source: editable ALV totals example
│   └── zmmr_vend_list.abap           # Eval 2 source: procedural vendor report
└── analyzing-programs-workspace/     # Iteration artifacts
    ├── build_benchmark.py            # Generates benchmark.json from grading_summary.json
    ├── grade.py                      # Scoring driver script (iteration-1)
    ├── grade3.py                     # Scoring driver script (iteration-3)
    ├── iteration-1/                  # First evaluation round
    │   ├── benchmark.json            # Eval results
    │   ├── grading_summary.json      # Raw scores
    │   ├── review.html               # Manual review page
    │   └── eval-*/{with,without}_skill/outputs/
    ├── iteration-2/                  # Second round (partially complete)
    └── iteration-3/                  # Latest round
        ├── benchmark.json
        ├── grading_summary.json
        ├── review.html
        └── eval-*/{with,without}_skill/outputs/
```

## Evaluation Flow

Every iteration round follows the same flow:

1. **Run the skill** against each source file → `eval-*/with_skill/outputs/report.md`
2. **Run the baseline** (same prompt, no skill guidance) → `eval-*/without_skill/outputs/report.md`
3. **Score** → produces `grading.json` (per item) and `grading_summary.json` (aggregate)
4. **Build benchmark** → `benchmark.json` (cross-round comparison summary)
5. **Manual review** → open `review.html` in a browser to compare side by side

Scripts:
- `grade.py` / `grade3.py` — batch-run the grader
- `build_benchmark.py` / `build_benchmark3.py` — aggregate into a cross-round summary

## Latest Results (Iteration 3)

| Configuration | Pass rate | Notes |
|----------------|-----------|-------|
| **with_skill** | 100% (12/12) | All structural assertions pass |
| **without_skill** | 18–55% | Missing A2 (responsibility-chain table), A4 (sequence diagram), A7 (P0/P3 grading), A8 (three-layer format) |

The skill markedly improves compliance with the 6-chapter structure and the three-layer analysis format.

## Core Rules (from SKILL.md)

- **No source line numbers** — locate issues by subprogram/method name instead
- **Three-layer format is mandatory** — every ` ```abap ` code block must be followed by "what it does / why / risks"
- **Mermaid label safety** — no bare `<` / `>` characters in node labels
- **Group by execution flow** — not by the order code appears in the file
- **Chinese output by default** — follows another language if the user specifies one