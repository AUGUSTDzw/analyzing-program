"""Pre-flight check on every file we are about to hand to an analyser.

Lesson from the corpus: a source stored as mojibake would be analysed as if it
were real code, and nothing downstream would notice. So confirm encoding,
decodability, absence of U+FFFD, and print a content fingerprint the analyser
result can be cross-checked against.

    python preflight.py CORPUSDIR "pick|pick|..."

A pick is resolved against the corpus MANIFEST.json first, then as a plain file
path (absolute, or relative to CORPUSDIR, or relative to the repo root). The
manifest-only behaviour is the original one; the path fallback was added because
the 16 synthetic eval fixtures are not in the manifest and had therefore never
been through this check. They are exactly the kind of hand-authored file that
gets written in the wrong encoding, which is how a UTF-16 source ended up stored
as mojibake in this corpus once already.
"""
import hashlib, io, json, os, re, sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

corpus = sys.argv[1]
picks = sys.argv[2].split("|")
rows, bad = [], []

man_path = os.path.join(corpus, "MANIFEST.json")
man = json.load(open(man_path, encoding="utf-8")) if os.path.isfile(man_path) else []
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve(want):
    """(abs path, origin) or (None, reason)."""
    hit = next((m for m in man if want.lower() in m["local"].lower()), None)
    if hit:
        return os.path.join(corpus, hit["local"]), "manifest"
    for cand in (want,
                 os.path.join(corpus, want),
                 os.path.join(REPO, want),
                 os.path.join(REPO, "evals", want)):
        if os.path.isfile(cand):
            return cand, "path"
    return None, "not found (not in manifest, not on disk)"


def rel(path):
    """Repo-relative when possible, absolute when not.

    os.path.relpath raises ValueError across drives on Windows, so a pick that
    points somewhere off this drive -- C:\\temp\\x.abap while the repo is on D:
    -- used to die with a traceback instead of a report.
    """
    try:
        return os.path.relpath(path, REPO).replace("\\", "/")
    except ValueError:
        return path.replace("\\", "/")


for want in picks:
    p, origin = resolve(want)
    if p is None:
        bad.append(f"{want}: {origin}")
        continue
    raw = io.open(p, "rb").read()
    try:
        txt = raw.decode("utf-8")
        dec = "utf-8"
    except UnicodeDecodeError as e:
        bad.append(f"{want}: not utf-8 ({e})")
        continue
    if raw[:3] == b"\xef\xbb\xbf":
        bad.append(f"{want}: starts with a UTF-8 BOM")
    n_bad = txt.count("�")
    if n_bad:
        bad.append(f"{want}: {n_bad} U+FFFD")
    # Does it still look like ABAP (or CDS DDL)?
    #
    # The keyword is matched WITHOUT its trailing colon and the \b is placed
    # after the word, not after the colon. The previous pattern was
    #     ^\s*(CLASS|...|DATA:|TYPES:|...)\b
    # and the two colon-bearing alternatives could never match anything, in any
    # file, on any run: after "DATA:" the next character is a space, and \b needs a
    # word/non-word transition, while ":" and " " are both non-word. So a file
    # made only of declarations -- a function-group TOP include, for instance --
    # read as having no ABAP in it at all. Ten alternatives, two of them dead,
    # and the check had been reporting confidently the whole time.
    abap_markers = len(re.findall(r"^\s*(?:CLASS|FUNCTION|METHOD|ENDMETHOD|FORM|"
                                 r"ENDFORM|REPORT|PROGRAM|DEFINE|ENDCLASS|"
                                 r"DATA|TYPES|CONTAINS|STATICS|INTERFACES)\b",
                                 txt, re.M))
    # CDS DDL sources are not ABAP and declare nothing above: they open with
    # `define view entity ...` or a catalog annotation. Treat them as first class
    # so a DDL fixture is never reported as an empty file.
    ddl_markers = len(re.findall(r"^\s*(?:define\s+(?:view|abstract\s+entity|"
                                 r"table\s+function|scalar\s+function|"
                                 r"projection|as\s+projection)|@AbapCatalog|"
                                 r"@EndUserText|@AccessControl)",
                                 txt, re.M | re.I))
    markers = abap_markers + ddl_markers
    # crude smell test: real ABAP is mostly upper case keywords + '*' comments
    letters = re.sub(r"\s", "", txt)
    upper_ratio = (sum(1 for c in letters if c.isupper()) /
                   max(1, sum(1 for c in letters if c.isalpha())))
    nul = txt.count("\x00")
    if nul:
        bad.append(f"{want}: {nul} NUL bytes")
    if markers == 0:
        kind = os.path.splitext(p)[1].lower()
        bad.append(f"{want}: no ABAP declaration keyword and no CDS DDL marker "
                   f"found (a .ddls/.asddls source should have `define view` or an "
                   f"@AbapCatalog annotation; got neither in {kind})")
    rows.append((rel(p), origin,
                 len(txt.splitlines()), dec, n_bad, nul, markers,
                 upper_ratio, hashlib.sha256(txt.encode()).hexdigest()[:12]))

print(f"{'file':50s}{'from':>9}{'lines':>7}{'enc':>7}{'FFFD':>6}{'NUL':>5}"
      f"{'kw':>6}{'UPPER%':>8}")
print("-" * 104)
for r in rows:
    print(f"{r[0][:50]:50s}{r[1]:>9}{r[2]:7d}{r[3]:>7}{r[4]:>6}{r[5]:>5}"
          f"{r[6]:6d}{r[7]*100:7.0f}%")
print("-" * 104)
print(f"{len(rows)} files checked; sha256 prefixes for cross-checking:")
for r in rows:
    print(f"   {r[8]}  {r[0][-44:]}")
if bad:
    print("\nPROBLEMS:")
    for b in bad:
        print("   -", b)
    sys.exit(1)
print("\nall clean: valid UTF-8, no BOM, no replacement chars, no NULs, "
      "ABAP keywords present")
