"""Diff _claims() between the committed gate and the modified one, per report.

Prints every line that changed status, so a new flag can be judged one by one
instead of by total count.
"""
import importlib.util
import io
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
OLD = pathlib.Path(r"C:\Users\DzwU\AppData\Local\Temp\ap-verify\qc_old.py")
NEW = ROOT / "skill" / "analyzing-programs" / "scripts" / "report_qc.py"


def load(p, name):
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


old, new = load(OLD, "qc_old"), load(NEW, "qc_new")


def blocks(text):
    out = []
    for st, bs, be, _en, lang in new.fence_spans(text):
        if lang and lang.lower() == new.QUOTE_LANG.lower():
            out.append(text[bs:be])
    return out


tot_new = tot_drop = 0
for rep in sorted((ROOT / "Test-result").rglob("*.skill.md")):
    text = io.open(rep, encoding="utf-8", errors="replace").read()
    for body in blocks(text):
        o = set(l for _i, l in old._claims(body))
        n = set(l for _i, l in new._claims(body))
        for l in sorted(n - o):
            tot_new += 1
            print("  + NEW %s" % rep.name[:44].ljust(46), l.strip()[:72])
        for l in sorted(o - n):
            tot_drop += 1
            print("  - DROPPED %s" % rep.name[:38].ljust(40), l.strip()[:72])
print()
print("newly probed  : %d" % tot_new)
print("dropped       : %d" % tot_drop)
