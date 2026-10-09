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


def main():
    base = io.open(BASE, encoding="utf-8").read()
    tmp = tempfile.mkdtemp()
    print("enforcement probes (current behaviour, see module docstring)")
    print("-" * 72)
    rc0, _ = gate(base, tmp, "p0_baseline.md")
    check(rc0 == 0, "baseline report passes the gate", f"rc={rc0}")

    m = re.search(FENCE + "abap\n(.*?)" + FENCE, base, re.S)
    lines = m.group(1).split("\n")
    i = next(k for k, l in enumerate(lines)
             if l.strip() and not l.strip().startswith(("*", '"')))
    lines[i] = "  lv_tampered = fabricated_token_does_not_exist( ) ."
    fabricated = base[:m.start(1)] + "\n".join(lines) + base[m.end(1):]
    rc, out = gate(fabricated, tmp, "p1_fabricated.md")
    check(rc == 0, "PROBE 1 gate currently PASSES a fabricated quote",
          f"rc={rc}")
    check("do not occur in the source" in out,
          "PROBE 1 the note is printed anyway")
    rc, _ = gate(fabricated, tmp, "p1_fidelity.md", ("--fidelity-only",))
    check(rc == 1, "PROBE 1 --fidelity-only does reject it", f"rc={rc}")

    lines5 = base.split("\n")
    i5 = next(k for k, l in enumerate(lines5) if l.startswith("## 五"))
    j5 = next(k for k in range(i5 + 1, len(lines5)) if lines5[k].startswith("## "))
    sec = lines5[i5:j5]
    rows = [k for k, l in enumerate(sec) if l.strip().startswith("|")]
    check(len(rows) > 4, "section five has rows to mutate", f"{len(rows)} rows")
    filler = "| P0 | 无 | 这段代码写得很好 | 无 | 无 | 无 |"
    for k in rows[1:5]:
        sec[k] = filler
    empty = "\n".join(lines5[:i5] + sec + lines5[j5:])
    rc, _ = gate(empty, tmp, "p2_empty_rows.md")
    check(rc == 0, "PROBE 2 gate currently PASSES rows with no content", f"rc={rc}")

    triple = re.compile(r"(?m)^\*\*(" + "|".join(LAYERS) + r")\*\*\s*[—–:-]")
    n_layers = len(triple.findall(base))
    check(n_layers >= 60, "report has enough layer lines to mutate",
          f"{n_layers}")
    same = triple.sub(lambda mm: mm.group(0).split("**")[0]
                      + "**" + mm.group(1) + "** — 这段代码值得一看。",
                      base)
    check(same != base, "PROBE 3 substitution actually changed the report",
          f"{len(base)} -> {len(same)} bytes")
    rc, _ = gate(same, tmp, "p3_same_layers.md")
    check(rc == 0, "PROBE 3 gate currently PASSES three identical layers", f"rc={rc}")

    nmm = len(re.findall(FENCE + "mermaid", base, re.I))
    check(nmm >= 2, "report has diagrams to delete", f"{nmm}")
    nomm = re.sub(FENCE + "mermaid\n.*?" + FENCE, "", base, flags=re.S | re.I)
    check("mermaid" not in nomm.lower(), "PROBE 4 all diagrams removed")
    rc, _ = gate(nomm, tmp, "p4_no_mermaid.md")
    check(rc == 0, "PROBE 4 gate currently PASSES a report with no diagram", f"rc={rc}")

    bad = base.replace("供应商", "供应商\ufffd\ufffd", 1)
    check(bad != base, "PROBE 5 substitution actually changed the report")
    rc, _ = gate(bad, tmp, "p5_fffd.md")
    check(rc == 0, "PROBE 5 gate currently PASSES a replacement char in prose", f"rc={rc}")

    h1 = re.search(r"(?ms)^## 一.*?(?=^## 二)", base)
    dup = base[:h1.end()] + h1.group(0) + base[h1.end():]
    check(len(re.findall(r"(?m)^## 一", dup)) == 2,
          "PROBE 6 section one now appears twice")
    rc, _ = gate(dup, tmp, "p6_dup_section.md")
    check(rc == 0, "PROBE 6 gate currently PASSES a duplicated section", f"rc={rc}")

    heads = [l for l in base.split("\n") if re.match(r"^#{1,3} ", l)]
    mini = ("\n".join(heads) + "\n\n" + FENCE + "abap\nREPORT lcl_foo.\n" + FENCE
            + "\n\n- 位置：`lcl_foo`\n- 为什么：`lcl_foo` 里这样\n"
            + "- 风险与改进：`lcl_foo` 会出错\n")
    check(len(mini) < 0.05 * len(base), "PROBE 7 skeleton is under 5% of the original",
          f"{len(mini)} vs {len(base)}")
    rc, _ = gate(mini, tmp, "p7_skeleton.md")
    check(rc != 0, "PROBE 7 gate REJECTS an empty skeleton (teeth intact)", f"rc={rc}")

    print()
    print("-" * 72)
    print(f"{N_OK} checks passed, {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())