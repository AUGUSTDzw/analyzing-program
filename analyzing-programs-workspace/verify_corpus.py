"""Verify the fetched corpus against MANIFEST.json.

Provenance is the whole point of pulling real code, so the sha256 of every file
must match what was recorded at fetch time. A silent content change would
invalidate every report written against that file.
"""
import hashlib, io, json, os, sys

OUT = sys.argv[1]
man = json.load(open(os.path.join(OUT, "MANIFEST.json"), encoding="utf-8"))

bad, missing, mojibake = [], [], []
for m in man:
    p = os.path.join(OUT, m["local"])
    if not os.path.isfile(p):
        missing.append(m["local"])
        continue
    data = io.open(p, "rb").read()
    got = hashlib.sha256(data).hexdigest()
    if got != m["sha256"]:
        bad.append((m["local"], m["sha256"][:12], got[:12]))
    try:
        txt = data.decode("utf-8")
    except UnicodeDecodeError:
        txt = ""
        mojibake.append((m["local"], "not valid utf-8"))
    # U+FFFD is what a wrong decode leaves behind. It is itself valid UTF-8, so
    # "does it decode" cannot see it -- the replacement character can. One such
    # file (a UTF-16 source) was stored as mojibake before this check existed.
    if "\ufffd" in txt:
        mojibake.append((m["local"], f"{txt.count(chr(0xfffd))} U+FFFD"))
    n = txt.count("\n") + 1
    if n != m["lines"]:
        bad.append((m["local"], f"{m['lines']} lines", f"{n} lines"))

on_disk = {f for f in os.listdir(OUT)
           if f.endswith((".abap", ".asddls", ".asbdef", ".xml"))
           and f != "MANIFEST.json"}
listed = {m["local"] for m in man}
unlisted = sorted(on_disk - listed)

print(f"manifest: {len(man)} files, {sum(m['lines'] for m in man)} lines")
print(f"on disk : {len(on_disk)} ABAP/DDIC files")
if missing:
    print(f"\nMISSING ({len(missing)}):")
    for m in missing:
        print("   -", m)
if bad:
    print(f"\nMISMATCH ({len(bad)}):")
    for f, want, got in bad:
        print(f"   - {f}\n       manifest: {want}\n       actual  : {got}")
if unlisted:
    print(f"\nON DISK BUT NOT IN MANIFEST ({len(unlisted)}):")
    for u in unlisted:
        print("   -", u)
if mojibake:
    print(f"\nMOJIBAKE / WRONG ENCODING ({len(mojibake)}):")
    for f, why in mojibake:
        print(f"   - {f}\n       {why}")

ok = not (missing or bad or unlisted or mojibake)
print("\n" + ("CORPUS VERIFIED" if ok else "CORPUS PROBLEMS FOUND"))
sys.exit(0 if ok else 1)
