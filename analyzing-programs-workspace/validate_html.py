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


def check(cond, msg, detail=""):
    print(("  OK   " if cond else "  FAIL ") + msg + (f"   {detail}" if detail else ""))
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
    # The arm names are carried by the payload, not hardcoded: a round whose arms
    # are named after their skill digest (with_skill_b8f84e8) has no cell under
    # "with_skill", and a hardcoded filter raised instead of reporting anything.
    _md0 = B.get("metadata", {})
    _warm = _md0.get("with_skill_arm") or _md0.get("headline_skill_arm") or "with_skill"
    _barm = _md0.get("without_skill_arm") or _md0.get("baseline_arm") or "without_skill"
    _wc = [c["mean"] for c in data["format"]["cells"] if c["config"] == _warm]
    _bc = [c["mean"] for c in data["format"]["cells"] if c["config"] == _barm]
    if _wc and _bc:
        wf = _st.mean(_wc)
        bf = _st.mean(_bc)
        check(abs(round(wf, 3) - B["summary"]["with_skill_mean"]) < 1e-9,
              f"format {_warm} mean matches benchmark.json ({round(wf, 3)})")
        check(abs(round(bf, 3) - B["summary"]["without_skill_mean"]) < 1e-9,
              f"format baseline mean matches benchmark.json ({round(bf, 3)})")
    else:
        check(False, f"format means could not be cross-checked: no cells for "
                     f"headline arm {_warm} ({len(_wc)}) or baseline {_barm} ({len(_bc)})")
    # The judge sign test must be one pair per (eval, run) — never one per report.
    # Absent on a round whose judge pass has not run for its arms; that is a gap
    # to be reported, not a validator crash.
    if data.get("judge") and isinstance(data["judge"].get("sign"), dict):
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
    else:
        print("  INFO  judge layer not present in payload; judge cross-checks skipped")

    # 7'. A result that cannot name the skill version that produced it cannot be
    # compared with any other result. Rounds 5 and 6 recorded skill_sha256;
    # rounds 7 and 8 did not, so their headline numbers were unattributable and
    # the digest had to be recovered from a git commit message. Absence is now a
    # failure, because the default is to build without saying which skill you ran.
    md = B.get("metadata", {})
    sha = md.get("skill_sha256")
    check(bool(sha) and re.fullmatch(r"[0-9a-f]{64}", sha or ""),
          "benchmark.json records the sha256 of the SKILL.md that produced it",
          sha[:16] + "..." if sha else md.get("skill_sha256_source", "absent"))

    # 7'b. Every skill arm needs its own digest. iteration-9 compares two versions
    # of the skill, and one digest cannot describe two of them -- the ambiguity
    # that left iteration-7 and iteration-8 unattributable in the first place.
    versions = md.get("skill_versions") or {}
    arms = md.get("arms") or ["with_skill", "without_skill"]
    baseline = md.get("baseline_arm", "without_skill")
    want = [a for a in arms if a != baseline]
    missing = [a for a in want if not re.fullmatch(r"[0-9a-f]{64}",
                                                   versions.get(a) or "")]
    check(not missing,
          f"every skill arm names the SKILL.md that produced it "
          f"({len(want)} arm(s))",
          ", ".join(f"{a}={versions.get(a, 'absent')[:12]}"
                    for a in want) if want else "no skill arm recorded")
    check(set(versions) <= set(arms),
          "skill_versions names only arms that exist",
          f"{sorted(versions)} vs {sorted(arms)}")

    # 7'c. If an arm was named after a digest-shaped token, the digest recorded for
    # it must actually be that one. iteration-9 stores two versions side by side,
    # and a transposed pair would pass every structural check while labelling each
    # result with the wrong SKILL.md -- the exact unattributable-round failure this
    # whole block exists to prevent.
    for arm, sha_v in sorted(versions.items()):
        # the digest-shaped token is the arm's trailing segment: with_skill_b8f84e8
        m = re.search(r"_([0-9a-f]{6,40})$", arm)
        tok = m.group(1) if m else None
        if tok and re.fullmatch(r"[0-9a-f]{64}", sha_v or "") \
                and not sha_v.startswith(tok):
            check(False, f"arm {arm} names {tok} but records {sha_v[:8]}...",
                  "digest does not match the arm name")

    # 7''. The discrimination buckets must partition the defect set. They did not:
    # the floor test was `a < 0.5` while a separate test fed the discriminating
    # bucket, so four defects sat in both and the three counts summed to 74 of 77.
    disc = B.get("discrimination")
    if isinstance(disc, dict) and "at_floor_one_arm" in disc:
        disjoint = [k for k in ("saturated_both_arms", "discriminating",
                                "missed_by_both_arms", "tied_mid_range") if k in disc]
        n_sum = sum(disc[k]["n"] for k in disjoint)
        check(n_sum == disc["total_defects"],
              f"discrimination buckets partition the defect set "
              f"({n_sum} == {disc['total_defects']})")
        names = {k: {d["defect"] if isinstance(d, dict) else d
                     for d in disc[k].get("defects", [])} for k in disjoint}
        # `discriminating` itemises its members as skill_wins + skill_loses, not as
        # a flat list, so the subset check needs the union of both.
        for side in ("skill_wins", "skill_loses"):
            names["discriminating"] |= {
                r["defect"] for r in disc["discriminating"].get(side, [])}
        for i, a in enumerate(disjoint):
            for b in disjoint[i + 1:]:
                check(not (names[a] & names[b]),
                      f"  {a} and {b} do not overlap")
        subset = disc["at_floor_one_arm"]
        if subset.get("is_subset_of"):
            host = names.get(subset["is_subset_of"], set())
            got = {d["defect"] if isinstance(d, dict) else d
                   for d in subset.get("defects", [])}
            check(got <= host,
                  f"at_floor_one_arm is inside {subset['is_subset_of']} "
                  f"({len(got)} of {len(host)})")

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