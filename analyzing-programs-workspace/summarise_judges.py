import collections, io, json, os, sys

R = sys.argv[1]


def load(n):
    p = os.path.join(R, n)
    return json.load(io.open(p, encoding="utf-8")) if os.path.isfile(p) else None


rows = []
sev = {"yes": 1.0, "partial": 0.5, "no": 0.0}

for fn, label, src in [
    ("judge-fi-toolkit.json", "ZCL_FI_TOOLKIT (Keremkoseoglu, 1702L, CLASS)",
     "ABAP-Library"),
    ("judge-ave.json", "z_ave_standalone (ysichov, 29.5kL, CLASS-POOL)", "AVE"),
    ("judge-classic.json", None, None),
]:
    d = load(fn)
    if d is None:
        rows.append((label or fn, "MISSING", "", "", "", ""))
        continue
    if "reports" in d:
        for i, rep in enumerate(d["reports"], 1):
            v = collections.Counter(rep["verdicts"].values())
            t = len(rep["verdicts"])
            name = os.path.basename(rep["source"])[:34]
            rows.append((name, t, v["yes"], v["partial"], v["no"],
                         len(rep.get("false_claims", []))))
    else:
        v = collections.Counter(d["report"]["verdicts"].values())
        t = len(d["report"]["verdicts"])
        rows.append((label, t, v["yes"], v["partial"], v["no"],
                     len(d.get("false_claims", []))))

hdr = f"{'source / report':40s}{'defects':>9}{'yes':>5}{'part':>6}{'no':>4}{'weighted':>10}{'false':>7}"
print(hdr)
print("-" * len(hdr))
T = Y = P = N = F = 0
for name, t, y, p, n, f in rows:
    if t == "MISSING":
        print(f"{name:40s}{'MISSING':>9}")
        continue
    w = (y * 1.0 + p * 0.5) / t
    print(f"{name:40s}{t:9d}{y:5d}{p:6d}{n:4d}{w:10.3f}{f:7d}")
    T += t
    Y += y
    P += p
    N += n
    F += f
print("-" * len(hdr))
print(f"{'TOTAL':40s}{T:9d}{Y:5d}{P:6d}{N:4d}"
      f"{(Y+P*0.5)/max(1,T):10.3f}{F:7d}")
print(f"\nweighted recall {(Y+P*0.5)/max(1,T):.3f}   "
      f"false-claim rate {F} across {len(rows)} reports")
