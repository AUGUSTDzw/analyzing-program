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
├── skill/analyzing-programs/
│   └── SKILL.md                      # Skill definition (prompt rules)
├── evals/                            # Evaluation material
│   ├── evals.json                    # Eval definitions (prompt, files).
│   │                                 #   Triggers are NOT stored — grade_v2.py
│   │                                 #   derives them from source at grading time.
│   ├── judge-defects.json            # Planted defects per eval (machine-readable)
│   ├── planted-defects.md            # Same, human-readable, with fairness notes
│   ├── ztest7.abap                   # Eval 1: procedural report, editable ALV + totals
│   ├── zmmr_vend_list.abap           # Eval 2: procedural vendor report
│   ├── zcl_stock_check.clas.abap     # Eval 3: global OO class, 9 methods, ALV grid
│   ├── zfg_material_price.fg.abap    # Eval 4: function group main program
│   ├── lzfg_material_pacetop.abap    # Eval 4: function group global data
│   ├── lzfg_material_pacu01.abap     # Eval 4: function group FM implementations
│   └── zreport_bapi_upload.abap      # Eval 5: report calling BAPI + remote RFC
├── Test-source/                      # Ad-hoc analysis inputs (not part of the eval set)
├── Test-result/                      # Reports produced from Test-source
└── analyzing-programs-workspace/     # Iteration artifacts
    ├── grade.py                      # Scoring driver (iteration-1)
    ├── grade3.py                     # Scoring driver (iteration-3..6, 4 hardcoded evals)
    ├── grade_v2.py                   # Scoring driver (iteration-7): N evals x N runs,
    │                                 #   source-derived triggers, A13 coverage, McNemar
    ├── check_fixtures.py             # Dry-run: fixture triggers vs declared, A13 sanity
    ├── merge_judge.py                # Folds judge/*.json into grading_summary.json
    ├── validate_judge.py             # Invariants on the judge merge (coverage, arithmetic)
    ├── build_benchmark4.py           # Cross-iteration compare (rounds 3-6)
    ├── build_benchmark7.py           # iteration-7 benchmark.json, honest measurement notes
    ├── build_benchmark7_html.py      # iteration-7 benchmark.html (two verdict layers)
    ├── smoke_benchmark7.js           # Executes the page JS against a stub DOM/ECharts
    ├── build_html.py                 # Renders benchmark.html + review.html (rounds 3-6)
    ├── validate_html.py              # Static checks on generated HTML
    ├── smoke_benchmark.js            # Executes benchmark.html JS (rounds 3-6)
    ├── smoke_review.js               # Executes review.html markdown render loop
    ├── verify_review_embed.js        # Proves embedded reports match report.md byte-for-byte
    ├── iteration-1/ … iteration-6/   # Earlier rounds (see Iteration History)
    └── iteration-7/                  # Latest: 5 program types, 2 runs, paired tests, judge
        ├── benchmark.json            # Aggregates + headline findings
        ├── benchmark.html            # Two verdict layers, side by side
        ├── grading_summary.json      # Per-run assertions + merged judge verdicts
        ├── judge/                    # Raw LLM judge output, one file per eval x config
        └── eval-<id>-<name>/{with_skill,without_skill}/run-<k>/outputs/report.md
```

## Evaluation Flow

Every iteration round follows the same flow:

1. **Run the skill** against each source file → `eval-*/with_skill/run-k/outputs/report.md`
2. **Run the baseline** (same prompt, no skill guidance) → `eval-*/without_skill/run-k/...`
3. **Score** → `grade_v2.py` produces `grading.json` (per item) and `grading_summary.json`
4. **Judge** (iteration-7+) → one judge pass per (eval, config) writing `judge/*.json`,
   then `merge_judge.py` folds verdicts in
5. **Build benchmark** → `benchmark.json` + `benchmark.html`
6. **Validate** → `validate_judge.py`, `smoke_benchmark7.js`

Fixtures live in `evals/`; the planted-defect manifest is `evals/judge-defects.json`
(human-readable version in `evals/planted-defects.md`).

## Evaluation Flow

Every iteration round follows the same flow:

1. **Run the skill** against each source file → `eval-*/with_skill/outputs/report.md`
2. **Run the baseline** (same prompt, no skill guidance) → `eval-*/without_skill/outputs/report.md`
3. **Score** → produces `grading.json` (per item) and `grading_summary.json` (aggregate)
4. **Build benchmark** → `benchmark.json` (cross-round comparison summary)
5. **Manual review** → open `review.html` in a browser to compare side by side

Scripts:
- `grade.py` / `grade3.py` — batch-run the grader
- `build_benchmark.py` / `build_benchmark3.py` / `build_benchmark4.py` — aggregate into a cross-round summary
- `build_html.py <newest-ws> [<older-ws> ...]` — renders `benchmark.html` + `review.html`
- `validate_html.py <ws>` · `smoke_benchmark.js` · `smoke_review.js` · `verify_review_embed.js` — verification pass over the generated HTML

## Latest Results (Iteration 7) — two independent verdict layers

Iteration 7 separated **format compliance** from **technical correctness** and did
NOT average them. They disagree, and the disagreement is the finding.

| Layer | with_skill | without_skill | Test | Result |
|---|---|---|---|---|
| **① Format compliance** (19 structural assertions) | **0.987** | 0.546 | McNemar exact on 304 paired cells: 68 vs 1 | p = 2.4e-19 — **significant** |
| **② Technical correctness** (24 planted defects, LLM judge) | 0.766 | 0.729 | Paired sign test: 9 better / 9 worse / 2 ties | p = 1.00 — **NOT significant** |

**The skill reliably produces well-structured reports. It does not make the analysis
measurably more accurate.** A bare model already catches ~73% of planted defects.

Coverage went from 1 program type to 5: procedural report (ALV editable), procedural
report (vendor list), **global OO class**, **function group with RFC**, **report calling
BAPI + RFC**.

### What changed in the harness

- **5 evals × 2 configs × 2 runs**, paired design — replaced `runs_per_configuration = 1`.
- **Paired statistics, not variance.** With n=2 a stddev estimates nothing. Iteration 7 uses
  McNemar exact (format) and a sign test (judge) on matched (eval, run) pairs.
- **Triggers derived from source.** Every content assertion's applicability is computed by
  regex over the fixture, so a trigger cannot drift from the code. Non-firing assertions are
  recorded as `skipped` and excluded from the denominator.
- **A13 coverage assertion** — every `FORM`/`METHOD`/`FUNCTION` in the source must be named
  in the report. Triggered from the fixture, not hand-listed.
- **LLM judge replaces keyword assertions.** A14–A19 (keyword presence) turned out to be
  worthless: *every* run including bare-model baselines scored 100%. Judge verdicts live in
  `iteration-7/judge/*.json` and are merged by `merge_judge.py`.
- **Fake zeros removed.** `tokens` is gone (unobservable, and `0` was indistinguishable from a
  real zero). `time_seconds` is not collected; report mtimes are recorded as `generated_at_utc`
  with an explicit note that they are not a duration. `stddev` is omitted from the headline.
- **Assertion A8 corrected (v1 → v2).** v1 demanded one three-layer set per ```abap block,
  which penalised a good report for embedding short snippets as inline evidence inside its own
  风险与改进 prose. Verified by reading iteration-7 eval-3/with/run-2 manually: fully compliant,
  yet scored 22/33. v2 counts `#### ① ② ③` sub-steps.

## Iteration History

| Round | evals | runs | with_skill | without_skill | Finding |
|-------|-------|------|-----------|---------------|---------|
| iteration-3 | 2 | 1 | 100% | 52% | Structural compliance first achieved |
| iteration-4 | 2 | 1 | 91% | 47% | **A8 regression** — `SKILL.md`'s "three-layer per block" rule fought its own "split into ① ② ③" rule |
| iteration-5 | 2 | 1 | 100% | 43% | A8 fix landed in `SKILL.md` ("拆分步骤时怎么办" section with compact bold-label template) |
| iteration-6 | 2 | 1 | 100% | 39% | Same SKILL.md re-run; **0pp spread** confirmed format compliance is deterministic |
| iteration-7 | **5** | **2** | 0.987 / 0.766 | 0.546 / 0.729 | **Coverage 1→5 program types; format significant (p=2.4e-19) but technical correctness NOT (p=1.00)** |

> Rounds 3–6 are not directly comparable to 7: the grader changed, the eval set grew, and
> the scoring model moved from mean-of-assertions to paired tests. Their `benchmark.json`
> files record `skill_sha256` where the digest was captured, so "same skill version" is
> verifiable rather than assumed.

## Known limitations

- The judge is a single pass with no inter-rater agreement data. Add a second judge and
  report Cohen's kappa before treating the technical layer as authoritative.
- Planted defects are 4–6 per fixture by construction; the absolute recall numbers do not
  extrapolate to real code. Only the with/baseline *relative* comparison is meaningful.
- n=2 supports the sign test but not variance estimation. Raise to 3 runs and run a power
  analysis to distinguish "skill has no effect" from "not enough samples".

## Core Rules (from SKILL.md)

- **No source line numbers** — locate issues by subprogram/method name instead
- **Three-layer format is mandatory** — every ` ```abap ` code block in chapter 3 must be followed by "what it does / why / risks". **Splitting a block into ① ② ③ does not exempt a step from the three layers**; use the compact bold-label form rather than unlabeled prose.
- **Mermaid label safety** — no bare `<` / `>` characters in node labels
- **Group by execution flow** — not by the order code appears in the file
- **Chinese output by default** — follows another language if the user specifies one