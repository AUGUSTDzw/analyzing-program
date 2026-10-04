import io
import json
import os
import statistics
import sys

R = sys.argv[1]
# three independent judgements of the SAME report against the SAME defect list
files = [("judge-v1two2.json", "orig"), ("judge-v1two2-a.json", "re-a"),
         ("judge-v1two2-b.json", "re-b")]
print(f"{'judgement':10}{'yes':>5}{'part':>6}{'no':>4}{'weighted':>11}{'strict':>9}{'false':>7}")
print("-" * 52)
ws, ss, fcs = [], [], []
per = {}
for f, tag in files:
    p = os.path.join(R, f)
    if not os.path.exists(p):
        print(f"{tag:10}  MISSING")
        continue
    d = json.load(io.open(p, encoding="utf-8"))
    c = {"yes": 0, "partial": 0, "no": 0}
    for x in d["verdicts"].values():
        c[x] += 1
    w = (c["yes"] + 0.5 * c["partial"]) / len(d["verdicts"])
    fc = len(d.get("false_claims") or [])
    ws.append(w)
    ss.append(c["yes"] / len(d["verdicts"]))
    fcs.append(fc)
    per[tag] = d["verdicts"]
    print(f"{tag:10}{c['yes']:>5}{c['partial']:>6}{c['no']:>4}{w:>11.3f}"
          f"{c['yes']/len(d['verdicts']):>9.3f}{fc:>7}")
print("-" * 52)
print(f"{'mean':10}{'':>5}{'':>6}{'':>4}{statistics.mean(ws):>11.3f}"
      f"{statistics.mean(ss):>9.3f}{statistics.mean(fcs):>7.1f}")
print(f"{'range':10}{'':>5}{'':>6}{'':>4}{max(ws)-min(ws):>11.3f}"
      f"{max(ss)-min(ss):>9.3f}")
print()
if len(per) >= 2:
    tags = list(per)
    ids = sorted(next(iter(per.values())).keys(), key=lambda x: int(x[1:]))
    print("per-defect agreement across judgements:")
    print("-" * 52)
    unstable = 0
    for i in ids:
        vals = [per[t][i] for t in tags]
        if len(set(vals)) == 1:
            mark = "stable  "
        else:
            mark = "UNSTABLE"
            unstable += 1
        print(f"  {mark} {i:4} {' / '.join(f'{v:<7}' for v in vals)}")
    print("-" * 52)
    print(f"{unstable} of {len(ids)} defects did not get the same verdict every time")
    print(f"agreement {len(ids)-unstable}/{len(ids)} = "
          f"{(len(ids)-unstable)/len(ids)*100:.0f}%")