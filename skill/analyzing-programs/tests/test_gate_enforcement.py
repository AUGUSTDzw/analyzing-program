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




DOT, SEMI, COMMA = "\u3002", "\uff1b", "\uff0c"
# Circled digits survive as a marker set on purpose: PROBE 11 needs them to
# rebuild the one-per-line shape A8-list used to accept. They are not markdown
# list markers, so nothing in the baseline may be built from them.
MARKS = "\u2460\u2461\u2462\u2463\u2464\u2465\u2466\u2467\u2468\u2469"


def _items(body):
    """A first layer's sentences, split only outside backtick spans.

    Splitting at a mark inside a span would break the quoted source statement and
    make a clean baseline read as rewritten, which would hide the defect the
    probe it feeds is meant to measure. If one sentence remains, the last comma
    outside a span is used so the layer still segments.
    """
    parts, cur, depth = [], "", 0
    for ch in body:
        if ch == "`":
            depth ^= 1
        elif depth == 0 and ch in (DOT, SEMI):
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    parts = [p for p in parts if p.strip()]
    if len(parts) == 1:
        depth, cut = 0, -1
        for i, ch in enumerate(parts[0]):
            if ch == "`":
                depth ^= 1
            elif ch == COMMA and depth == 0:
                cut = i
        if 0 < cut < len(parts[0]) - 1:
            head, tail = parts[0][:cut], parts[0][cut + 1:]
            if head.strip() and tail.strip():
                parts = [head.strip(), tail.strip()]
    return parts


def listify(text):
    """Give every first layer the segmented form A8-list requires.

    BASE is a 2026-10-09 experiment artifact: what the skill wrote before this
    rule existed, with a judge verdict already recorded against it. Rewriting it
    to comply would change what that run produced, so the baseline is derived
    instead -- its own sentences re-emitted as list items, no word invented.
    """
    out = []
    for line in text.split("\n"):
        m = re.match(r"^(\*\*" + LAYERS[0] + r"\*\*\s*[\u2014\u2013:-]\s*)(.+)$",
                     line)
        if not m:
            out.append(line)
            continue
        head, body = m.group(1), m.group(2).strip()
        out.append(head)
        for k, part in enumerate(_items(body)[:len(MARKS)]):
            # Numbered, not circled: 1.1.31 accepted ① per line, which CommonMark
            # prints as one paragraph. The derived baseline must be the form the
            # gate now enforces, or PROBE 10's negative half would be vacuous.
            out.append("%d. %s" % (k + 1, part.strip()))
    return "\n".join(out)


def circulate(text):
    """Swap a first layer's markdown markers back to circled digits, one per
    line: the shape 1.1.31 accepted and printed as a single paragraph.

    Runs on a compliant report, so it replaces markers only and invents no
    prose. That is what makes PROBE 11 a clean isolation -- the circled version
    and the numbered one differ in nothing but the marker.
    """
    label = re.compile(r"^[ \t]*\*\*(?:%s)\*\*" % "|".join(LAYERS))
    out, n = [], 0
    for line in text.split("\n"):
        if label.match(line):
            n = 0
        m = re.match(r"^([ \t]*)(\d+)\. (\S.*)$", line)
        if m and n < len(MARKS):
            out.append("%s%s %s" % (m.group(1), MARKS[n], m.group(3)))
            n += 1
        else:
            out.append(line)
    return "\n".join(out)


def main():
    raw = io.open(BASE, encoding="utf-8").read()
    base = listify(raw)
    tmp = tempfile.mkdtemp()
    print("enforcement probes (current behaviour, see module docstring)")
    print("-" * 72)
    rc0, _ = gate(base, tmp, "p0_baseline.md")
    check(rc0 == 0, "baseline passes once its first layers are "
                           "segmented", f"rc={rc0}")

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

    # PROBE 8: exit 2 must not follow a printed verdict. Exit 2 means nothing
    # was inspected, so a caller that read it found either a PASS to discard or
    # a run to trust. Existence was pre-flighted for all reports; a directory and
    # a report that does not decode as utf-8 both fired inside the loop, after
    # the earlier reports had printed.
    print()
    print("PROBE 8: a refusal never follows a printed verdict")
    print("-" * 72)
    good = os.path.join(tmp, "p8_good.md")
    io.open(good, "w", encoding="utf-8", newline="").write(base)
    bad_utf8 = os.path.join(tmp, "p8_gbk.md")
    io.open(bad_utf8, "wb").write(base.encode("gbk", errors="replace"))
    bad_dir = os.path.join(tmp, "p8_dir.md")
    os.makedirs(bad_dir, exist_ok=True)
    for mode_label, mode in (("", ()), ("--fidelity-only", ("--fidelity-only",))):
        for bad_label, bad in (("a directory", bad_dir),
                               ("a report that is not utf-8", bad_utf8)):
            r = run(*(mode + (good, bad, SRC)))
            verdicts = [l for l in r.stdout.splitlines()
                        if l.startswith(("PASS", "FAIL"))]
            errs = [l for l in r.stdout.splitlines() if l.startswith("error  ")]
            where = mode_label or "shape mode"
            check(r.returncode == 2 and not verdicts and len(errs) == 1,
                  "PROBE 8 %s: %s is refused before the first verdict"
                  % (where, bad_label),
                  "rc=%d verdicts=%d errs=%d" % (r.returncode, len(verdicts),
                                                 len(errs)))
    r = run(good, good, SRC)
    check(r.returncode == 0, "PROBE 8 two good reports still pass",
          "rc=%d" % r.returncode)
    check(len([l for l in r.stdout.splitlines()
               if l.startswith("PASS")]) == 2,
          "PROBE 8 both verdicts are still printed")

    # -o only exists in --fix. Outside it the flag fell into the extension split:
    # -o read as a source and the output path read as a report, so the refusal
    # said "more than one source" without ever naming the cause.
    r = run(good, SRC, "-o", os.path.join(tmp, "p8_out.md"))
    check(r.returncode == 2 and "only valid with --fix" in r.stdout,
          "PROBE 8 -o outside --fix is refused and the cause is named",
          "rc=%d" % r.returncode)

    # A report with no quotation used to clear fidelity with no line at all,
    # which reads as "faithful". Its source statements were stripped, not
    # rewritten, and those are not the same event.
    noquote = mini.replace(FENCE + "abap\nREPORT lcl_foo.\n" + FENCE, "")
    rc, out = gate(noquote, tmp, "p8_noquote.md")
    check("no quoted source statement" in out,
          "PROBE 8 shape mode: a report with no quotation says so instead of "
          "staying silent")
    rc, out = gate(noquote, tmp, "p8_noquote_fo.md", ("--fidelity-only",))
    check(rc == 0 and "no quoted source statement" in out,
          "PROBE 8 --fidelity-only: the same silence is filled in",
          "rc=%d" % rc)

    print()
    print("PROBE 9: an escape written out as text is a defect")
    print("-" * 72)
    # The bytes are right and the file is valid UTF-8; the writer owed one
    # newline and wrote out the escape instead. enc sees nothing here, and no
    # structural detector does either, so a report like this used to clear the
    # gate. Two shapes: the backslash one, and the one that actually reached a
    # shipped report, where every backslash had become a backtick.
    sl = base + "\n\n这里本该是一个换行，正文里坐着字面的 " + chr(92) + "n。\n"
    check(sl != base, "PROBE 9 backslash residue actually changed the report")
    rc, out = gate(sl, tmp, "p9_backslash.md")
    check(rc != 0, "PROBE 9 gate now REJECTS a literal backslash-n in prose",
          f"rc={rc}")
    check("esc" in out, "PROBE 9 the backslash shape is reported as kind 'esc'",
          out.strip().splitlines()[0][:80] if out.strip() else "")
    tk = base + "\n\n" + chr(96) + "n" + chr(96) + "n" + "\n"
    check(tk != base, "PROBE 9 backtick residue actually changed the report")
    rc, out = gate(tk, tmp, "p9_tickn.md")
    check(rc != 0, "PROBE 9 gate now REJECTS the backtick-mangled shape",
          f"rc={rc}")
    check("esc" in out, "PROBE 9 the tick shape is reported as kind 'esc'",
          out.strip().splitlines()[0][:80] if out.strip() else "")
    # Quoting an escape names it instead of shipping it, so the same two
    # characters inside an inline span must not trip the probe. The baseline is
    # clean, so this reads as a negative control on the span exemption.
    quiet = (base + "\n\n正文里写 " + chr(96) + chr(92) + "n" + chr(96)
             + " 只是在说这个名字。\n")
    rc, out = gate(quiet, tmp, "p9_quoted.md")
    check("esc" not in out, "PROBE 9 a quoted escape is not residue",
          out.strip().splitlines()[0][:80] if out.strip() else "")

    # PROBE 10: the first layer written as a paragraph instead of a segmented
    # list. raw is BASE before listify(), so it is the unsegmented baseline --
    # the shape the rule was added for. The rule checks the count of list items
    # against the number of statements in the quoted block, so it cannot tell a
    # specific item from a vague one.
    print()
    print("PROBE 10: a first layer written as a paragraph is a defect")
    print("-" * 72)
    check(listify(raw) != raw,
          "PROBE 10 precondition: raw still carries an unsegmented first layer")
    rc, out = gate(raw, tmp, "p10_paragraph.md")
    check(rc != 0, "PROBE 10 gate now REJECTS first layers written as paragraphs",
          f"rc={rc}")
    check("A8-list" in out, "PROBE 10 reported as kind 'A8-list'",
          out.strip().splitlines()[0][:80] if out.strip() else "")
    check("segmented list" in out, "PROBE 10 names what the layer owed")
    rc2, out2 = gate(base, tmp, "p10_listified.md")
    check(rc2 == 0 and "A8-list" not in out2,
          "PROBE 10 the segmented baseline is clean", f"rc={rc2}")

    # PROBE 11: the marker, not the segmentation, is what 1.1.31 got wrong.
    # base is compliant, so circulate() only swaps markers and invents no prose;
    # the result is the exact shape a deployed 1.1.31 gate accepted and printed
    # as one paragraph.
    print()
    print("PROBE 11: one circled digit per line is not a list")
    print("-" * 72)
    circ = circulate(base)
    check(circ != base,
          "PROBE 11 precondition: base carries markdown markers", "")
    strip = re.compile(r"^[ \t]*(?:\d+\.|[\u2460-\u246b])\s*", re.M)
    check(strip.sub("", circ) == strip.sub("", base),
          "PROBE 11 the only difference is the marker, so the variable is "
          "isolated", "")
    rc3, out3 = gate(circ, tmp, "p11_circled.md")
    check(rc3 != 0, "PROBE 11 circled digits no longer satisfy A8-list",
          f"rc={rc3}")
    check("A8-list" in out3, "PROBE 11 reported as kind 'A8-list'",
          out3.strip().splitlines()[0][:80] if out3.strip() else "")
    check("circled digits are not markdown list markers" in out3,
          "PROBE 11 names the marker that was not counted",
          out3.strip().splitlines()[0][:80] if out3.strip() else "")
    return finish()


if __name__ == "__main__":
    sys.exit(main())
