#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Score a report against a frozen defect reference.

report_qc.py answers whether a report has the right shape. It cannot answer
whether the analysis is right, and that is the part a reader depends on: the
v1 report passed every structural check and still made six false claims. Recall
is worse -- nothing in a report says which defects it failed to find, because a
missed defect leaves no trace.

Both need a reference: someone reads the source, writes down what is wrong with
it, and that list stops changing. Then a judge decides, per defect, whether the
report identified it. That makes recall measurable and stops the metric from
drifting when the report is rewritten.

Three commands:

    evaluate.py tasks   --defects D.json [--source S]
        Print the numbered questions a judge must answer, with the anchors and
        the exact verdict vocabulary. This is the step a model performs; nothing
        here can do it for you.

    evaluate.py score  --defects D.json --verdicts V.json [--report R]
        Validate hard, then aggregate: tally, weighted recall, false claims.

    evaluate.py compare --defects D.json --a A.json --b B.json
        Paired comparison of two reports on one reference, with an exact
        two-sided sign test. Comparing unpaired totals on 20 defects is how this
        project talked itself into a version that regressed.

The validation is the point of shipping this. Three earlier merge scripts failed
silently -- no exception, just an empty or clobbered aggregate -- so a partial
judgement must not be able to pass as a complete one. A verdict file that does
not name every defect exactly once is rejected, not scored.

Verdict file shape:

    {"report": "path/to/report.md",
     "verdicts": {"D1": "yes", "D2": "partial", "D3": "no"},
     "false_claims": [{"claim": "...", "why_wrong": "..."}]}
"""
import io
import json
import math
import os
import re
import sys

SCORE = {"yes": 1.0, "partial": 0.5, "no": 0.0}


def die(msgs, title):
    print(f"REJECTED  {title}")
    for m in msgs:
        print("  -", m)
    sys.exit(2)


def load_defects(path):
    if not os.path.exists(path):
        die([f"no such defect reference: {path}"], "defect reference")
    try:
        d = json.load(io.open(path, encoding="utf-8"))
    except (ValueError, OSError) as e:
        # A traceback exits 1, the code a real recall shortfall gets, so a
        # broken reference read as a bad report.
        die([f"not parseable json: {e}"], path)
    defs = d.get("defects")
    if not isinstance(defs, list) or not defs:
        die(["`defects` is missing or empty"], path)
    ids = [x.get("id") for x in defs]
    bad = [i for i in ids if not i]
    if bad:
        die([f"{len(bad)} defect(s) have no id"], path)
    nonstr = [i for i in ids if not isinstance(i, str)]
    if nonstr:
        die([f"{len(nonstr)} defect(s) have non-string ids: "
             + ", ".join(repr(x) for x in nonstr[:3])], path)
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        die([f"duplicate id(s): {', '.join(map(str, dup))}"], path)
    for x in defs:
        if not x.get("question"):
            die([f"{x['id']} has no question; a judge cannot answer it"], path)
    return d


def cmd_tasks(a):
    d = load_defects(a.defects)
    src = a.source or d.get("source") or "(source not recorded)"
    print(f"source: {src}")
    print(f"defects: {len(d['defects'])}   report to judge: {a.report or '(not given)'}")
    print()
    print("Read the report once. Then, for each defect below, decide whether the")
    print("report identifies THAT defect. Judge the report, not the source: a")
    print("defect the report is silent about counts as `no`, however true it is.")
    print()
    print("  yes      the report states this defect, in substance")
    print("  partial  the report touches it but misstates or understates it")
    print("  no       the report does not identify it")
    print()
    print("Verdicts must name every id exactly once. A partial file is rejected.")
    print()
    for x in d["defects"]:
        print(f"[{x['id']}]  ({x.get('area', '-')})")
        print(f"  anchor : {_anchor(x)}")
        print(f"  ask    : {x['question']}")
        print()
    print("Write the result as:")
    print(json.dumps({"report": a.report or "<path>",
                      "verdicts": {x["id"]: "yes|partial|no" for x in d["defects"][:3]},
                      "false_claims": []}, ensure_ascii=False, indent=1))


def _anchor(x):
    if x.get("anchors"):
        return " / ".join(x["anchors"])
    return x.get("anchor", "-")


def load_verdicts(path, defects, title, need_evidence=True):
    if not os.path.exists(path):
        die([f"no such verdict file: {path}"], title)
    try:
        v = json.load(io.open(path, encoding="utf-8"))
    except (ValueError, OSError) as e:
        die([f"not parseable json: {e}"], path)
    if not isinstance(v, dict):
        die(["the verdict file must be a json object"], path)
    rep = v.get("report")
    got = v.get("verdicts")
    if not isinstance(got, dict):
        die(["`verdicts` missing or not an object"], title)
    want = {x["id"] for x in defects}
    have = set(got)
    missing = sorted(want - have)
    extra = sorted(have - want)
    wrong = sorted(f"{k}={got[k]!r}" for k in have & want if got[k] not in SCORE)
    msgs = []
    if rep is not None and not isinstance(rep, str):
        # os.path.exists on a list raises TypeError. That is a crash, not a
        # rejection, and the rejection is the whole point of this file.
        msgs.append(f"`report` must be a path string, got "
                    f"{type(rep).__name__}")
        rep = None
    elif rep and "\x00" in rep:
        msgs.append(f"`report` path contains null bytes: {rep!r}")
        rep = None
    if missing:
        msgs.append(f"{len(missing)} defect(s) never judged: {', '.join(missing)}")
    if extra:
        msgs.append(f"verdict for unknown defect(s): {', '.join(map(str, extra))}")
    if wrong:
        msgs.append("verdict outside {yes, partial, no}: " + ", ".join(wrong))
    # A positive verdict must point at the report line that carries it. Borrowed
    # from archify, which never accepts a pass without an identified reviewer and
    # binds every receipt to the artifact it measured. Without this, "yes" is an
    # assertion with nothing to check, and the false matches are invisible: a
    # token probe here judged a defect present because `assigning` appeared,
    # when the line actually said LOOP AT ... ASSIGNING.
    ev = v.get("evidence")
    if ev is not None and not isinstance(ev, dict):
        msgs.append("`evidence` must be an object keyed by defect id")
        ev = {}
    rep_body = None
    if rep and os.path.exists(rep):
        try:
            rep_body = io.open(rep, encoding="utf-8").read().split("\n")
        except (OSError, UnicodeDecodeError) as e:
            msgs.append(f"`report` {rep} is not readable: {e}")
            rep_body = None
    elif need_evidence and any(v in ("yes", "partial") for v in (got or {}).values()):
        # Without the report, report_line and quote cannot be checked, so a
        # citation requirement would be accepted without being verified. It read
        # as a clean pass: verdicts citing lines that were made up still scored.
        why = f"`report` {rep} does not exist" if rep else "`report` is missing"
        msgs.append(why + ", so report_line and quote cannot be checked; pass "
                     "--legacy for files that predate citations")
    for k, verdict in (got or {}).items():
        if verdict not in ("yes", "partial"):
            continue
        e = (ev or {}).get(k)
        if not need_evidence:
            # Historical verdict files predate the citation requirement. Their
            # recall is comparable; their auditability is not, and --legacy says
            # so out loud rather than quietly treating them as equivalent.
            continue
        if rep_body is None:
            continue
        if not isinstance(e, dict) or not e.get("report_line"):
            msgs.append(f"{k} is `{verdict}` with no evidence: "
                        f"needs evidence.{k}.report_line")
            continue
        try:
            ln = int(e["report_line"])
        except (TypeError, ValueError):
            msgs.append(f"evidence.{k}.report_line is not a line number")
            continue
        if not (1 <= ln <= len(rep_body)):
            msgs.append(f"evidence.{k}.report_line {ln} is outside the "
                        f"report ({len(rep_body)} lines)")
            continue
        q = e.get("quote")
        if not q or not str(q).strip():
            # A line number alone is an assertion with nothing to check: it is
            # what makes a fabricated citation score clean. --legacy waives the
            # requirement for files that predate it, and says so.
            msgs.append(f"{k} is `{verdict}` but cites no quote: add "
                        f"evidence.{k}.quote, or pass --legacy for files that "
                        f"predate citations")
            continue
        norm = lambda t: re.sub(r"\s+", " ", t).strip().lower()
        if norm(str(q)) not in norm(rep_body[ln - 1]):
            msgs.append(f"evidence.{k}.quote does not appear on "
                        f"report line {ln}")
    fc = v.get("false_claims")
    if fc is not None and not isinstance(fc, list):
        # Some older judge files stored a count here. A count cannot be audited
        # and silently coercing it to [] would understate the false-claim rate,
        # which is the number this whole exercise exists to keep honest.
        msgs.append(f"`false_claims` is {type(fc).__name__}, expected a list of "
                    f"{{claim, why_wrong}}. A bare count cannot be checked; "
                    f"rebuild it from the claims themselves.")
        fc = []
    for i, c in enumerate(fc or []):
        if not isinstance(c, dict) or not c.get("claim") or not c.get("why_wrong"):
            msgs.append(f"false_claims[{i}] needs both `claim` and `why_wrong`")
    if msgs:
        die(msgs, title)
    return v


def tally(verdicts, defects):
    t = {"yes": 0, "partial": 0, "no": 0}
    for x in defects:
        t[verdicts[x["id"]]] += 1
    n = len(defects)
    return t, (t["yes"] + 0.5 * t["partial"]) / max(1, n)


def cmd_score(a):
    d = load_defects(a.defects)
    v = load_verdicts(a.verdicts, d["defects"], a.verdicts, not a.legacy)
    t, w = tally(v["verdicts"], d["defects"])
    fc = v.get("false_claims") or []
    rep = v.get("report")
    print(f"source   : {d.get('source', '-')}")
    print(f"report   : {rep or a.report or '-'}")
    if rep and not os.path.exists(rep):
        print(f"           WARNING  report path does not exist: {rep}")
    if a.legacy:
        # The flag is the whole story here: with it on, no verdict is bound to
        # anything in the report, and a scored file reads as auditable.
        print(f"           WARNING  --legacy: citations were not verified, so "
              f"every verdict is an uncheckable assertion")
    if a.report and rep and os.path.abspath(a.report) != os.path.abspath(rep):
        print(f"           WARNING  verdict file names a different report than --report")
    print(f"defects  : {len(d['defects'])}")
    print(f"verdicts : {t['yes']} yes, {t['partial']} partial, {t['no']} no")
    print(f"recall   : {w:.3f} weighted   ({t['yes']/max(1,len(d['defects'])):.3f} strict)")
    print(f"false    : {len(fc)} claim(s) contradicted by the source")
    print()
    miss = [x["id"] for x in d["defects"] if v["verdicts"][x["id"]] == "no"]
    part = [x["id"] for x in d["defects"] if v["verdicts"][x["id"]] == "partial"]
    if miss:
        print("not identified: " + " ".join(miss))
    if part:
        print("understated   : " + " ".join(part))
    if fc:
        print()
        for i, c in enumerate(fc, 1):
            print(f"false claim {i}: {c['claim'][:110]}")
            print(f"              {c['why_wrong'][:110]}")


def sign_p(b, c):
    """Exact two-sided sign test on the discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def cmd_compare(a):
    d = load_defects(a.defects)
    ids = [x["id"] for x in d["defects"]]
    A_full = load_verdicts(a.a, d["defects"], a.a, not a.legacy)
    B_full = load_verdicts(a.b, d["defects"], a.b, not a.legacy)
    # Both verdict files must reference the same report; comparing two different
    # reports against one defect list is a paired test that was never run.
    rep_a = A_full.get("report")
    rep_b = B_full.get("report")
    if rep_a and rep_b and os.path.basename(rep_a) != os.path.basename(rep_b):
        die([f"verdict files reference different reports: "
             f"{os.path.basename(rep_a)} vs {os.path.basename(rep_b)}"],
            "compare")
    A = A_full["verdicts"]
    B = B_full["verdicts"]
    ta, wa = tally(A, d["defects"])
    tb, wb = tally(B, d["defects"])
    up = [i for i in ids if SCORE[B[i]] > SCORE[A[i]]]
    dn = [i for i in ids if SCORE[B[i]] < SCORE[A[i]]]
    same = [i for i in ids if SCORE[B[i]] == SCORE[A[i]]]
    p = sign_p(len(up), len(dn))
    print(f"source  : {d.get('source', '-')}   defects: {len(ids)}")
    print(f"A {os.path.basename(a.a):34} {ta['yes']}y {ta['partial']}p {ta['no']}n  recall {wa:.3f}")
    print(f"B {os.path.basename(a.b):34} {tb['yes']}y {tb['partial']}p {tb['no']}n  recall {wb:.3f}")
    print(f"delta   : {wb - wa:+.3f}")
    print()
    print(f"B better on {len(up)}, worse on {len(dn)}, unchanged on {len(same)}")
    print(f"sign test (exact, two-sided): b={len(up)} c={len(dn)}  p = {p:.4f}")
    if p > 0.05:
        print("  -> not distinguishable from noise at this sample size")
    if up:
        print("B improves: " + " ".join(up))
    if dn:
        print("B regresses: " + " ".join(dn))
    print()
    print("A paired test on 20 defects cannot resolve a small effect. Treat a")
    print("difference under roughly 30 points as unmeasured, not as a result.")


def main(argv):
    ap = _ap(argv)
    a = ap.parse_args()
    if not a.cmd:
        print(__doc__)
        return 2
    {"tasks": cmd_tasks, "score": cmd_score, "compare": cmd_compare}[a.cmd](a)
    return 0


def _ap(argv):
    import argparse
    p = argparse.ArgumentParser(prog="evaluate.py", add_help=True)
    sub = p.add_subparsers(dest="cmd")
    t = sub.add_parser("tasks")
    t.add_argument("--defects", required=True)
    t.add_argument("--source")
    t.add_argument("--report")
    s = sub.add_parser("score")
    s.add_argument("--defects", required=True)
    s.add_argument("--verdicts", required=True)
    s.add_argument("--report")
    s.add_argument("--legacy", action="store_true",
                   help="waive the citation requirement; historical verdict files "
                        "predate it. Their recall is comparable, their auditability "
                        "is not.")
    c = sub.add_parser("compare")
    c.add_argument("--defects", required=True)
    c.add_argument("--a", required=True)
    c.add_argument("--b", required=True)
    c.add_argument("--legacy", action="store_true")
    return p


if __name__ == "__main__":
    sys.exit(main(sys.argv))
