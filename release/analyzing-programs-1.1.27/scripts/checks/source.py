"""What counts as a source that has something in it.

Stands alone on purpose: it imports nothing from checks/contract.py, so a script
that has nothing to do with a report -- recon.py, docgen.py -- can read the
predicate without also taking on the rule set. checks/text.py keeps it in its own
__all__ so the gate's star import still reaches it, but the definition lives here,
where it can be imported without side effects.

One definition, read by four callers, because the two ways it was spelled before
drew different lines: `.strip()` passes a file of null bytes, and isprintable()
passes a file of replacement characters.
"""
__all__ = ["has_content"]


def has_content(src):
    """Whether a source carries any character that can be analysed.

    `strip()` removes whitespace, and control bytes are not whitespace, so
    "\x00" * 500 survives it and a file with nothing in it passed as a one-line
    program. isprintable() alone is not enough either: it is True of U+FFFD, the
    replacement character, so a source that is nothing but the corruption signature
    checks/encoding.py exists to catch passed as well, and got a document about a
    program that does not exist. Callers are recon.py, docgen.py, report_qc.py in
    both its refusal and its note, and checks/text.py's _src_of, so none of them
    can draw the line in a different place from the others.
    """
    return any(ch.isprintable() and ch != "\ufffd" for ch in (src or "").strip())
