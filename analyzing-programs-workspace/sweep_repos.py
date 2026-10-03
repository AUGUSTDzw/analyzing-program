"""Sweep many repos via zipball: scan every ABAP file locally, keep
  (a) every file carrying a construct we lack, and
  (b) the largest few files per repo for shape diversity.

Scanning locally instead of sampling via the API is what makes this conclusive:
the earlier API probe looked at ~20 blobs per repo and could not distinguish
"absent" from "not sampled".
"""
import concurrent.futures as cf
import hashlib, io, json, os, re, sys, urllib.request, zipfile

OUT = sys.argv[1]
TOPK = int(sys.argv[2]) if len(sys.argv) > 2 else 3
LIMIT_MB = float(sys.argv[3]) if len(sys.argv) > 3 else 40.0
HDRS = {"User-Agent": "abap-corpus-fetcher"}
SUFFIX = (".abap", ".asddls", ".asbdef")

repos = json.load(open(sys.argv[4], encoding="utf-8"))
WANT = [r for r in sys.argv[5].split(",")]

PROBES = {
    "BADI impl":        r"^\s*CLASS\s+\w+\s+IMPLEMENTATION\s*$",
    "CLASS-POOL":       r"CLASS-POOL",
    "FUNCTION":         r"^\s*FUNCTION\s+\w+\s*\.",
    "dyn SQL":          r"EXECUTE\s+IMMEDIATE|EXECUTE\s+STATEMENT",
    "obsolete COMPUTE": r"^\s*COMPUTE\s+\w+\s*=",
    "obsolete MOVE TO": r"^\s*MOVE\s+TO\s+\w+\s*=",
    "obsolete ADD TO":  r"^\s*ADD\s+TO\s+\w+\s*=",
    "obsolete SUBTRACT": r"^\s*SUBTRACT\s+FROM\s+\w+\s*=",
    "PBO/PAI":          r"^\s*MODULE\s+\w+\s+(?:OUTPUT|INPUT)",
    "UPDATE TASK":      r"UPDATE\s+TASK\s+\w+|PERFORM\s+\w+\s+ON\s+COMMIT",
    "job control":      r"JOB-SUBMIT|START-JOB|bp_job_create",
    "AUTHORITY-CHECK":  r"AUTHORITY-CHECK",
    "CL_HTTP_CLIENT":   r"\bCL_HTTP_CLIENT\b|\bIF_HTTP_CLIENT\b",
    "CLASS-EVENTS":     r"\bCLASS-EVENTS\b",
    "RAISE EVENT":      r"\bRAISE\s+EVENT\b",
    "ENQUEUE":          r"\bENQUEUE_\w+",
    "AMDP":             r"BY\s+DATABASE\s+(?:PROCEDURE|FUNCTION)",
    "view entity":      r"define\s+view\s+entity",
    "side effect":      r"\bside\s+effects?\b",
}

man = json.load(open(os.path.join(OUT, "MANIFEST.json"), encoding="utf-8"))
have = {m["local"] for m in man}
print(f"corpus before: {len(man)} files")


def dl(repo):
    for br in (repos.get(repo, {}).get("branch"), "main", "master"):
        if not br:
            continue
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(
                        f"https://codeload.github.com/{repo}/zip/refs/heads/{br}",
                        headers=HDRS), timeout=150) as r:
                blob = r.read()
        except Exception:
            continue
        if len(blob) > LIMIT_MB * 1e6:
            return {"repo": repo, "br": br, "skip": f"{len(blob)/1e6:.0f}MB"}
        try:
            return {"repo": repo, "br": br,
                    "z": zipfile.ZipFile(io.BytesIO(blob))}
        except Exception as e:
            return {"repo": repo, "br": br, "skip": str(e)[:40]}
    return {"repo": repo, "skip": "no branch"}


GAPS = ("BADI impl", "CLASS-POOL", "FUNCTION", "dyn SQL", "obsolete COMPUTE",
        "obsolete MOVE TO", "obsolete ADD TO", "obsolete SUBTRACT",
        "PBO/PAI", "UPDATE TASK", "job control")

added, found_map, notes = 0, {}, []
for res_repo in WANT:
    res = dl(res_repo)
    repo = res["repo"]
    if res.get("skip"):
        print(f"  SKIP {repo:44s} {res['skip']}")
        notes.append({"repo": repo, "skip": res["skip"]})
        continue
    z, br = res["z"], res["br"]
    items = []
    for name in z.namelist():
        if name.endswith("/") or not name.endswith(SUFFIX):
            continue
        try:
            data = z.read(name)
        except Exception:
            continue
        txt = data.decode("utf-8", "replace")
        hits = [k for k, p in PROBES.items() if re.search(p, txt, re.M | re.I)]
        items.append((len(data), name, data, hits))
    items.sort(key=lambda x: -x[0])
    print(f"  {repo:44s} {len(items):5d} blobs, "
          f"{sum(1 for i in items if i[3])} carry a target construct")
    repo_found = {}
    for i, (_, name, data, hits) in enumerate(items):
        for h in hits:
            repo_found.setdefault(h, name)
    for h in GAPS:
        if h in repo_found:
            found_map.setdefault(h, []).append(repo)
    keep_idx = {i for i, it in enumerate(items) if it[3] in GAPS}
    keep_idx |= set(range(min(TOPK, len(items))))
    for i in sorted(keep_idx):
        _, name, data, hits = items[i]
        base = name.split("/", 1)[1] if "/" in name else name
        local = repo.replace("/", "__") + "__" + base.replace("/", "__")
        if local in have:
            continue
        txt = data.decode("utf-8", "replace")
        open(os.path.join(OUT, local), "w", encoding="utf-8", newline="").write(txt)
        note = ("carries: " + ", ".join(sorted(hits))) if hits else "largest object (shape diversity)"
        man.append({"repo": repo, "ref": br, "path": name,
                    "url": f"https://github.com/{repo}/blob/{br}/{name}",
                    "license": repos.get(repo, {}).get("lic") or "see-repo",
                    "note": note, "local": local,
                    "lines": txt.count("\n") + 1, "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest()})
        have.add(local)
        added += 1
    json.dump(man, open(os.path.join(OUT, "MANIFEST.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

print(f"\n+{added} files, manifest: {len(man)}")
print("\nconstruct -> repos where found:")
for g in GAPS:
    print(f"   {g:18s} {len(found_map.get(g, [])):2d}  {', '.join(found_map.get(g, [])[:4])}")
json.dump({"found": found_map, "notes": notes},
          open(sys.argv[6], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
