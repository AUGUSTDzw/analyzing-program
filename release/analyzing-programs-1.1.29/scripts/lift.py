#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Measure the lift of a skill over a baseline.

    python scripts/lift.py --defects defects.json \
                           --with-skill verdicts_with.json \
                           --without-skill verdicts_without.json

Reads two verdict JSON files (produced by evaluating a report with and
without the skill's guidance) against the same defect list, computes the
recall delta and false-claim delta, and runs an exact two-sided sign test
on the paired verdicts.

Exit codes:
  0  the comparison ran cleanly (the result may be positive, negative, or
     indistinguishable from noise -- this is a reporter, not a gate)
  2  refused -- a required argument is missing, a file does not exist, or
     the JSON does not parse. "error" is the first line.

Why this exists: a skill that claims to improve recall needs to show it.
The number "with skill: 0.87, without skill: 0.65" is not evidence -- it is
a claim. The sign test asks whether the per-defect improvements could have
arisen by chance. A paired test on a small sample will not resolve a small
effect, and the output says so out loud rather than letting a rounding
error read as a result.

The two verdict files must reference the same report and the same defect
list. They need not have identical false-claim counts: the without-skill
baseline often makes different mistakes than the with-skill run, and the
delta in false claims is itself a finding.

This is the tier-3 step in NVIDIA's SkillEvaluator three-tier model: tier 1
is structural lint, tier 2 is semantic deduplication, tier 3 is behavioural
measurement. This skill ships lint_skill.py (tier 1), dedup.py (tier 2),
and lift.py (tier 3).
"""
import argparse
import json
import math
import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SCORE = {"yes": 1.0, "partial": 0.5, "no": 0.0}


def _die(msg: str) -> None:
    print(f"error  {msg}")
    sys.exit(2)


def _load_json(path: str, label: str):
    if not os.path.exists(path):
        _die(f"{label} does not exist: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError) as e:
        _die(f"{label} is not parseable json: {e}")


def _load_defects(path: str):
    d = _load_json(path, "defects file")
    if not isinstance(d, dict):
        _die("defects file must be a json object")
    defects = d.get("defects")
    if not isinstance(defects, list) or not defects:
        _die("defects file must have a non-empty `defects` list")
    for i, x in enumerate(defects):
        if not isinstance(x, dict) or not x.get("id"):
            _die(f"defects[{i}] needs an `id`")
    return defects


def _load_verdicts(path: str, defects, label: str):
    v = _load_json(path, f"{label} verdicts")
    if not isinstance(v, dict):
        _die(f"{label} verdicts must be a json object")
    got = v.get("verdicts")
    if not isinstance(got, dict):
        _die(f"{label} verdicts must have a `verdicts` object")
    want = {x["id"] for x in defects}
    have = set(got)
    missing = sorted(want - have)
    extra = sorted(have - want)
    bad = [k for k in want & have if got[k] not in SCORE]
    msgs = []
    if missing:
        msgs.append(f"{len(missing)} defect(s) never judged in {label}: "
                    f"{', '.join(str(m) for m in missing)}")
    if extra:
        msgs.append(f"verdict for unknown defect(s) in {label}: "
                    f"{', '.join(str(e) for e in extra)}")
    if bad:
        msgs.append(f"verdict outside {{yes, partial, no}} in {label}: "
                    f"{', '.join(str(b) for b in bad)}")
    if msgs:
        _die("; ".join(msgs))
    fc = v.get("false_claims") or []
    if not isinstance(fc, list):
        _die(f"{label} verdicts: `false_claims` must be a list")
    return got, fc


def _tally(verdicts: dict, defects: list):
    t = {"yes": 0, "partial": 0, "no": 0}
    for x in defects:
        t[verdicts[x["id"]]] += 1
    n = len(defects)
    return t, (t["yes"] + 0.5 * t["partial"]) / max(1, n)


def _sign_p(b: int, c: int) -> float:
    """Exact two-sided sign test on discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure the lift of a skill over a baseline")
    parser.add_argument("--defects", required=True,
                        help="defects json file")
    parser.add_argument("--with-skill", required=True,
                        help="verdict json from a report produced with the skill")
    parser.add_argument("--without-skill", required=True,
                        help="verdict json from a report produced without the skill")
    args = parser.parse_args()

    defects = _load_defects(args.defects)
    w_verdicts, w_fc = _load_verdicts(args.with_skill, defects, "with-skill")
    b_verdicts, b_fc = _load_verdicts(args.without_skill, defects, "without-skill")

    tw, recall_w = _tally(w_verdicts, defects)
    tb, recall_b = _tally(b_verdicts, defects)

    ids = [x["id"] for x in defects]
    up = [i for i in ids if SCORE[b_verdicts[i]] < SCORE[w_verdicts[i]]]
    dn = [i for i in ids if SCORE[b_verdicts[i]] > SCORE[w_verdicts[i]]]
    same = [i for i in ids if SCORE[b_verdicts[i]] == SCORE[w_verdicts[i]]]

    p = _sign_p(len(up), len(dn))
    delta_recall = recall_w - recall_b
    delta_fc = len(w_fc) - len(b_fc)

    print(f"defects    : {len(ids)}")
    print(f"with-skill : {os.path.basename(args.with_skill)}")
    print(f"without    : {os.path.basename(args.without_skill)}")
    print()
    print(f"with-skill  : {tw['yes']}y {tw['partial']}p {tw['no']}n  "
          f"recall {recall_w:.3f}  false_claims {len(w_fc)}")
    print(f"without     : {tb['yes']}y {tb['partial']}p {tb['no']}n  "
          f"recall {recall_b:.3f}  false_claims {len(b_fc)}")
    print()
    print(f"delta recall    : {delta_recall:+.3f}")
    print(f"delta false_claims : {delta_fc:+d}")
    print()
    print(f"with-skill better on {len(up)}, worse on {len(dn)}, "
          f"unchanged on {len(same)}")
    print(f"sign test (exact, two-sided): b={len(up)} c={len(dn)}  "
          f"p = {p:.4f}")

    if p > 0.05:
        print()
        print("  -> not distinguishable from noise at this sample size")
        if up:
            print(f"with-skill improves: {' '.join(str(i) for i in up)}")
        if dn:
            print(f"with-skill regresses: {' '.join(str(i) for i in dn)}")
        print()
        print("A paired test on a small sample cannot resolve a small effect.")
        print("Treat a recall difference under roughly 0.30 as unmeasured,")
        print("not as a result.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
