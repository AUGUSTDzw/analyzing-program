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
│   ├── judge-defects.json            # 77 planted defects across 13 evals
│   ├── planted-defects.md            # Evals 1-5, human-readable, with fairness notes
│   ├── ztest7.abap                   # Eval 1: procedural report, editable ALV + totals
│   ├── zmmr_vend_list.abap           # Eval 2: procedural vendor report
│   ├── zcl_stock_check.clas.abap     # Eval 3: global OO class, 9 methods, ALV grid
│   ├── zfg_material_price.fg.abap    # Eval 4: function group main program
│   ├── lzfg_material_pacetop.abap    # Eval 4: function group global data
│   ├── lzfg_material_pacu01.abap     # Eval 4: function group FM implementations
│   ├── zreport_bapi_upload.abap      # Eval 5: report calling BAPI + remote RFC
│   ├── zsalv_po_list.abap            # Eval 6: OO ALV, aggregations, events, popup
│   ├── zcl_grade_calc.clas.abap      # Eval 7: abstract superclass, inheritance,
│   │                                 #   polymorphism, locking, number range
│   ├── zorder_dialog.abap            # Eval 8: dynpro PBO/PAI, AT SELECTION-SCREEN
    │   ├── zsales_synch.abap            # Eval 9: CDS consumer + CL_HTTP_CLIENT + JSON
    │   ├── zi_vbak_open.asddls         # Eval 9: the CDS view DDL source it consumes
    │   ├── zprice_batch.abap            # Eval 10: SY-BATCH branching, conditional COMMIT
    │   ├── zcl_price_watch.clas.abap    # Eval 11: CLASS-EVENTS publish + two subscribers
    │   ├── zvendor_notify.abap          # Eval 12: ENQUEUE/DEQUEUE, MESSAGE ID
    │   └── zmodern_lo.abap              # Eval 13: inline DATA(), FILTER, REDUCE, VALUE #
├── Test-source/                      # Ad-hoc analysis inputs (not part of the eval set)
│   └── real/                         # Real open-source ABAP, provenance in MANIFEST.json
│                                     #   abapGit (MIT) + SAP-samples (Apache-2.0); up to 1598
│                                     #   lines, adds FIELD-SYMBOL / INCLUDE layers / RAP+BDL
├── Test-result/                      # Reports produced from Test-source
│   ├── generality-audit.md           # Generality + correctness evidence for real-world input
│   ├── judge-zvend.json              # Independent judge's own 21-defect list + 2-run scores
│   ├── zr.*                          # zr.abap run 3x on the SAME skill version to measure
│   │                                 #   stability: baseline 72% / skill 75% / skill 100%
│   │                                 #   of 32 defect fingerprints
│   └── real/*.skill.md               # Reports over the fetched real-world corpus
└── analyzing-programs-workspace/     # Iteration artifacts
    ├── grade.py                      # Scoring driver (iteration-1)
    ├── grade3.py                     # Scoring driver (iteration-3..6, 4 hardcoded evals)
    ├── grade_v2.py                   # Scoring driver (iteration-7+): N evals x N runs,
    │                                 #   source-derived triggers, A13 coverage, McNemar
    ├── check_fixtures.py             # Dry-run: files exist, A13 inventory non-trivial,
    │                                 #   ≥1 content trigger fires. Imports its
    │                                 #   derivations from grade_v2.py (no duplicated regexes)
    ├── coverage_audit.py             # Maps 41 ABAP constructs onto the eval set; prints gaps
    ├── merge_judge.py                # Folds judge/*.json into grading_summary.json
    ├── validate_judge.py             # Invariants on the judge merge (coverage, arithmetic,
    │                                 #   sign-test pairing — counts derived, never hardcoded)
    ├── build_benchmark4.py           # Cross-iteration compare (rounds 3-6)
    ├── build_benchmark7.py           # iteration-7 benchmark.json, honest measurement notes
    ├── build_benchmark7_html.py      # iteration-7 benchmark.html (two verdict layers)
    ├── smoke_benchmark7.js           # Executes the page JS against a stub DOM/ECharts
    ├── build_benchmark8.py           # iteration-8 benchmark.json; findings + discrimination
    │                                 #   analysis are COMPUTED from data, not hardcoded prose
    ├── build_benchmark8_html.py      # iteration-8 benchmark.html; all counts injected from
    │                                 #   benchmark.json and asserted fully substituted
    ├── smoke_benchmark8.js           # Row counts + defect-key coverage derived from payload
    ├── build_html.py                 # Renders benchmark.html + review.html (rounds 3-6)
    ├── validate_html.py              # Static checks on generated HTML
    ├── smoke_benchmark.js            # Executes benchmark.html JS (rounds 3-6)
    ├── smoke_review.js               # Executes review.html markdown render loop
    ├── verify_review_embed.js        # Proves embedded reports match report.md byte-for-byte
    ├── iteration-1/ … iteration-7/   # Earlier rounds (see Iteration History)
    └── iteration-8/                  # Latest: 13 program types, 41 constructs, 77 defects,
        ├── benchmark.json            #   2 runs, paired tests, judge + discrimination
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

## Eval set coverage

`coverage_audit.py` inventories 41 ABAP constructs against the fixtures.
Rounds 3-7 tested one program type; the set now spans 13:

| eval | Program type | Key constructs exercised |
|---|---|---|
| 1 | Procedural report | `REUSE_ALV_GRID_DISPLAY`, editable totals, `DATA_CHANGED` |
| 2 | Procedural report | `REUSE_ALV_FIELDCATALOG_MERGE`, inline host vars |
| 3 | Global OO class | `CLASS-POOL`, `CL_GUI_ALV_GRID`, `SET HANDLER`, `CALL SCREEN`, `CX_` |
| 4 | Function group | `FUNCTION-POOL` + TOP + U01, shared global data |
| 5 | Report + integration | `BAPI_MATERIAL_MAINTAIN`, RFC `DESTINATION` |
| 6 | OO ALV | `CL_SALV_TABLE`, aggregations, `double_click`/`link_click`, popup |
| 7 | Inheritance | abstract superclass, `INHERITING`, `super->`, redefinition, polymorphism |
| 8 | Dialog program | dynpro 0100, `MODULE` PBO/PAI, `AT SELECTION-SCREEN`, `AUTHORITY-CHECK` |
| 9 | CDS + HTTP | ABAP SQL on a CDS entity, `CL_HTTP_CLIENT`, JSON assembly |
| 10 | Background batch | `SY-BATCH` branching, conditional `COMMIT WORK` |
| 11 | Class events | `CLASS-EVENTS`, `RAISE EVENT`, `FOR EVENT` subscribers |
| 12 | Locking + message class | `ENQUEUE`/`DEQUEUE`, `MESSAGE ID`/`NUMBER` |
| 13 | Modern syntax | inline `DATA()`, `FILTER`, `REDUCE`, `VALUE #`, string templates |

**All 41 constructs are now exercised.** The gaps that were closed, and what each
new fixture turned out to be for:

| Gap | Closed by | Why it matters |
|---|---|---|
| `CL_SALV_TABLE`, inheritance, dialog flow | evals 6-8 | The three largest. The OO ALV is the default choice for new reports, and a report can be mostly inheritance or mostly screen flow. |
| `CLASS-EVENTS`, HTTP/JSON, background, message class, CDS | evals 9-12 | Publishing/subscriber events, outbound REST, batch-safe transaction handling, the *correct* `MESSAGE ID` pattern, and a DDL source shipped alongside its consumer. |
| inline `DATA()` as a statement | eval 13 | Modern syntax has scoping rules (`DATA(x)` is visible only inside its FORM) that are a genuine source of bugs. |

`check_fixtures.py` asserts per eval that the files exist, the A13 subprogram
inventory is non-trivial (a vacuous inventory would make A13 pass trivially), and
at least one content assertion's trigger fires. It imports its trigger and
subprogram derivations from `grade_v2.py` rather than keeping a second copy —
an earlier version duplicated the regexes and silently disagreed with the grader
about `MODULE`, which is how the A13-vacuous-on-dialog-programs bug surfaced.

Fixtures are synthetic, authored for this benchmark to match the constructs SAP Help
and SAP Community document. They are not copied from any customer system. Every
fixture carries planted defects listed in `evals/judge-defects.json` (77 across
13 evals), with a human-readable annotation of the first eight in
`evals/planted-defects.md`.


## Iteration History

| Round | evals | runs | with_skill | without_skill | Finding |
|-------|-------|------|-----------|---------------|---------|
| iteration-3 | 2 | 1 | 100% | 52% | Structural compliance first achieved |
| iteration-4 | 2 | 1 | 91% | 47% | **A8 regression** — `SKILL.md`'s "three-layer per block" rule fought its own "split into ① ② ③" rule |
| iteration-5 | 2 | 1 | 100% | 43% | A8 fix landed in `SKILL.md` ("拆分步骤时怎么办" section with compact bold-label template) |
| iteration-6 | 2 | 1 | 100% | 39% | Same SKILL.md re-run; **0pp spread** confirmed format compliance is deterministic |
| iteration-7 | **5** | **2** | 0.987 / 0.766 | 0.546 / 0.729 | **Coverage 1→5 program types; format significant (p=2.4e-19) but technical correctness NOT (p=1.00)** |
| iteration-8 | **13** | **2** | 0.980 / 0.849 | 0.554 / 0.826 | **Coverage 5→13 program types / 41 constructs. Format still significant (p=5.6e-44) but the judge layer CEILINGED: 46/77 defects full marks for BOTH arms, so technical correctness is unmeasurable, not merely flat (p=1.00)** |

### iteration-8: the judge layer stopped discriminating

Widening the eval set did not widen the gap — it removed the ability to measure one.
With 77 planted defects across 13 program types, **46 (60%) are scored full marks by
both arms**, and only 21 of 77 discriminate at all. At `with_skill` 0.849 vs baseline
0.826 there is no headroom left, so a null result here means *the benchmark ran out of
difficulty*, not that the skill is provably neutral on code review.

Consequences for how this table should be read:

- The format result (`p = 5.6e-44`, 170 with-only vs 5 baseline-only cells) is solid and
  strengthened by the wider set.
- The technical result is **not evidence of equivalence**. The correct next step is a
  harder defect tier, not more runs; `benchmark.json → discrimination` records the
  saturated, floor, and discriminating sets explicitly.
- Two bugs found and fixed while producing this round would each have hidden a real
  effect (see `Known limitations`).


> Rounds 3–6 are not directly comparable to 7: the grader changed, the eval set grew, and
> the scoring model moved from mean-of-assertions to paired tests. Their `benchmark.json`
> files record `skill_sha256` where the digest was captured, so "same skill version" is
> verifiable rather than assumed.

## Known limitations

- **The judge layer has ceilinged** (iteration-8). 46 of 77 planted defects are full marks
  for both arms; 7 more are missed by both. A null technical result is therefore
  uninterpretable until the defect tier gets harder.
- The judge is a single pass with no inter-rater agreement data. Add a second judge and
  report Cohen's kappa before treating the technical layer as authoritative.
- Planted defects are 4–10 per fixture by construction; the absolute recall numbers do not
  extrapolate to real code. Only the with/baseline *relative* comparison is meaningful.
- n=2 supports the sign test but not variance estimation. Raise to 3 runs and run a power
  analysis to distinguish "skill has no effect" from "not enough samples".
- **The skill is not self-validating.** On real open-source input it has produced
  fabricated code statements and asserted that genuinely broken syntax was fine. Treat it as a
  *first-pass reading checklist*, not as a defect oracle — see `Test-result/generality-audit.md`.

### Generalality and correctness on real-world input

`Test-result/generality-audit.md` records the full evidence. Headline:

| | baseline | skill |
|---|---|---|
| Six-section structure, 2 Mermaid diagrams, responsibility table | — | **7/7 reports pass** |
| Locating issues by name rather than line number | — | **7/7 pass** |
| A8 three-layer labels after every abap block | — | **154/170 blocks** |
| `zvend.abap`, 21 judge-derived defects | — | run1 0.833 / run2 0.738, 8/21 disagree |
| Verbatim fidelity to the source | — | **fails** (invented `ASSERT`, `ELSE.` → `ELSE:`) |

Real-world corpus: 10 files from abapGit (MIT) and SAP-samples (Apache-2.0), up to 1598 lines,
covering `FIELD-SYMBOL`, `INCLUDE` layers, global classes, RAP behavior definitions and CDS —
with provenance pinned per file in `Test-source/real/MANIFEST.json`. Still uncovered: AMDP,
BADI implementations, class pools / function modules, dynamic SQL.

Two failure modes recur and are the highest-value fixes:
1. **Confident wrongness.** When unsure of a syntax/environment detail, the skill asserts the
   construct is valid. Both `zvend` runs explicitly backed an unqualified `JOIN ... WHERE bedat`
   as "unambiguous" when the field is ambiguous across `EKKO`/`EKPO`.
2. **A8 lapses specifically on remediation code.** The three-layer rule is documented, but 16/170
   missing blocks cluster entirely where the report shows *corrected* code and then comments on it
   in unlabeled prose.

### Measurement bugs found in iteration-8 (both fixed, both regression-guarded)

These are recorded because each one *silently* produced a plausible-looking number:

1. **`merge_judge.py` double-counted every sign-test pair.** It iterated all 52 `per_run`
   records and matched each to its counterpart, so each pair was counted twice with
   mirrored signs — which forces `with_higher == baseline_higher` and pins `p` at 1.0
   regardless of the real effect. iteration-7 had reported `9 better / 9 worse / 2 ties`
   over "20 pairs"; the true figures are **5 / 4 / 1 over 10 pairs**. Fixed by walking only
   the `with_skill` arm. `validate_judge.py` now recomputes the tallies from `per_run` and
   fails if they disagree.
2. **`merge_judge.py` emitted `per_defect` rows for evals that were never judged.** It
   walked the whole `judge-defects.json` master list, so re-running merge on the older
   iteration-7 directory produced 53 phantom rows with `n=0` (24 → 77 defects) and skewed
   any mean computed over them. Now restricted to the evals actually judged, with a
   validation that every row has a non-zero sample count.
3. **`validate_judge.py` and the smoke tests hardcoded counts** (20 reports / 24 defects /
   19 assertions), so they passed against stale expectations after the eval set grew. Both
   now derive counts from the payload; `smoke_benchmark8.js` additionally asserts every
   defect key actually reaches the DOM, which a row count alone cannot catch.

## Core Rules (from SKILL.md)

- **No source line numbers** — locate issues by subprogram/method name instead
- **Three-layer format is mandatory** — every ` ```abap ` code block in chapter 3 must be followed by "what it does / why / risks". **Splitting a block into ① ② ③ does not exempt a step from the three layers**; use the compact bold-label form rather than unlabeled prose.
- **Mermaid label safety** — no bare `<` / `>` characters in node labels
- **Group by execution flow** — not by the order code appears in the file
- **Chinese output by default** — follows another language if the user specifies one