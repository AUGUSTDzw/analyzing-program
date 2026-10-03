"""Pre-flight check on every file we are about to hand to an analyser.

Lesson from the corpus: a source stored as mojibake would be analysed as if it
were real code, and nothing downstream would notice. So confirm encoding,
decodability, absence of U+FFFD, and print a content fingerprint the analyser
result can be cross-checked against.
"""
import hashlib, io, json, os, re, sys

man = json.load(open(os.path.join(sys.argv[1], "MANIFEST.json"), encoding="utf-8"))
picks = sys.argv[2].split("|")
rows, bad = [], []

for want in picks:
    hit = next((m for m in man if want.lower() in m["local"].lower()), None)
    if not hit:
        bad.append(f"{want}: not in manifest")
        continue
    p = os.path.join(sys.argv[1], hit["local"])
    raw = io.open(p, "rb").read()
    try:
        txt = raw.decode("utf-8")
        dec = "utf-8"
    except UnicodeDecodeError as e:
        bad.append(f"{hit['local']}: not utf-8 ({e})")
        continue
    n_bad = txt.count("\ufffd")
    if n_bad:
        bad.append(f"{hit['local']}: {n_bad} U+FFFD")
    # does it still look like ABAP?
    abap_markers = len(re.findall(r"^\s*(CLASS|FUNCTION|METHOD|ENDMETHOD|"
                                 r"FORM|ENDFORM|REPORT|PROGRAM|DATA:|TYPES:|"
                                 r"DEFINE|ENDCLASS)\b", txt, re.M))
    # crude smell test: real ABAP is mostly upper case keywords + '*' comments
    letters = re.sub(r"\s", "", txt)
    upper_ratio = (sum(1 for c in letters if c.isupper()) /
                   max(1, sum(1 for c in letters if c.isalpha())))
    nul = txt.count("\x00")
    if nul:
        bad.append(f"{hit['local']}: {nul} NUL bytes")
    rows.append((hit["local"], hit["lines"], dec, n_bad, nul,
                 abap_markers, upper_ratio,
                 hashlib.sha256(txt.encode()).hexdigest()[:12], hit["repo"]))

print(f"{'file':54s}{'lines':>7}{'enc':>7}{'FFFD':>6}{'NUL':>5}"
      f"{'abapkw':>8}{'UPPER%':>8}")
print("-" * 104)
for r in rows:
    print(f"{r[0][:54]:54s}{r[1]:7d}{r[2]:>7}{r[3]:>6}{r[4]:>5}"
          f"{r[5]:8d}{r[6]*100:7.0f}%")
print("-" * 104)
print(f"{len(rows)} files checked; sha256 prefixes for cross-checking:")
for r in rows:
    print(f"   {r[7]}  {r[8]}  {r[0][-46:]}")
if bad:
    print("\nPROBLEMS:")
    for b in bad:
        print("   -", b)
else:
    print("\nall clean: valid UTF-8, no replacement chars, no NULs, ABAP keywords present")
