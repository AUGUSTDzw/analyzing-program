#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dry-run: confirm every eval's files parse, triggers fire, and A13's
subprogram inventory is non-trivial (otherwise the assertion is vacuous)."""
import json, os, re, sys

EV = r"D:\Workspace\Skills\analyzing-programs\evals"
d = json.load(open(os.path.join(EV, "evals.json"), encoding="utf-8"))

print(f"{'id':<3} {'name':30} {'src':>6} {'meth':>5} {'form':>5} "
      f"{'readTbl':>8} {'FAE':>5} {'hard':>5} {'sem':>4} {'persist':>7}")
bad = 0
# The trigger set is deliberately NOT stored in evals.json. grade_v2.py derives
# every trigger from the source at grading time, so a hand-maintained copy could
# only ever drift. This script recomputes the same derivation and prints it for
# review; there is nothing to compare it against, so "mismatch" is impossible by
# construction. What it DOES assert: files exist, subprograms are non-trivial
# (otherwise A13 is vacuous), and the derived trigger set is not all-False.
DBT = ("MARA", "MARC", "MARD", "MAKT", "KNA1", "LFA1", "EKKO", "EKPO")
WEIGHTY = ("BRGEW", "NTGEW", "EINA", "EINUM", "MENGE", "WAERS", "NETPR",
           "MSTOCK", "MVBELN", "WRBTR", "BWHTB")

for e in d["evals"]:
    missing = [f for f in e["files"] if not os.path.exists(os.path.join(EV, f))]
    if missing:
        print(f"  MISSING FILES for eval {e['id']}: {missing}")
        bad += 1
        continue
    src = "".join(open(os.path.join(EV, f), encoding="utf-8").read() for f in e["files"])
    up = src.upper()
    meth = re.findall(r"^\s*METHOD\s+(\w+)\.", src, re.M | re.I)
    form = re.findall(r"^\s*FORM\s+(\w+)", src, re.M | re.I)
    fn = re.findall(r"^\s*FUNCTION\s+(\w+)", src, re.M | re.I)

    persist = bool(
        re.search(r"\bMODIFY\s+(" + "|".join(DBT) + r")\s+FROM", up)
        or re.search(r"\bINSERT\s+INTO\s+\w+", up)
        or re.search(r"\bUPDATE\s+\w+\s+SET\b", up)
        or re.search(r"\bDELETE\s+FROM\s+\w+", up)
        or re.search(r"BAPI_\w*(MAINTAIN|CREATE|CHANGE|DELETE)\w*", up))
    trg = {
        "read_table": "READ TABLE" in up,
        "for_all_entries": "FOR ALL ENTRIES" in up,
        "hardcode": bool(re.search(r"SPRAS\s*=\s*'", up)
                         or re.search(r"VALUE\s+'(EN|DE|ZH|JA|1|USD|EUR|CNY)'", up)
                         or re.search(r"\bWAERS\b[^.]{0,40}=\s*'", up)),
        "semantic": any(w in up for w in WEIGHTY),
        "persist": persist,
        "literal_msg": bool(re.search(r"MESSAGE\s+'", up)),
    }
    n_prog = len(meth) + len(form) + len(fn)
    if n_prog < 2:
        print(f"  FAIL eval {e['id']}: only {n_prog} subprograms — A13 would be vacuous")
        bad += 1
    if not any(trg.values()):
        print(f"  FAIL eval {e['id']}: no content assertion can fire")
        bad += 1
    fired = [k for k, v in trg.items() if v]
    print(f"{e['id']:<3} {e['name']:30} {len(src)//1024:>4}K "
          f"subs={n_prog:<3} fires={len(fired)}/6  [{', '.join(fired)}]")
    if meth:
        print(f"      methods: {meth}")
    if form:
        print(f"      forms  : {form}")
    if fn:
        print(f"      fms    : {fn}")

print("\n" + ("FIXTURES OK — triggers are derived at grading time, not stored"
             if not bad else f"{bad} PROBLEM(S)"))
sys.exit(1 if bad else 0)