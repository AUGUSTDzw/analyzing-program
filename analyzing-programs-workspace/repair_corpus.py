"""Repair manifest path/url fields and normalise any file mangled by a wrong decode.

Two bugs in the zip fetcher, both silent:
  1. zipball entries carry a `<repo>-<branch>/` root. `local` stripped it but the
     recorded `path` did not, so every `url` had a doubled segment -- which is why
     re-fetching a file 404'd while its sha256 (taken from the correct raw bytes)
     still matched upstream.
  2. sources that are UTF-16 with a BOM were decoded as UTF-8 with
     errors="replace" and the mangled text written to disk. The hash was taken
     before that, so the stored hash described bytes the file never had.

Fix both, then re-verify everything.
"""
import hashlib, io, json, os, re, sys, time, urllib.request

OUT = sys.argv[1]
MAN = os.path.join(OUT, "MANIFEST.json")
HDRS = {"User-Agent": "abap-corpus-fetcher"}
man = json.load(open(MAN, encoding="utf-8"))

path_fixed = enc_fixed = 0
for m in man:
    # ---- 1. path / url -------------------------------------------------
    good = m["path"]
    for _ in range(3):
        root = good.split("/", 1)[0]
        if root.lower().startswith(m["repo"].split("/")[-1].lower()) or \
           root.lower().startswith(m["repo"].split("/")[0].lower()):
            good = good.split("/", 1)[1]
        else:
            break
    if good != m["path"]:
        m["path"] = good
        path_fixed += 1
    m["url"] = f"https://github.com/{m['repo']}/blob/{m['ref']}/{m['path']}"

    # ---- 2. encoding + content -----------------------------------------
    p = os.path.join(OUT, m["local"])
    raw = io.open(p, "rb").read()
    try:
        txt = raw.decode("utf-8")
        corrupt = "�" in txt
    except UnicodeDecodeError:
        txt, corrupt = None, True
    if not corrupt:
        m["sha256"] = hashlib.sha256(raw).hexdigest()
        m["bytes"] = len(raw)
        continue

    url = f"https://raw.githubusercontent.com/{m['repo']}/{m['ref']}/{m['path']}"
    up = None
    for a in range(5):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=HDRS), timeout=90) as r:
                up = r.read()
            break
        except Exception as e:
            print(f"     retry {a+1}: {e}")
            time.sleep(3 + a * 3)
    if up is None:
        print(f"   UNFIXED {m['local'][-46:]:46s} (kept corrupt copy)")
        continue
    # Upstream may itself be UTF-16 -- that is the whole reason we are here.
    # Sniff the BOM instead of assuming UTF-8.
    if up[:2] == b"\xff\xfe":
        up_txt, up_enc = up.decode("utf-16-le"), "utf-16-le"
    elif up[:2] == b"\xfe\xff":
        up_txt, up_enc = up.decode("utf-16-be"), "utf-16-be"
    else:
        try:
            up_txt, up_enc = up.decode("utf-8"), "utf-8"
        except UnicodeDecodeError as e:
            print(f"   UNFIXED {m['local'][-46:]:46s} undecodable: {e}")
            continue
    if "\x00" in up_txt[:200]:
        print(f"   UNFIXED {m['local'][-46:]:46s} NUL bytes after decode")
        continue
    if "�" in up_txt:
        print(f"   UNFIXED {m['local'][-46:]:46s} upstream has U+FFFD")
        continue
    good_txt = up_txt.replace("\r\n", "\n")
    io.open(p, "w", encoding="utf-8", newline="\n").write(good_txt)
    m["sha256"] = hashlib.sha256(good_txt.encode("utf-8")).hexdigest()
    m["bytes"] = len(good_txt.encode("utf-8"))
    m["lines"] = good_txt.count("\n") + 1
    m["upstream_was_utf16"] = (up_enc != "utf-8")
    m["upstream_encoding"] = up_enc
    m["note"] = (m["note"] + f" [re-fetched: upstream is {up_enc}, was stored mojibake]").strip()
    enc_fixed += 1
    print(f"   FIXED {m['local'][-46:]:46s} {up_enc} -> utf-8, {m['lines']} lines")

json.dump(man, open(MAN, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\npaths/urls repaired: {path_fixed}")
print(f"files re-normalised: {enc_fixed}")
print(f"manifest: {len(man)} files, {sum(x['lines'] for x in man)} lines")
