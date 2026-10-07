"""Sweep every archived report through the fidelity pass and record what it says.

Used to compare the gate before and after a change to _claims: the number of
fidelity notes across the real corpus must not go up.
"""
import io
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
QC = ROOT / "skill" / "analyzing-programs" / "scripts" / "report_qc.py"
REPORTS = ROOT / "Test-result"
SOURCES = ROOT / "Test-source"

SKIP = ("v1fid_", "v1gate_", "v1two_", "v1two2_", "v1two3_", "r1_", "r2_",
        "st1_", "st2_", "st_", "slice_", "slice2_", "v4_r1_", "v4_r2_", "v4_")


def stem(name):
    s = name.replace(".skill.md", "")
    for p in SKIP:
        if s.startswith(p):
            s = s[len(p):]
            break
    return s


def find_source(st):
    low = st.lower()
    best = None
    for f in SOURCES.rglob("*.abap"):
        p = str(f).lower()
        if low in p or any(tok.lower() in p for tok in st.split("__")[-1:]):
            if best is None or len(p) < len(best):
                best = p
    return pathlib.Path(best) if best else None


def main():
    global QC
    if len(sys.argv) > 1:
        QC = pathlib.Path(sys.argv[1])
    out = {}
    for rep in sorted(REPORTS.rglob("*.skill.md")):
        src = find_source(stem(rep.name))
        rec = {"lines": len(io.open(rep, encoding="utf-8", errors="replace").read().split("\n"))}
        if not src:
            rec["source"] = None
            out[str(rep.relative_to(ROOT))] = rec
            continue
        rec["source"] = str(src.relative_to(ROOT))
        r = subprocess.run(
            [sys.executable, str(QC), "--fidelity-only", str(rep), str(src)],
            capture_output=True, text=True, encoding="utf-8")
        rec["exit"] = r.returncode
        notes = [l.strip() for l in r.stdout.split("\n") if "do not occur in the source" in l]
        rec["fidelity_notes"] = notes
        m = []
        for n in notes:
            import re
            x = re.search(r"(\d+) quoted statement\(s\) of (\d+)", n)
            if x:
                m = (int(x.group(1)), int(x.group(2)))
                break
        rec["bad_of_total"] = list(m) if m else None
        out[str(rep.relative_to(ROOT))] = rec

    hit = {k: v for k, v in out.items() if v.get("fidelity_notes")}
    print("reports swept        : %d" % len(out))
    print("sources resolved     : %d" % sum(1 for v in out.values() if v.get("source")))
    print("reports with notes   : %d" % len(hit))
    tot = 0
    for k, v in out.items():
        if v.get("bad_of_total"):
            tot += v["bad_of_total"][0]
    print("total bad statements : %d" % tot)
    if hit:
        print()
        for k, v in hit.items():
            print("  %-70s %s" % (k, v["bad_of_total"]))
    json.dump(out, io.open(ROOT / "sweep_result.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
