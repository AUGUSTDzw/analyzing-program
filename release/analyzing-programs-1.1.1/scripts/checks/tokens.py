"""Tokenizing ABAP well enough to tell a punctuation slip from a rewrite.

The old fidelity check asked whether a flattened statement occurred in the
flattened source. That is a substring test, so any difference in punctuation
the flattener did not normalise -- a trailing period, a changed arrow -- reads as
fabrication. `fidelity_note`'s docstring records the cost: 16 mismatches, 5 of
them false, 69% precision, not enough to fail a report.

Comparing token sequences instead separates the two cases. An identifier, a
string literal or a number that changed is a rewrite and must fail. Punctuation
that moved is a slip and stays advisory.

Identifiers and keywords are lowercased because ABAP is case-insensitive there.
String literals are not: 'BUK' and 'bUK' are different data.
"""
import re

_TOKEN = re.compile(r"""
      (?P<literal>'(?:[^']|'')*')
    | (?P<number>\b\d+(?:\.\d+)?\b)
    | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<punct>=>|<>|>=|<=|\*|-|\+|=|<|>|\(|\)|,|;|:|\.)
""", re.X)


def tokenize(s):
    """[(kind, value)] for one statement, in source order."""
    out = []
    for m in _TOKEN.finditer(s):
        kind = m.lastgroup
        val = m.group(0)
        if kind == "ident":
            val = val.lower()
        out.append((kind, val))
    return out


def identity(seq):
    """The part of a token sequence that carries meaning.

    Two statements with the same identity differ only in punctuation. Anything
    that changes a name, a literal or a number changes the identity.
    """
    return tuple(v for k, v in seq if k != "punct")
