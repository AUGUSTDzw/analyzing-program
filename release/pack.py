"""Package one release from the commit that produced it.

Reads the tree out of git rather than the worktree, so the artifact is
reproducible from history alone. Layout is asserted against the previous release
so a silent structural change cannot ship. Run from the repository root:

    python release/pack.py 1.1.0 <commit>

The version argument is the release number; the contract's release.ships_with
and the directory name come from it.
"""
import hashlib, os, shutil, subprocess, sys, zipfile

VER = sys.argv[1]
REV = sys.argv[2]
SRC = "skill/analyzing-programs"
PREFIX = "analyzing-programs-" + VER
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

names = subprocess.run(["git", "ls-tree", "-r", "--name-only", REV, "--", SRC],
                       capture_output=True, text=True, check=True).stdout.split()
blobs = {}
for n in names:
    rel = n[len(SRC) + 1:].replace("\\", "/")
    blobs[rel] = subprocess.run(["git", "show", "%s:%s" % (REV, n)],
                                capture_output=True, check=True).stdout

dirs = set()
for rel in blobs:
    parts = rel.split("/")
    for i in range(1, len(parts)):
        dirs.add("/".join(parts[:i]))

order = []
def walk(prefix):
    if prefix in dirs:
        order.append((prefix + "/", None))
    lead = prefix + "/" if prefix else ""
    here = set()
    for p in list(dirs) + list(blobs):
        if p.startswith(lead) and p != prefix:
            here.add(p[len(lead):].split("/")[0])
    for child in sorted(here):
        full = prefix + "/" + child if prefix else child
        order.append((full, full)) if full in blobs else walk(full)
walk("")
order.insert(0, ("", None))
assert sorted(r for _, r in order if r) == sorted(blobs)

zp = "release/%s.zip" % PREFIX
if os.path.exists(zp):
    os.remove(zp)
with zipfile.ZipFile(zp, "w") as z:
    for entry, rel in order:
        zi = zipfile.ZipInfo(PREFIX + "/" + entry)
        zi.create_system = 0
        if rel is None:
            zi.compress_type = zipfile.ZIP_STORED
            zi.external_attr = 0o40755 << 16 | 0x10
            z.writestr(zi, b"")
        else:
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, blobs[rel])

dst = "release/" + PREFIX
shutil.rmtree(dst, ignore_errors=True)
with zipfile.ZipFile(zp) as z:
    z.extractall("release")

z = zipfile.ZipFile(zp)
files = sorted(n[len(PREFIX) + 1:] for n in z.namelist() if not n.endswith("/"))
assert files == sorted(blobs), "zip contents differ from the commit"
for rel in files:
    assert z.read(PREFIX + "/" + rel) == blobs[rel], rel
    assert open(os.path.join(dst, rel), "rb").read() == blobs[rel], rel

data = open(zp, "rb").read()
h = hashlib.sha256(data).hexdigest()
print("%s.zip  %d files  %d B" % (PREFIX, len(files), len(data)))
print(h)
