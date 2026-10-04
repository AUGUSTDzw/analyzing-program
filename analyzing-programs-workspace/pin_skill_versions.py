"""Pin both skill versions under test and prove the pins still hold.

    python analyzing-programs-workspace/pin_skill_versions.py

Why this exists. Every quantitative result in this repository was produced
against one SKILL.md, and for two rounds nobody could say which one: iteration-7
and iteration-8 recorded no digest, so the number existed only in a git commit
message. iteration-9 compares two versions of the skill, which makes "which file
was actually loaded" a question the harness has to answer mechanically.

The baseline arm is deliberately not versioned. It is the same prompt with no
skill guidance, so it does not depend on the skill file at all; re-running it
would measure model drift, which is a different question.

Three things are asserted, because each has been wrong here before:
  - the extracted old version is BYTE-IDENTICAL to the git blob, not a
    PowerShell-rewritten copy (Out-File -Encoding utf8 adds a BOM and the digest
    moves; that is how a file gets analysed as if it were the real thing)
  - the old version references no script, because none of them existed when it
    was written -- if it did, the A/B would be comparing a prompt against a
    prompt-plus-tools and the comparison would be about the tools
  - the live tree still hashes to the pinned digest, so a round cannot silently
    measure a skill that has since been edited
"""
import hashlib
import io
import json
import os
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
VERSIONS = os.path.join(HERE, "skill-versions")
LIVE = os.path.join(REPO, "skill", "analyzing-programs", "SKILL.md")
MANIFEST = os.path.join(VERSIONS, "versions.json")

# commit that the iteration-7/8 results were produced against, and the digest it
# produced. The directory is named for the DIGEST, not the commit, because the
# digest is what every other artifact refers to; the commit is recorded inside.
OLD_COMMIT = "2cced57"
OLD_SHA = "b8f84e805a2a2aec6ecff58f35ac7e6c55874308b4559a73efdb068fc5f00a1b"
OLD_DIR = OLD_SHA[:7]
OLD_PATH_IN_REPO = "skill/analyzing-programs/SKILL.md"

fails = []


def check(cond, msg, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {msg}" + (f"   {detail}" if detail else ""))
    if not cond:
        fails.append(msg)


def sha(path):
    return hashlib.sha256(io.open(path, "rb").read()).hexdigest()


def git_blob(commit, path):
    return subprocess.run(["git", "show", f"{commit}:{path}"],
                          capture_output=True, cwd=REPO).stdout


def main():
    os.makedirs(os.path.join(VERSIONS, OLD_DIR), exist_ok=True)
    blob = git_blob(OLD_COMMIT, OLD_PATH_IN_REPO)
    if not blob:
        print(f"cannot read {OLD_COMMIT}:{OLD_PATH_IN_REPO} from git")
        return 2
    old_path = os.path.join(VERSIONS, OLD_DIR, "SKILL.md")

    print("pinning the two versions under test")
    print("-" * 74)
    old_sha = hashlib.sha256(blob).hexdigest()
    live_sha = sha(LIVE)
    check(old_sha == OLD_SHA,
          f"{OLD_COMMIT} blob still hashes to the recorded digest", old_sha[:16] + "...")

    # The old version is re-extracted from git every run and the script owns that
    # file, so a rewritten copy is not a failure state -- it is repaired. What it
    # must NOT do is repair silently: a byte that moved means someone hand-edited
    # the pinned version, which would make the A/B compare something else.
    rewritten = os.path.exists(old_path) and sha(old_path) != old_sha
    if rewritten or not os.path.exists(old_path):
        io.open(old_path, "wb").write(blob)
    check(sha(old_path) == old_sha,
          f"{OLD_COMMIT} SKILL.md extracted byte-identically", old_sha[:16] + "...")
    check(not io.open(old_path, "rb").read(3) == b"\xef\xbb\xbf",
          "  and carries no BOM")
    check(git_blob(OLD_COMMIT, OLD_PATH_IN_REPO) == io.open(old_path, "rb").read(),
          "  and equals the git blob exactly")
    if rewritten:
        print(f"  note  the pinned copy had drifted and was re-extracted from git; "
              f"if that was not expected, someone edited it by hand")

    prior = None
    if os.path.exists(MANIFEST):
        try:
            prior = json.load(io.open(MANIFEST, encoding="utf-8"))
        except ValueError:
            prior = None

    record = {
        "_comment": [
            "The two SKILL.md versions iteration-9 compares. Both digests are",
            "asserted against their source by pin_skill_versions.py, so a round",
            "cannot report a number for a skill file that has since changed.",
            "The baseline arm is intentionally absent: it loads no skill file.",
        ],
        "old": {
            "label": OLD_SHA[:7],
            "commit": OLD_COMMIT,
            "path": os.path.relpath(old_path, REPO).replace("\\", "/"),
            "sha256": old_sha,
            "source": f"git show {OLD_COMMIT}:{OLD_PATH_IN_REPO}",
        },
        "new": {
            "label": live_sha[:7],
            "commit": "HEAD",
            "path": os.path.relpath(LIVE, REPO).replace("\\", "/"),
            "sha256": live_sha,
            "source": "the live tree; this is the version that ships",
        },
    }

    # This is the check that can actually fail, and it is the one that matters.
    # The old version is pinned to an immutable commit, so it cannot drift. The new
    # version IS the working tree: every edit to SKILL.md moves this digest. A round
    # that measured 718f5988 and then had SKILL.md edited would otherwise report a
    # number for a skill nobody ran -- which is exactly what happened to iteration-7
    # and iteration-8, whose digest existed only in a commit message.
    if prior and prior.get("new", {}).get("sha256") not in (None, live_sha):
        print(f"  FAIL  the live SKILL.md has changed since it was pinned")
        print(f"          pinned : {prior['new']['sha256']}")
        print(f"          on disk: {live_sha}")
        print(f"          Re-pin deliberately before generating, or every number")
        print(f"          produced from here on describes a skill that was not run.")
        fails.append("live SKILL.md drifted from its pin")
    elif prior:
        print(f"  ok    live SKILL.md still matches its pin   {live_sha[:16]}...")

    io.open(MANIFEST, "w", encoding="utf-8").write(
        json.dumps(record, ensure_ascii=False, indent=2))

    print()
    print("the old version must be a prompt and nothing else")
    print("-" * 74)
    old = io.open(old_path, encoding="utf-8").read()
    for token in ("scripts/", "schemas/", "references/", "evals/",
                  "report_qc", "report-contract", "example-report"):
        check(token not in old,
              f"  old version does not mention {token!r}")
    print()
    print("what changed between them")
    print("-" * 74)
    new = io.open(LIVE, encoding="utf-8").read()
    # added by the new version and expected to be absent from the old
    for token, label in [("这一轮不许改分析", "step 6: post-hoc repair pass"),
                         ("不确定就标注", "section: factual discipline"),
                         ("references/example-report.md", "shipped exemplar report")]:
        check(token in new and token not in old,
              f"  added in new: {label}")
    # added by b703918 then removed by faa8643, so it must be in NEITHER. Asserting
    # it here stops a future edit from quietly reintroducing four questions whose
    # two failing tests were the reason they were deleted.
    check("激活" not in old and "激活" not in new,
          "  the four activation questions are in neither version",
          "added by b703918, removed by faa8643")
    print()
    print(f"{'':4}{'version':10}{'lines':>7}{'bytes':>9}  sha256")
    for k in ("old", "new"):
        p = os.path.join(REPO, record[k]["path"])
        txt = io.open(p, encoding="utf-8").read()
        print(f"{'':4}{record[k]['label']:10}{txt.count(chr(10)) + 1:>7}"
              f"{len(txt.encode('utf-8')):>9}  {sha(p)[:32]}")

    print()
    print("-" * 74)
    if fails:
        print(f"{len(fails)} check(s) failed:")
        for f in fails:
            print("  -", f)
        return 1
    print(f"both versions pinned; manifest at "
          f"{os.path.relpath(MANIFEST, REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())