"""The primary endpoint for iteration-9: the shipped gate, scored per report, paired.

    python gate_ab.py SKILL_SCRIPTS WORKSPACE [ARM_A] [ARM_B]

Why per-report DEFECT COUNT rather than pass/fail. Measured on iteration-8
(26 with_skill reports, shipped gate): 20 pass, 6 fail, 7 defect instances
(A8-cc 4, A8-pt 2, line-number 1), per-report counts 0 x20 / 1 x5 / 2 x1. That
is a 23% base rate. At 39 paired reports a move from 77% to 90% is about five net
flips, and 8 wins / 2 losses only reaches p=0.109 -- undetectable. Counting
defects turns the same evidence into "this report went from 2 defects to 0",
which is a clear directional win.

The ceiling that follows, and it is the reason the threshold is written where it
is: at a 23% base rate only about 9 of 39 reports carry any defect at all, so the
number of wins CANNOT exceed ~9. A criterion demanding 12 wins would be
arithmetically unreachable and would read as "the fix failed" when it means
"the threshold was above the ceiling".

Rules are read from report_qc, not reimplemented. report_qc.check(s) returns
(kind, line, detail) triples; importing it means this script cannot drift from
the gate the skill actually ships. Seven fixes in this project were a checker
disagreeing with the rule it enforced, every one of them a second copy of the
rule.
"""
import io
import json
import os
import re
import sys
from math import comb

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SCRIPTS, WS = sys.argv[1], sys.argv[2]
ARM_A = sys.argv[3] if len(sys.argv) > 3 else "with_skill_b8f84e8"
ARM_B = sys.argv[4] if len(sys.argv) > 4 else "with_skill_718f5988"

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, SCRIPTS)
import report_qc   # noqa: E402  (paths must be set first)
import truncation  # noqa: E402

# Truncated reports are excluded before anything is aggregated. A fragment is
# still a file and still looks like data; one 464-line AVE report was counted as
# a finished report once and produced a false "A8 defects fell from 50 to 15".
# Above this fraction the round is void rather than merely noisy.
VOID_IF_TRUNCATED_OVER = 0.40


def eval_sources():
    """{eval_id: source text}, so truncation can be judged against the real input."""
    p = os.path.join(REPO, "evals", "evals.json")
    out = {}
    if not os.path.isfile(p):
        return out
    for e in json.load(io.open(p, encoding="utf-8"))["evals"]:
        parts = []
        for f in e["files"]:
            fp = os.path.join(REPO, "evals", f)
            if os.path.isfile(fp):
                parts.append(io.open(fp, encoding="utf-8", errors="replace").read())
        out[e["id"]] = "\n".join(parts)
    return out


SRC = eval_sources()


def eval_id_of(name):
    m = EV_RE.match(name)
    return int(m.group(1).split("-")[1]) if m else None

# ---- the pre-registered criterion, fixed in iteration-9-plan.md section 2 ----
# PRIMARY passes when the new version carries strictly fewer defect instances AND
# the exact sign test over discordant (eval, run) pairs reaches p < 0.05.
ALPHA = 0.05
# Also asserted, so the report always states what this round could have detected
CEILING_NOTE = ("win count is bounded by the 23% base rate: only ~9 of 39 reports "
                "carry a defect, so a shortfall below the bar means the fix did "
                "not work -- not that there was too little data")

EV_RE = re.compile(r"^(eval-\d+-[a-z0-9-]+)")


def sign_p(w, l):
    """Exact two-sided sign test. Ties are excluded, not counted as half."""
    n = w + l
    if n == 0:
        return 1.0
    k = min(w, l)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def reports(arm):
    """{eval_id: {run_k: path}} for one arm.

    The arm directory sits INSIDE each eval directory, which is the layout
    grade_v2.py reads and iteration-1..8 all use:
        <ws>/eval-<id>-<name>/<arm>/run-<k>/outputs/report.md
    A flat <ws>/<arm>/... layout is accepted as a fallback so this script can also
    be pointed at a directory that was arranged by hand.
    """
    out = {}
    for ev in sorted(os.listdir(WS)):
        d = os.path.join(WS, ev, arm)
        if not os.path.isdir(d):
            continue
        for run in sorted(os.listdir(d)):
            p = os.path.join(d, run, "outputs", "report.md")
            if os.path.isfile(p):
                out.setdefault(ev, {})[run] = p
    if out:
        return out
    flat = os.path.join(WS, arm)
    if not os.path.isdir(flat):
        return None
    for ev in sorted(os.listdir(flat)):
        d = os.path.join(flat, ev)
        if not os.path.isdir(d):
            continue
        for run in sorted(os.listdir(d)):
            p = os.path.join(d, run, "outputs", "report.md")
            if os.path.isfile(p):
                out.setdefault(ev, {})[run] = p
    return out or None


def defects(path):
    """(count, {kind: n}, pass/fail) using the shipped gate's own rule set."""
    s = io.open(path, encoding="utf-8").read()
    bad = report_qc.check(s)
    kinds = {}
    for kind, _ln, _detail in bad:
        kinds[kind] = kinds.get(kind, 0) + 1
    return len(bad), kinds, (not bad)


def truncation_of(path, ev_name):
    """(truncated, reasons) judged against this eval's real source."""
    eid = eval_id_of(ev_name)
    src = SRC.get(eid) if eid is not None else None
    _t, why, _f = truncation.classify_file(path, src)
    return bool(why), why


def inventory(arm):
    found = reports(arm)
    if found is None:
        return None
    rows = []
    for ev, runs in sorted(found.items()):
        for run, p in sorted(runs.items()):
            n, kinds, ok = defects(p)
            trunc, why = truncation_of(p, ev)
            rows.append({"eval": ev, "run": run, "path": os.path.relpath(p, WS),
                         "defects": n, "kinds": kinds, "pass": ok,
                         "truncated": trunc, "truncation": why})
    return rows


def main():
    A, B = inventory(ARM_A), inventory(ARM_B)
    if A is None or B is None:
        for arm, got in ((ARM_A, A), (ARM_B, B)):
            if got is None:
                print(f"arm directory not found: {os.path.join(WS, arm)}")
        return 2

    print(f"{'':4}{ARM_A}  vs  {ARM_B}")
    print("-" * 78)
    for name, rows in ((ARM_A, A), (ARM_B, B)):
        n = len(rows)
        cut = [r for r in rows if r["truncated"]]
        tot = sum(r["defects"] for r in rows)
        npass = sum(1 for r in rows if r["pass"])
        kinds = {}
        for r in rows:
            for k, v in r["kinds"].items():
                kinds[k] = kinds.get(k, 0) + v
        dist = {}
        for r in rows:
            dist[r["defects"]] = dist.get(r["defects"], 0) + 1
        print(f"  {name:26} reports {n:3d}   PASS {npass:3d} ({npass/n*100:4.1f}%)"
              f"   defect instances {tot:3d}")
        print(f"  {'':26} per-report defect counts "
              f"{', '.join('%d x%d' % (k, dist[k]) for k in sorted(dist))}")
        print(f"  {'':26} by kind: "
              f"{', '.join('%s %d' % (k, v) for k, v in sorted(kinds.items())) or 'none'}")
        print(f"  {'':26} truncated: {len(cut)}")
        for r in cut:
            print(f"  {'':26}   EXCLUDED {r['eval']}/{r['run']}: {'; '.join(r['truncation'])}")

    # ---- truncation gate -----------------------------------------------------
    frac = (sum(1 for r in A + B if r["truncated"]) / max(1, len(A) + len(B)))
    print()
    if frac > VOID_IF_TRUNCATED_OVER:
        print(f"  ROUND VOID: {frac*100:.0f}% of reports are truncated, over the "
              f"{VOID_IF_TRUNCATED_OVER*100:.0f}% ceiling.")
        print("  Generation is not reliable enough to compare anything. This is the")
        print("  'generation is unreliable' finding, not a result about either skill.")
        return 1

    # ---- pair on (eval, run) -------------------------------------------------
    idx_a = {(r["eval"], r["run"]): r for r in A}
    idx_b = {(r["eval"], r["run"]): r for r in B}
    keys = sorted(set(idx_a) & set(idx_b))
    only_a = sorted(set(idx_a) - set(idx_b))
    only_b = sorted(set(idx_b) - set(idx_a))
    excluded = [k for k in keys
                if idx_a[k]["truncated"] or idx_b[k]["truncated"]]
    live = [k for k in keys if k not in excluded]
    wins = losses = ties = 0
    detail = []
    for k in live:
        da, db = idx_a[k]["defects"], idx_b[k]["defects"]
        if db < da:
            wins += 1
        elif db > da:
            losses += 1
        else:
            ties += 1
        if da != db:
            detail.append((k, da, db))

    unpaired = len(only_a) + len(only_b)
    print(f"  paired on (eval, run): {len(keys)} pairs, {len(live)} after "
          f"excluding truncated"
          + (f"   UNPAIRED: {unpaired} report(s) present in one arm only"
             if unpaired else ""))
    for k in excluded:
        print(f"    excluded (truncated): {k[0]}/{k[1]}")
    for k in only_a[:5]:
        print(f"    only in {ARM_A}: {k}")
    for k in only_b[:5]:
        print(f"    only in {ARM_B}: {k}")

    tot_a = sum(idx_a[k]["defects"] for k in live)
    tot_b = sum(idx_b[k]["defects"] for k in live)
    p = sign_p(wins, losses)

    print()
    print(f"  discordant pairs: {ARM_B} better on {wins}, worse on {losses}, "
          f"tied {ties}")
    for k, da, db in detail:
        print(f"    {k[0]:44} {k[1]:6} {da} -> {db}")

    print()
    print(f"  defect instances   {ARM_A} {tot_a}   {ARM_B} {tot_b}"
          f"   delta {tot_b - tot_a:+d}")
    print(f"  exact sign test    {wins} / {losses} / {ties} ties   p = {p:.4f}")
    print()
    print("-" * 78)
    if unpaired:
        print(f"  INCOMPLETE: {unpaired} report(s) unpaired. A pair count that does not")
        print("  cover both arms is a survivorship artefact, not a comparison.")
        return 1
    if tot_b >= tot_a:
        print("  PRE-REGISTERED CRITERION: NOT MET")
        print(f"  {ARM_B} does not carry strictly fewer defect instances "
              f"({tot_b} vs {tot_a}).")
        print("  Per iteration-9-plan.md: keep the skill as it is. Record the")
        print("  criterion as failed; do not re-run to get a different number.")
        return 1
    if p >= ALPHA:
        print(f"  PRE-REGISTERED CRITERION: NOT MET (p = {p:.4f} >= {ALPHA})")
        print("  Fewer defects overall, but not on enough pairs.")
        print(f"  {CEILING_NOTE}.")
        return 1
    print(f"  PRE-REGISTERED CRITERION: MET")
    print(f"  {ARM_B} carries {tot_a} -> {tot_b} defect instances and wins "
          f"{wins} of {wins + losses} discordant pairs, p = {p:.4f}.")
    print(f"  {CEILING_NOTE}.")

    out = os.path.join(WS, "gate_ab.json")
    json.dump({"arm_a": ARM_A, "arm_b": ARM_B, "alpha": ALPHA,
               "per_report": {"a": A, "b": B},
               "totals": {"a": tot_a, "b": tot_b},
               "sign_test": {"wins": wins, "losses": losses, "ties": ties,
                             "p_exact_two_sided": p, "n_pairs": len(keys)},
               "criterion_met": True},
              io.open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n  wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())