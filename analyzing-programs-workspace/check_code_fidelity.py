"""Does every quoted code line exist verbatim in the source?

The skill requires it: pasted code must be character-for-character faithful, and
must not be altered to read better. Nothing in the gate checks this, so a
rewritten statement passes every other check.

Semantics: a quoted line is faithful if it occurs in the source. Blocks are not
required to be contiguous, because a report may quote one construct in pieces,
and contiguity was the wrong test. It produced 92 false positives on the AVE
report on the first attempt -- every one a call to SAPGUI_PROGRESS_INDICATOR,
a source with 30 call sites of which the report quoted a different one, wrapped
across lines differently. Comparing blocks for contiguity measured re-wrapping,
not faithfulness.

Skipped, because they are not claims about the source:
  - lines carrying an elision marker, which the skill permits for boilerplate
  - parenthetical notes, which are the report's own commentary
  - lines under two characters

What remains is exactly the interesting set: statements the report shows that
the source does not contain.
"""
import io
import os
import re
import sys

sys.path.insert(0, sys.argv[1])
import report_qc

ROOT = sys.argv[2]
SRCDIR = os.path.join(ROOT, "Test-source", "real")

PAIRS = [
    ("Test-result/real/abapgit_flow_logic.skill.md",
     "abapGit__abapGit__zcl_abapgit_flow_logic.clas.abap"),
    ("Test-result/real/abapgit_forms.skill.md", "abapGit__abapGit__zabapgit_forms.prog.abap"),
    ("Test-result/real/abapgit_password_dialog.skill.md",
     "abapGit__abapGit__zabapgit_password_dialog.prog.abap"),
    ("Test-result/real/zcl_demo_abap_dynamic_prog.skill.md",
     "SAP-samples__abap-cheat-sheets__zcl_demo_abap_dynamic_prog.clas.abap"),
    ("Test-result/real/ysichov__AVE__z_ave_standalone.skill.md",
     "ysichov__AVE__src__z_ave_standalone.prog.abap"),
    ("Test-result/real/Keremkoseoglu__ABAP-Library__ZCL_FI_TOOLKIT.skill.md",
     "Keremkoseoglu__ABAP-Library__functional__fi__ZCL_FI_TOOLKIT.abap"),
    ("Test-result/real2/Keremkoseoglu__ZCL_FI_TOOLKIT.skill.md",
     "Keremkoseoglu__ABAP-Library__functional__fi__ZCL_FI_TOOLKIT.abap"),
    ("Test-result/real3/r1_Keremkoseoglu__ZCL_FI_TOOLKIT.skill.md",
     "Keremkoseoglu__ABAP-Library__functional__fi__ZCL_FI_TOOLKIT.abap"),
    ("Test-result/real3/r2_Keremkoseoglu__ZCL_FI_TOOLKIT.skill.md",
     "Keremkoseoglu__ABAP-Library__functional__fi__ZCL_FI_TOOLKIT.abap"),
    ("Test-result/real4/v4_zbc_show_error_log.skill.md",
     "hardyp__AbapToTheFuture03__src__zmonsters_p01_enablers__"
     "zmonsters_c04_exceptions__zbc_show_error_log.fugr.zbc_show_error_log.abap"),
]

ELIDE = re.compile(r"\.\.\.|\u2026")
NOTE = re.compile(r"^[\s|*]*[\uff08(].*[\uff09)]\s*$")
CJK = re.compile(r"[\u4e00-\u9fff]")
# The source writes "t_documents ," with a space before the comma and the report
# writes "t_documents,". That is punctuation spacing, not a rewritten statement,
# so normalise it away. Verified against the source: both forms occur.
PUNCT = re.compile(r"\s+([,;:)])")


def flat(s):
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = PUNCT.sub(r"\1", s)
    return re.sub(r"([(])\s+", r"\1", s)


def claimable(body):
    """Lines of a quote that assert something about the source."""
    out = []
    for raw in body.split("\n"):
        if ELIDE.search(raw):
            continue                       # skill-permitted boilerplate elision
        l = re.sub(r'^\s*[*"\'"]', "", raw).rstrip()
        if len(l.strip()) < 3 or NOTE.match(l):
            continue
        if CJK.search(l) and "|" not in l:
            continue                       # the report's own commentary
        if l.count('"') % 2:
            continue                       # unbalanced quote: a layout artefact
        out.append(l)
    return out


def audit(rep, src):
    """Return (n_claims, [(report_line, text)]) for statements absent from src."""
    sf = flat(src)
    n = 0
    bad = []
    for m in re.finditer(r"```abap\n(.*?)```", rep, re.S):
        if report_qc.in_risk_layer(rep[:m.start()]):
            continue                      # remediation snippet, not a quote
        base = rep[:m.start()].count("\n") + 1
        for i, l in enumerate(claimable(m.group(1))):
            n += 1
            probe = l.strip().rstrip(".")
            if probe and flat(probe) not in sf:
                bad.append((base + 1 + i, l.strip()))
    return n, bad


def main():
    print(f"{'report':46}{'claims':>8}{'absent':>8}  rate    examples")
    print("-" * 108)
    tn = tb = 0
    allbad = []
    for rel, srcname in PAIRS:
        rp, sp = os.path.join(ROOT, rel), os.path.join(SRCDIR, srcname)
        if not (os.path.exists(rp) and os.path.exists(sp)):
            print(f"{os.path.basename(rel)[:44]:46}  missing source {srcname[:30]}")
            continue
        rep = io.open(rp, encoding="utf-8").read()
        src = io.open(sp, encoding="utf-8", errors="replace").read()
        n, bad = audit(rep, src)
        tn += n
        tb += len(bad)
        ex = "; ".join(f"L{ln} {t[:30]}" for ln, t in bad[:2])
        print(f"{os.path.basename(rel)[:44]:46}{n:>8}{len(bad):>8}"
              f"  {len(bad)/max(1,n)*100:>4.1f}%  {ex}")
        allbad += [(os.path.basename(rel), ln, t) for ln, t in bad]
    print("-" * 108)
    print(f"{'TOTAL':46}{tn:>8}{tb:>8}  {tb/max(1,tn)*100:>4.1f}%")
    if allbad:
        print("\nevery absent statement:")
        for f, ln, t in allbad:
            print(f"  {f[:44]:46} L{ln:<5} {t[:60]}")
    return tn, tb


if __name__ == "__main__":
    main()
