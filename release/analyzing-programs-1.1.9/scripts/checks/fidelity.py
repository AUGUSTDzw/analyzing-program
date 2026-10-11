"""Fidelity: does every quoted statement actually occur in the source?

Two tiers, decided in the spec for 1.1.0:

  PUNCT-ONLY    punctuation differs from the source but the tokens carrying
                meaning are identical. Advisory. Exit stays 0.
  SUBSTANTIVE   an identifier, a string literal or a number changed. The report
                describes code that does not exist. Exit 1.

Before 1.1.0 this was one note that never changed an exit code, so a report that
invented an ABAP statement printed 'Check whether the report rewrote the source'
and was still PASS. That is the single largest hole found on 2026-10-09.

The tier is decided by two classifiers disagreeing, not by inspecting one
statement -- see classify(), added in the next step.
"""
from checks.contract import QUOTE_LANG as _QUOTE_LANG
from checks.text import _claims, _flat, fence_spans, line_of
from checks.tokens import identity, tokenize

_DETAIL = {
    "SUBSTANTIVE": "quoted statement does not occur in the source: an "
                    "identifier, a literal or a number differs",
    "PUNCT-ONLY": "punctuation differs from the source; the tokens carrying "
                  "meaning are identical",
}


_MAX_WINDOW = 30
_MAX_CACHE = 10
_src_cache = {}


def _src_identities(src):
    """Every contiguous identity window up to _MAX_WINDOW tokens in the source.

    A quoted statement is one statement, not a suffix. Checking identity
    membership means checking if the probe's identity tuple appears as a
    contiguous subsequence in the source -- which requires pre-computing
    windows of every size, not just suffixes. Capped at _MAX_WINDOW tokens per
    position, so the count is O(N x _MAX_WINDOW) rather than the O(N^2) a full
    unbounded scan would produce.

    Cached: --fidelity-only checks multiple reports against one source. The
    cache is bounded at _MAX_CACHE entries; the oldest entry is evicted when
    the limit is reached.
    """
    if src not in _src_cache:
        if len(_src_cache) >= _MAX_CACHE:
            # Evict the first-inserted entry. Dict insertion order is
            # preserved since Python 3.7, so the first key is the oldest.
            _src_cache.pop(next(iter(_src_cache)))
        seq = identity(tokenize(src))
        windows = set()
        for i in range(len(seq)):
            for size in range(1, min(_MAX_WINDOW, len(seq) - i) + 1):
                windows.add(seq[i:i + size])
        _src_cache[src] = windows
    return _src_cache[src]


def _substring_mismatch(probe, flat_src):
    """The pre-1.1.0 test: a flattened substring containment check.

    Kept deliberately. It is what PUNCT-ONLY is measured against -- without it
    there is no way to tell a punctuation slip from a rewrite, only to tell
    'something differs' from 'nothing differs'.
    """
    return _flat(probe) not in flat_src


def classify(s, src):
    """[(tier, line, report_line, detail)] for every quoted statement.

    `line` is 1-based in the report. Both classifiers run so the tier can be
    decided by their disagreement:

        old mismatch, new match   -> PUNCT-ONLY    punctuation moved
        old mismatch, new mismatch -> SUBSTANTIVE   a name, literal or number changed
        both match                -> faithful, nothing emitted

    A statement the old check missed and the new check misses is still a
    SUBSTANTIVE: neither algorithm is trusted to be exhaustive, so the union
    decides.
    """
    if not src:
        return []
    src_ids = _src_identities(src)
    flat_src = _flat(src)
    found = []
    for st, bs, be, _en, lang in fence_spans(s):
        if lang != _QUOTE_LANG.lower():
            continue
        base = line_of(s, st)
        for i, raw in _claims(s[bs:be]):
            probe = raw.strip()
            c = probe.find('"')
            if c >= 0:
                probe = probe[:c]
            probe = probe.rstrip(".")
            if not probe:
                continue
            ident = identity(tokenize(probe))
            new_ok = bool(ident) and ident in src_ids
            old_ok = not _substring_mismatch(probe, flat_src)
            if old_ok and new_ok:
                continue
            tier = "SUBSTANTIVE" if not new_ok else "PUNCT-ONLY"
            found.append((tier, base + 1 + i, raw.strip(), _DETAIL[tier]))
    return found


def fidelity_report(s, src):
    """(n_substantive, n_punct_only, tiers, notes)."""
    found = classify(s, src)
    sub = [f for f in found if f[0] == "SUBSTANTIVE"]
    pun = [f for f in found if f[0] == "PUNCT-ONLY"]
    notes = []
    if sub:
        notes.append("%d quoted statement(s) rewrite the source. First at line "
                     "%d: %r" % (len(sub), sub[0][1], sub[0][2][:60]))
    if pun:
        notes.append("%d quoted statement(s) differ from the source in "
                     "punctuation only; advisory. First at line %d: %r"
                     % (len(pun), pun[0][1], pun[0][2][:60]))
    return len(sub), len(pun), found, notes
