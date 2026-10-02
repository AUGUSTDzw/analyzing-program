#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate generated benchmark.html / review.html before handing them over."""
import json, os, re, sys

WS = sys.argv[1]
DASH = os.path.join(WS, "benchmark.html")
REVW = os.path.join(WS, "review.html")
# review.html only exists for the rounds 3-6 build (build_html.py). Rounds 7+
# ship benchmark.html only, so its absence is not a failure there — otherwise the
# validator hard-fails on the newer layout it was never written for.
WANT_REVIEW = os.path.isfile(os.path.join(WS, "review.html")) or \
    os.path.isdir(os.path.join(WS, "reports"))

fail = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fail.append(msg)


DATA_SRC = None
for path in (DASH, REVW):
    if path == REVW and not WANT_REVIEW:
        print(f"  SKIP  review.html — not part of this round's build")
        continue
    check(os.path.exists(path), f"{os.path.basename(path)} exists")
    if not os.path.exists(path):
        continue
    t = open(path, encoding="utf-8").read()

    # 1. no unreplaced template placeholders. Match ANY __TOKEN__ rather than a
    # fixed list — the iteration-7/8 builders introduce new tokens, and an
    # allowlist silently stops protecting them.
    leftovers = sorted(set(re.findall(r"__[A-Z][A-Z0-9_]*__", t)))
    check(not leftovers, f"{os.path.basename(path)}: no leftover __PLACEHOLDER__ ({leftovers[:3]})")

    # 2. balanced tags for the containers we generate
    for tag in ("html", "head", "body", "script", "style", "table"):
        o = len(re.findall(rf"<{tag}[\s>]", t))
        c = len(re.findall(rf"</{tag}>", t))
        check(o == c, f"{os.path.basename(path)}: <{tag}> balanced ({o} open / {c} close)")

    # 3. embedded JSON parses (dashboard only — review.html has no payload)
    m = re.search(r'<script id="payload" type="application/json">(.*?)</script>', t, re.S)
    if path == REVW:
        check(m is None, f"{os.path.basename(path)}: no payload tag (expected for review page)")
        data = None
    elif m:
        raw = m.group(1).replace("<\\/", "</")
        try:
            data = json.loads(raw)
            check(True, f"{os.path.basename(path)}: embedded payload parses as JSON")
        except Exception as e:
            check(False, f"{os.path.basename(path)}: payload JSON broken -> {e}")
            data = None
    else:
        data = None
        check(False, f"{os.path.basename(path)}: payload script tag missing")

    # `data` came from whichever file last parsed; remember which, so the schema
    # gate below does not label benchmark.html's payload "review.html".
    DATA_SRC = path

    # 4. no raw </script> smuggled inside the JSON payload
    if data:
        check("</script" not in raw.lower(), f"{os.path.basename(path)}: no </script> inside payload")

    # 5. no unescaped angle brackets from markdown leaking as live HTML in review
    if path == REVW:
        check(t.count("<div class=\"md\">") == 4,
              f"review.html: 4 markdown panels present ({t.count(chr(60)+'div class=' + chr(34) + 'md' + chr(34) + '>')})")
        check("&lt;" in t, "review.html: markdown HTML-escaped before embedding")

# The checks below target the rounds 3-6 dashboard schema (rounds / matrixLatest
# / buckets). iteration-7+ emits a different payload (format / judge / assertions /
# findings), so gate on the schema instead of assuming it — otherwise this block
# raises KeyError on a perfectly valid newer page.
LEGACY_DASHBOARD = isinstance(data, dict) and "rounds" in data and "buckets" in data

if data and not LEGACY_DASHBOARD:
    check(True, f"{os.path.basename(DATA_SRC)}: payload is iteration-7+ schema; "
                "rounds 3-6 dashboard checks not applicable")
    # 6'. cross-check the two verdict means against benchmark.json instead
    B = json.load(open(os.path.join(WS, "benchmark.json"), encoding="utf-8"))
    import statistics as _st
    wf = _st.mean(c["mean"] for c in data["format"]["cells"] if c["config"] == "with_skill")
    bf = _st.mean(c["mean"] for c in data["format"]["cells"] if c["config"] == "without_skill")
    check(abs(round(wf, 3) - B["summary"]["with_skill_mean"]) < 1e-9,
          f"format with_skill mean matches benchmark.json ({round(wf, 3)})")
    check(abs(round(bf, 3) - B["summary"]["without_skill_mean"]) < 1e-9,
          f"format baseline mean matches benchmark.json ({round(bf, 3)})")
    # the judge sign test must be one pair per (eval, run) — never one per report
    sp = data["judge"]["sign"]
    check(sp["n_paired"] == data["meta"]["nEvals"] * data["meta"]["runs"],
          f"judge sign test pairs == evals x runs ({sp['n_paired']} == "
          f"{data['meta']['nEvals']} x {data['meta']['runs']})")
    check(len(data["judge"]["perDefect"]) == len(B["judge"]["per_defect"]),
          f"every judged defect reaches the page "
          f"({len(data['judge']['perDefect'])} == {len(B['judge']['per_defect'])})")
    check(len(data["assertions"]) == len(B["assertion_stats"]),
          f"every assertion reaches the page "
          f"({len(data['assertions'])} == {len(B['assertion_stats'])})")

elif data and LEGACY_DASHBOARD:
    # 6. cross-check dashboard numbers against grading_summary.json
    gs = json.load(open(os.path.join(WS, "grading_summary.json"), encoding="utf-8"))
    exp_w = round(sum(gs[k]["pass_rate"] for k in
                      ("eval-1-with_skill", "eval-2-with_skill")) / 2, 4)
    exp_b = round(sum(gs[k]["pass_rate"] for k in
                      ("eval-1-without_skill", "eval-2-with_skill")) / 2, 4)
    got = data["rounds"][-1]
    check(got["with_mean"] == exp_w,
          f"with_skill mean matches grading_summary ({got['with_mean']} == {exp_w})")
    check(got["without_mean"] == exp_b,
          f"baseline mean matches grading_summary ({got['without_mean']} == {exp_b})")

    # 7. every assertion text referenced exists; aid sets align across runs
    aids_runs = {r: sorted(v) for r, v in data["matrixLatest"].items()}  # legacy schema
    union = sorted({a for v in aids_runs.values() for a in v})
    check(union == sorted({a for v in data["assertionText"].values() for a in v}),
          f"matrixLatest and assertionText cover the same aids ({len(union)} aids)")
    per_run = {r: len(v) for r, v in aids_runs.items()}
    print(f"  INFO  aids per run: {per_run}")

    # 8. bucket arithmetic: gain + nondisc + mixed + failboth == 11
    tot = (len(data["buckets"]["skill_gain"]) + len(data["buckets"]["non_discriminating"])
           + len(data["buckets"]["mixed"]) + len(data["buckets"]["fail_both"]))
    check(tot == 11, f"buckets partition all 11 shared assertions (got {tot})")

    # 9. regression count must equal with_skill FAIL count
    n_fail = sum(1 for r, m2 in data["matrixLatest"].items()
                 if r.endswith("with_skill") for v in m2.values() if not v)
    check(len(data["buckets"]["regression"]) == n_fail,
          f"regression list matches with_skill FAIL count "
          f"({len(data['buckets']['regression'])} == {n_fail})")

print("\n" + ("ALL CHECKS PASSED" if not fail else f"{len(fail)} CHECK(S) FAILED"))
sys.exit(1 if fail else 0)