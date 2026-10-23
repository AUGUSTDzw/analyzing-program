#!/usr/bin/env python3
"""Ship the skill as a release/: one directory, one zip, one SHA256SUMS line.

Why this exists
---------------
release/ last shipped 1.1.9 while the skill moved on to 1.1.29, so installing
from release/ gave a skill with no enc/esc gate, no schemas/skill-contract.json
and none of the meta tools. Nothing in the tree referenced release/, so the gap
sat for twenty releases. This closes the loop both ways: the default builds, and
--verify checks an existing release against SHA256SUMS and against the directory
sitting next to its zip, so a silently re-encoded artifact cannot pass unnoticed.

Where the version comes from
----------------------------
skill/<pkg>/SKILL.md frontmatter, not an argument. Reading the number from the
file that declares it means the directory name, the zip name and the SHA256SUMS
entry cannot disagree with what the skill says it is. An argument would have been
a fourth place for that number to live.

What is not shipped
-------------------
NOT_SHIPPED holds repository-only paths that must never reach a release. Every
suite under tests/ resolves fixtures by walking up from tests/ to a repository
root and reading sibling Test-source/ and analyzing-programs-workspace/, neither
of which ships; in an installed package they die on the first fixture, which
reads as a broken release rather than a harness that cannot run here. CRITICAL
lists the paths the gate and its scripts read, and the assertion below refuses to
let NOT_SHIPPED overlap them, so an over-eager exclusion cannot silently drop code.

verify() checks an already-packed release against NOT_SHIPPED as well as against
its zip and its digest. That check has to walk an unfiltered view: walk_clean
applies NOT_SHIPPED on the way out, so a verifier that walked the same filtered
tree would report a polluted release clean. That is exactly how 1.1.29 shipped
its whole harness and still passed --verify at 461 entries.

Usage
-----
    python package_release.py                ship the current version
    python package_release.py --verify NAME  check one release, write nothing
                                            NAME is a release dir name, e.g.
                                            analyzing-programs-1.1.29

Exit codes
----------
0  shipped, or verified clean
1  refused to overwrite, or a mismatch or a repository-only file was found
2  an input is missing or unreadable
"""
import hashlib
import io
import os
import re
import shutil
import sys
import zipfile

EXCLUDE_DIRS = ("__pycache__", ".pytest_cache", ".git")

# Repository-only paths that must never reach a release. Every suite under
# tests/ resolves fixtures by walking up from tests/ to a repository root and
# reading sibling Test-source/ and analyzing-programs-workspace/, neither of
# which ships. In an installed package they die on the first fixture, which
# reads as a broken release rather than a harness that cannot run here. The
# gate and its scripts are unaffected, so they stay.
NOT_SHIPPED = ("tests/",)

# The paths the gate and its scripts actually read. Dropping one of these ships
# a broken skill, so NOT_SHIPPED must not overlap them in either direction.
CRITICAL = ("schemas/", "scripts/", "references/", "evals/")

for _p in NOT_SHIPPED:
    for _c in CRITICAL:
        assert not (_p.startswith(_c) or _c.startswith(_p)), (
            "NOT_SHIPPED %r overlaps CRITICAL %r, which the gate reads"
            % (_p, _c))


def is_shipped(arcname):
    """False for a repository-only path that must not reach the package."""
    return not any(arcname.startswith(p) for p in NOT_SHIPPED)


def read_version(skill_md):
    """The version the skill declares about itself, or None."""
    with io.open(skill_md, encoding="utf-8") as fh:
        m = re.search(r"^version:\s*(\S+)\s*$", fh.read(), re.M)
    return m.group(1) if m else None


def walk_clean(root):
    """(arcname, fullpath) for every shippable file under root.

    Skips build noise (EXCLUDE_DIRS, *.pyc) and repository-only paths
    (NOT_SHIPPED). Directory entries are yielded first with a trailing slash,
    matching the layout the earlier releases were packed with.

    arcname is relative to root's parent, which is how the archives were laid
    out. NOT_SHIPPED is matched against the path relative to root itself --
    matching it against arcname would never fire, since every arcname is
    prefixed with the package directory name.
    """
    base = os.path.dirname(root.rstrip(os.sep))
    root_ = root.rstrip(os.sep)
    for cur, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        arc = os.path.relpath(cur, base).replace(os.sep, "/")
        rel = os.path.relpath(cur, root_).replace(os.sep, "/")
        prefix = "" if rel == "." else rel + "/"
        if is_shipped(prefix):
            yield arc + "/", None
        for f in sorted(files):
            if f.endswith(".pyc") or not is_shipped(prefix + f):
                continue
            yield arc + "/" + f, os.path.join(cur, f)


def walk_all(root):
    """(arcname, fullpath) for every file under root, minus build noise only.

    Deliberately ignores NOT_SHIPPED: verifying an already-packed release needs
    to see everything that is actually there, or a polluted release looks
    self-consistent and the check that should catch it cannot fire. walk_clean
    filters NOT_SHIPPED because it builds the archive.
    """
    base = os.path.dirname(root.rstrip(os.sep))
    for cur, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        arc = os.path.relpath(cur, base).replace(os.sep, "/")
        yield arc + "/", None
        for f in sorted(files):
            if f.endswith(".pyc"):
                continue
            yield arc + "/" + f, os.path.join(cur, f)


def not_shipped_in(root):
    """arcnames of NOT_SHIPPED files present under root, if any."""
    root_ = root.rstrip(os.sep)
    out = []
    for arc, full in walk_all(root):
        if full is None:
            continue
        rel = os.path.relpath(full, root_).replace(os.sep, "/")
        if not is_shipped(rel):
            out.append(arc)
    return sorted(out)


def sha256(path):
    with io.open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def verify(release_dir, dirname):
    """An existing release: does its zip match its dir and its recorded hash?"""
    rc = 0
    dest = os.path.join(release_dir, dirname)
    zippath = os.path.join(release_dir, dirname + ".zip")
    sums = os.path.join(release_dir, "SHA256SUMS")

    for label, path in (("directory", dest), ("zip", zippath)):
        if not os.path.exists(path):
            print("error  %s is missing: %s" % (label, path))
            return 2

    with zipfile.ZipFile(zippath) as zf:
        zset = set(zf.namelist())
    # walk_all, not walk_clean: filtering NOT_SHIPPED here would make a polluted
    # release look self-consistent, since the directory really does hold those
    # files. os.walk hands out basenames, so relativising one against the release
    # dir is the wrong answer -- distinct files sharing a name collapse onto a
    # single path and the comparison fails on every release.
    dset = set(a for a, _ in walk_all(dest))
    if dset == zset:
        print("  ok    zip contents match the directory (%d entries)" % len(zset))
    else:
        print("  FAIL  zip and directory disagree: %d only in zip, %d only in dir"
              % (len(zset - dset), len(dset - zset)))
        rc = 1

    # Zip entries and not_shipped_in both use arcnames relative to release/, so
    # strip the release-dir prefix before testing against NOT_SHIPPED.
    prefix = dirname + "/"
    zstray = sorted(n for n in zset
                    if n.startswith(prefix) and not is_shipped(n[len(prefix):]))
    stray = sorted(set(not_shipped_in(dest)) | set(zstray))
    if stray:
        print("  FAIL  %d repository-only file(s) shipped, excluded as %s: %s"
              % (len(stray), " ".join(NOT_SHIPPED), ", ".join(stray[:5])))
        rc = 1
    else:
        print("  ok    no repository-only path in the release")

    if os.path.exists(sums):
        with io.open(sums, encoding="utf-8") as fh:
            got = None
            for line in fh:
                if line.rstrip("\n").endswith(dirname + ".zip"):
                    got = line.split()[0]
                    break
        if got is None:
            print("  FAIL  %s.zip has no entry in SHA256SUMS" % dirname)
            rc = 1
        elif got == sha256(zippath):
            print("  ok    SHA256SUMS matches the zip")
        else:
            print("  FAIL  SHA256SUMS records %s, zip hashes to %s" % (got[:12],
                                                                       sha256(zippath)[:12]))
            rc = 1
    else:
        print("  FAIL  release/ has no SHA256SUMS")
        rc = 1
    return rc


def ship(pkg_dir, release_dir):
    skill_md = os.path.join(pkg_dir, "SKILL.md")
    if not os.path.isfile(skill_md):
        print("error  SKILL.md not found at %s" % skill_md)
        return 2
    version = read_version(skill_md)
    if not version:
        print("error  no `version:` in %s" % skill_md)
        return 2

    dirname = os.path.basename(pkg_dir) + "-" + version
    dest = os.path.join(release_dir, dirname)
    zippath = os.path.join(release_dir, dirname + ".zip")
    sums = os.path.join(release_dir, "SHA256SUMS")

    for label, path in (("directory", dest), ("zip", zippath)):
        if os.path.exists(path):
            print("error  %s already exists: %s" % (label, path))
            print("       release/ is append-only; bump the version first")
            return 1

    shutil.copytree(pkg_dir, dest,
                    ignore=shutil.ignore_patterns(*EXCLUDE_DIRS, "*.pyc"))
    # copytree's ignore matches basenames, which is the wrong unit for a path
    # prefix, so NOT_SHIPPED is pruned from the copied tree. walk_clean already
    # keeps the zip clean; the directory half ships alongside it and is what
    # verify() reads, so leaving these behind would fail its own check.
    for _p in NOT_SHIPPED:
        _victim = os.path.join(dest, _p.rstrip("/"))
        if os.path.isdir(_victim):
            shutil.rmtree(_victim)
        elif os.path.isfile(_victim):
            os.remove(_victim)

    with zipfile.ZipFile(zippath, "w", zipfile.ZIP_DEFLATED) as zf:
        for arc, full in walk_clean(dest):
            if full is None:
                zf.writestr(arc, "")
            else:
                zf.write(full, arc)

    digest = sha256(zippath)
    existing = io.open(sums, encoding="utf-8").read() if os.path.exists(sums) else ""
    if dirname + ".zip" in existing:
        print("error  %s.zip is already recorded in SHA256SUMS" % dirname)
        return 1
    with io.open(sums, "a", encoding="utf-8", newline="") as fh:
        fh.write("%s  %s.zip\n" % (digest, dirname))

    nfiles = sum(1 for _a, f in walk_clean(dest) if f)
    print("shipped %s" % dirname)
    print("  directory  %s  (%d files)" % (dest, nfiles))
    print("  zip        %s  (%d entries)" % (zippath,
                                             len(zipfile.ZipFile(zippath).namelist())))
    print("  sha256     %s" % digest)
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    here = os.path.dirname(os.path.abspath(__file__))
    skill_root = os.path.join(here, "skill")
    if not os.path.isdir(skill_root):
        print("error  no skill/ next to this script")
        return 2
    pkgs = [d for d in os.listdir(skill_root)
            if os.path.isdir(os.path.join(skill_root, d))]
    if len(pkgs) != 1:
        print("error  expected exactly one skill package, found %s" % pkgs)
        return 2

    release_dir = os.path.join(here, "release")
    if not os.path.isdir(release_dir):
        print("error  no release/ next to this script")
        return 2

    if "--verify" in sys.argv:
        i = sys.argv.index("--verify")
        if i + 1 >= len(sys.argv):
            print("error  --verify needs a release dir name")
            return 2
        return verify(release_dir, sys.argv[i + 1])

    return ship(os.path.join(skill_root, pkgs[0]), release_dir)


if __name__ == "__main__":
    sys.exit(main())
