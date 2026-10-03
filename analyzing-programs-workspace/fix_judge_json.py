import json, os, sys

JUDGE_DIR = sys.argv[1]
DEFECTS = json.load(open(sys.argv[2], encoding="utf-8"))["defects"]

CLOSERS = set(",}]:")


def repair(text):
    """Escape bare double quotes that appear *inside* JSON string values."""
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
            i += 1
            continue
        if ch == "\\":
            out.append(text[i : i + 2])
            i += 2
            continue
        if ch == '"':
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in CLOSERS:
                out.append('"')
                in_str = False
            else:
                out.append('\\"')
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


ok = True
for fn in sorted(os.listdir(JUDGE_DIR)):
    if not fn.endswith(".json"):
        continue
    p = os.path.join(JUDGE_DIR, fn)
    raw = open(p, encoding="utf-8").read()
    try:
        json.loads(raw)
        status = "OK  "
    except json.JSONDecodeError:
        try:
            data = json.loads(repair(raw))
        except json.JSONDecodeError as e:
            print("FAIL", fn, "unrepairable:", e)
            ok = False
            continue
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        status = "FIX "
    print(status, fn)
    data = json.load(open(p, encoding="utf-8"))
    ev, cfg = str(data["eval"]), data["config"]
    exp = {d["id"] for d in DEFECTS[ev]}
    if len(data["reports"]) != 2:
        print("     !! expected 2 reports, got", len(data["reports"]))
        ok = False
    for rep in data["reports"]:
        got = set(rep["verdicts"])
        if got != exp:
            print(f"     !! verdict id mismatch: missing={exp-got} extra={got-exp}")
            ok = False
        bad = {k: v for k, v in rep["verdicts"].items() if v not in ("yes", "partial", "no")}
        if bad:
            print("     !! invalid verdict values:", bad)
            ok = False
        if not os.path.isfile(rep["path"]):
            print("     !! report path does not exist:", rep["path"])
            ok = False
print("\nALL GOOD" if ok else "\nPROBLEMS FOUND")
sys.exit(0 if ok else 1)
