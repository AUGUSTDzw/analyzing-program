"""Probes for the enforcement holes found on 2026-10-09.

Each probe mutates a report that currently PASSES the gate and records what
the gate does with it. Task 1 asserts the CURRENT behaviour, which is that the
gate passes all of them. Task 9 and 10 flip these expectations to the behaviour
1.1.0 must have. Keeping both in one file is the point: the same probe, first
recorded as wrong, then proven right.

Run: python tests/test_gate_enforcement.py
"""
import io, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QC = os.path.join(HERE, "..", "scripts", "report_qc.py")
REPO = os.path.dirname(os.path.dirname(ROOT))
BASE = os.path.join(REPO, "analyzing-programs-workspace", "exp-1.0.9",
                    "with_skill", "run1.md")
SRC = os.path.join(REPO, "Test-source", "zvend.abap")
FENCE = chr(96) * 3
LAYERS = ("做什么", "为什么", "风险与改进")

N_OK = 0
FAILS = []


def check(cond, label, detail=""):
    global N_OK
    if cond:
        N_OK += 1
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAILS.append(label)


def run(*args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    return subprocess.run([sys.executable, QC] + list(args), capture_output=True,
                          text=True, encoding="utf-8", env=env)


def gate(text, tmpdir, name, extra=()):
    """Write a mutated report and run the gate on it. Returns (rc, output)."""
    p = os.path.join(tmpdir, name)
    io.open(p, "w", encoding="utf-8", newline="").write(text)
    r = run(*(list(extra) + [p, SRC]))
    return r.returncode, r.stdout + r.stderr


def finish():
    print()
    print("-" * 72)
    print(f"{N_OK} checks passed, {len(FAILS)} failed")
    return 1 if FAILS else 0


def bail(label):
    """A precondition of this file is gone, so every later probe would run on a
    report we no longer control. Record the missing structure and exit cleanly:
    an uncaught StopIteration/AttributeError would abort main() and silently
    drop the remaining checks, which is worse than a counted failure."""
    check(False, label)
    return finish()


def main():
    base = io.open(BASE, encoding="utf-8").read()
    tmp = tempfile.mkdtemp()
    print("enforcement probes (current behaviour, see module docstring)")
    print("-" * 72)
    rc0, _ = gate(base, tmp, "p0_baseline.md")
    check(rc0 == 0, "baseline report passes the gate", f"rc={rc0}")

    m = re.search(FENCE + "abap\n(.*?)" + FENCE, base, re.S)
    if m is None:
        return bail("abap fence is present in the baseline")
    lines = m.group(1).split("\n")
    i = next((k for k, l in enumerate(lines)
              if l.strip() and not l.strip().startswith(("*", '"'))), None)
    if i is None:
        return bail("baseline abap fence holds at least one quotable statement")
    lines[i] = "  lv_tampered = fabricated_token_does_not_exist( ) ."
    fabricated = base[:m.start(1)] + "\n".join(lines) + base[m.end(1):]
    check(fabricated != base, "PROBE 1 substitution actually changed the report",
          f"{len(base)} -> {len(fabricated)} chars")
    rc, out = gate(fabricated, tmp, "p1_fabricated.md")
    check(rc != 0, "PROBE 1 gate now REJECTS a fabricated quote",
          f"rc={rc}")
    check("not occur in the source" in out,
          "PROBE 1 the note is still printed")
    rc, _ = gate(fabricated, tmp, "p1_fidelity.md", ("--fidelity-only",))
    check(rc == 1, "PROBE 1 --fidelity-only does reject it", f"rc={rc}")

    lines5 = base.split("\n")
    i5 = next((k for k, l in enumerate(lines5) if l.startswith("## 五")), None)
    if i5 is None:
        return bail("section five heading is present in the baseline")
    j5 = next((k for k in range(i5 + 1, len(lines5))
               if lines5[k].startswith("## ")), None)
    if j5 is None:
        return bail("section five is followed by another top-level heading")
    sec = lines5[i5:j5]
    rows = [k for k, l in enumerate(sec) if l.strip().startswith("|")]
    if len(rows) < 5:
        return bail("section five has header, divider and at least three rows "
                    f"({len(rows)} table lines found)")
    # Five cells, matching the P0 table's own header, so this probe blanks a
    # finding without also changing the table shape. Every cell is prose with no
    # backticked token and no identifier from the source: that is the whole
    # defect, and keeping it the only defect means the probe can only flip when
    # something learns to require a finding to name a source object.
    filler = "| P0-1 | 无 | 这段代码写得很好 | 无 | 无 |"
    # rows[0] is the header and rows[1] the |---| divider: replacing either would
    # break the table, not blank out a finding. Start at 2 to touch real rows only.
    for k in rows[2:5]:
        sec[k] = filler
    empty = "\n".join(lines5[:i5] + sec + lines5[j5:])
    rc, out = gate(empty, tmp, "p2_empty_rows.md")
    check(rc != 0, "PROBE 2 gate now REJECTS rows that name nothing", f"rc={rc}")
    check("row-src" in out, "PROBE 2 reported as kind 'row-src'",
          out.strip().splitlines()[0][:80] if out.strip() else "")

    layer_re = r"(?m)^\*\*(" + "|".join(LAYERS) + r")\*\*[^\n]*"
    triple = re.compile(layer_re)
    n_layers = len(triple.findall(base))
    check(n_layers >= 60, "report has enough layer lines to mutate",
          f"{n_layers}")
    # The tail must go too. Replacing only the bold label leaves each block's
    # original prose in place, so the three bodies stay different and the probe
    # stops measuring what it claims: C2 compares bodies, and bodies that are
    # still individually distinctive will not trip it. Swallowing the line and
    # writing back one canned sentence per layer makes all three bodies equal,
    # which is the defect the probe is named for.
    same = triple.sub(lambda mm: "**" + mm.group(1) + "** — 这段代码值得一看。",
                      base)
    check(same != base, "PROBE 3 substitution actually changed the report",
          f"{len(base)} -> {len(same)} chars")
    bodies = {}
    for lab, body in re.findall(r"(?m)^\*\*(" + "|".join(LAYERS) + r")\*\*"
                                r"\s*[—–:-]\s*(.*)$", same):
        bodies.setdefault(lab, set()).add(body.strip())
    distinct = {lab: len(b) for lab, b in bodies.items()}
    check(sorted(distinct) == sorted(LAYERS) and set(distinct.values()) == {1},
          "PROBE 3 every layer body is now one repeated sentence",
          f"unique bodies per layer: {distinct}")
    check(len({next(iter(b)) for b in bodies.values()}) == 1,
          "PROBE 3 the three layer bodies are identical to each other")
    rc, out = gate(same, tmp, "p3_same_layers.md")
    check(rc != 0, "PROBE 3 gate now REJECTS three identical layers", f"rc={rc}")
    check("layer-same" in out, "PROBE 3 reported as kind 'layer-same'",
          out.strip().splitlines()[0][:80] if out.strip() else "")

    nmm = len(re.findall(FENCE + "mermaid", base, re.I))
    check(nmm >= 2, "report has diagrams to delete", f"{nmm}")
    nomm = re.sub(FENCE + "mermaid\n.*?" + FENCE, "", base, flags=re.S | re.I)
    check("mermaid" not in nomm.lower(), "PROBE 4 all diagrams removed")
    rc, out = gate(nomm, tmp, "p4_no_mermaid.md")
    check(rc != 0, "PROBE 4 gate now REJECTS a report with no diagram", f"rc={rc}")
    check("mm-missing" in out, "PROBE 4 reported as kind 'mm-missing'",
          out.strip().splitlines()[0][:80] if out.strip() else "")

    bad = base.replace("供应商", "供应商\ufffd\ufffd", 1)
    check(bad != base, "PROBE 5 substitution actually changed the report")
    rc, out = gate(bad, tmp, "p5_fffd.md")
    check(rc != 0, "PROBE 5 gate now REJECTS a replacement char in prose", f"rc={rc}")
    check("enc" in out, "PROBE 5 the violation is reported as kind 'enc'",
          out.strip().splitlines()[0][:80] if out.strip() else "")

    h1 = re.search(r"(?ms)^## 一.*?(?=^## 二)", base)
    if h1 is None:
        return bail("sections one and two are present in the baseline")
    dup = base[:h1.end()] + h1.group(0) + base[h1.end():]
    check(len(re.findall(r"(?m)^## 一", dup)) == 2,
          "PROBE 6 section one now appears twice")
    rc, out = gate(dup, tmp, "p6_dup_section.md")
    check(rc != 0, "PROBE 6 gate now REJECTS a duplicated section", f"rc={rc}")
    check("sec-dup" in out, "PROBE 6 reported as kind 'sec-dup'",
          out.strip().splitlines()[0][:80] if out.strip() else "")

    heads = [l for l in base.split("\n") if re.match(r"^#{1,3} ", l)]
    mini = ("\n".join(heads) + "\n\n" + FENCE + "abap\nREPORT lcl_foo.\n" + FENCE
            + "\n\n- 位置：`lcl_foo`\n- 为什么：`lcl_foo` 里这样\n"
            + "- 风险与改进：`lcl_foo` 会出错\n")
    check(len(mini) < 0.05 * len(base), "PROBE 7 skeleton is under 5% of the original",
          f"{len(mini)} vs {len(base)}")
    rc, _ = gate(mini, tmp, "p7_skeleton.md")
    check(rc != 0, "PROBE 7 gate REJECTS an empty skeleton (teeth intact)", f"rc={rc}")

    return finish()


if __name__ == "__main__":
    sys.exit(main())
