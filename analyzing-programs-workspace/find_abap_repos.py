"""Broadly enumerate ABAP repositories on GitHub, paginated.

Earlier pass used 6 queries x 15 results = ~65 candidates, all from one page.
This widens the query set, paginates, and de-duplicates, because the corpus
ceiling (4 projects) was itself a finding worth re-testing at larger scale.
"""
import json, sys, time, urllib.parse, urllib.request

HDRS = {"User-Agent": "abap-corpus-fetcher", "Accept": "application/vnd.github+json"}

QUERIES = [
    "abap",
    "abap language:abap",
    "sap abap",
    "abap report program",
    "abap class pool",
    "abap function module",
    "abap badi",
    "abap enhancement spot",
    "abap user exit",
    "abap amdp",
    "abap rap business object",
    "abap cds view entity",
    "abap dialog screen pbo pai",
    "abap background job",
    "abap alv grid",
    "abap odata service",
    "abap steampunk",
    "abap open source",
    "abap clean code",
    "abap migration",
    "abap to abap cloud",
    "abap unit test",
]

seen = {}
for q in QUERIES:
    for page in (1, 2):
        url = ("https://api.github.com/search/repositories?q="
               + urllib.parse.quote(q)
               + f"&sort=stars&order=desc&per_page=50&page={page}")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HDRS),
                                        timeout=45) as r:
                d = json.load(r)
        except Exception as e:
            print(f"  ! {q} p{page}: {e}")
            time.sleep(4)
            continue
        items = d.get("items", [])
        if not items:
            break
        for it in items:
            if it.get("language") != "ABAP" and "abap" not in (
                    (it.get("name") or "").lower()):
                continue
            seen[it["full_name"]] = {
                "stars": it["stargazers_count"],
                "lic": (it.get("license") or {}).get("spdx_id"),
                "desc": (it.get("description") or "")[:88],
                "pushed": (it.get("pushed_at") or "")[:10],
                "branch": it.get("default_branch") or "main",
                "size_kb": it.get("size", 0),
            }
        time.sleep(2.2)

rows = sorted(seen.items(), key=lambda x: -x[1]["stars"])
json.dump({k: v for k, v in rows}, open(sys.argv[1], "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(f"{len(rows)} distinct ABAP repos (>=20 stars shown below)\n")
print(f"{'repo':46s}{'stars':>7}{'KB':>8}  {'license':11s} branch")
print("-" * 92)
n = 0
for name, m in rows:
    if m["stars"] < 20:
        continue
    n += 1
    print(f"{name[:46]:46s}{m['stars']:7d}{m['size_kb']:8d}  "
          f"{str(m['lic'])[:10]:11s} {m['branch']}")
print(f"\n{n} repos with >=20 stars written to {sys.argv[1]}")
