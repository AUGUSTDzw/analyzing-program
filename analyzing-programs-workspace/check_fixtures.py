#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dry-run for the eval fixtures.

Asserts three things per eval, and deliberately reuses grade_v2.py's own
derivation rather than keeping a second copy of the regexes:

  1. every declared source file exists
  2. the A13 subprogram inventory is non-trivial — if it were empty, A13 would
     be vacuously true and a report could omit every subprogram and still pass
  3. at least one content assertion's trigger fires

An earlier version of this script carried its own copy of the trigger and
subprogram regexes. It silently disagreed with the grader: it did not know
about MODULE, so the new dialog fixture (eval 8) reported "0 subprograms" as
if that were the fixture's fault, when in fact the GRADER did not recognise
MODULE either. That divergence was only visible because grade_v2.py's
subprograms() gained MODULE at the same time. Duplicated logic in a scoring
harness is a correctness hazard, so this script now imports the real one.
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
EV = os.path.join(REPO, "evals")

# Import grade_v2 without executing its __main__ body: it does all its work at
# module scope, so read the two functions out of the source instead.
def _load_derivations():
    """Pull triggers() and subprograms() out of grade_v2.py and exec them."""
    src = open(os.path.join(HERE, "grade_v2.py"), encoding="utf-8").read()
    start = src.index("WEIGHTY = (")
    end = src.index("for e in EVALS:", start)
    ns = {"re": __import__("re"), "os": os, "json": json}
    exec(compile(src[start:end], "grade_v2.py:derivations", "exec"), ns)
    return ns["triggers"], ns["subprograms"]


triggers, subprograms = _load_derivations()

d = json.load(open(os.path.join(EV, "evals.json"), encoding="utf-8"))
print(f"{'id':<4} {'name':34} {'src':>5} {'subs':>5}  fires")
print("-" * 100)
bad = 0
for e in d["evals"]:
    missing = [f for f in e["files"] if not os.path.exists(os.path.join(EV, f))]
    if missing:
        print(f"  FAIL eval {e['id']}: missing files {missing}")
        bad += 1
        continue
    src = "".join(open(os.path.join(EV, f), encoding="utf-8").read()
                  for f in e["files"])
    trg = triggers(src)
    subs = subprograms(src)
    fired = [k for k, v in trg.items() if v]
    if len(subs) < 2:
        print(f"  FAIL eval {e['id']}: only {len(subs)} subprograms — "
              f"A13 would be vacuous. subs={subs}")
        bad += 1
    if not fired:
        print(f"  FAIL eval {e['id']}: no content assertion can fire")
        bad += 1
    print(f"{e['id']:<4} {e['name']:34} {len(src)//1024:>4}K {len(subs):>5}  "
          f"{len(fired)}/6 [{', '.join(fired)}]")
    if len(subs) <= 12:
        print(f"       subs: {subs}")

print("-" * 100)
if bad:
    print(f"{bad} PROBLEM(S)")
    sys.exit(1)
print("FIXTURES OK — triggers and subprogram inventory come from grade_v2.py itself")