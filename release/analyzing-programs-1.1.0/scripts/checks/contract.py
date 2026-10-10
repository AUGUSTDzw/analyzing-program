"""The contract, loaded once, and everything derived from it.

report_qc.py used to load the JSON at import time and derive a dozen constants
inline. Those derivations were spread across the file, so a rule that existed in
the contract but not in the gate was invisible: `test_contract_drift.py` could
only check what a module imported.

Contract version 1.2.6 -> 1.3.0 in 1.1.0. Five new rule keys:
problem_section.rows_require_source_object, layers.distinct,
encoding.replacement_char, mermaid.required_diagrams, sections_exactly_once.
Shipped with 1.1.0.
"""
import io, json, os, re, sys

# `import *` takes whatever is not underscore-prefixed unless __all__ says
# otherwise, so without this line io/json/os/re/sys rode back into report_qc.py
# on the star import. Harmless today -- report_qc.py imports io/os/re/sys itself
# and never mentions json -- and that is exactly what makes it a trap: a
# detector there that reaches for json.load would resolve it through this module
# and keep working in tests that never install the gate, then fail on a system
# where something else owns the name. An explicit list turns a silent
# resolution into a NameError at import.
__all__ = ["CONTRACT", "CONTRACT_PATH", "SEC", "SEC_RE", "LAYERS", "A8_GAP",
           "BUCKETS", "ROW", "DIAGRAM_LANG", "FENCE_LANGS", "QUOTE_LANG",
           "FIX_LANG", "PSEC", "PSEC_RE", "LINE_NUM", "FULLWIDTH", "MM_BAD",
           "DENSITY_FLOOR", "CITE_NUM", "ANCHORS"]

# Fence language decides whether a fence quotes source or illustrates a proposed
# fix. Position exempts nothing: a block after a 风险与改进 label is indistinguishable
# from the next sub-step's real quote, and the positional exemption used to skip
# genuine quotes wholesale (12 of 138 statements inspected on a report carrying
# 20 blocks). A mislabeled fix is caught by fix_lang_note instead of being
# silently trusted. Both names are read from the contract below rather than
# spelled out here, which is where they used to live.

# The rule set is read from schemas/report-contract.json, not hardcoded here.
# Seven fixes in this project were a detector disagreeing with the rule it was
# meant to enforce: LINE_NUM matched two spellings so a report written as `L23`
# throughout scored clean, and the checking half and the fixing half of the
# Mermaid rule carried different patterns so one reported what the other skipped.
# A second copy of the rules inside this file is the cause of that class of bug,
# so there is now one copy. Every rule in the contract carries a skill_anchor,
# and test_contract_drift.py fails when that anchor is absent from SKILL.md, so
# the contract and the prose cannot drift apart either.
_HERE = os.path.dirname(os.path.abspath(__file__))
CONTRACT_PATH = os.path.join(_HERE, "..", "..", "schemas", "report-contract.json")
try:
    with io.open(CONTRACT_PATH, encoding="utf-8") as _fh:
        CONTRACT = json.load(_fh)
except (OSError, ValueError) as _e:
    # The rule set is read before the script can run, so a missing or corrupt
    # contract dies here -- before main(), before every exit-2 guard below.
    # An unhandled exception exits 1, which SKILL.md defines as "the check ran
    # and found defects". The caller then goes and fixes defects that do not
    # exist, or loops on step 7 forever: the one false reassurance this script
    # is not allowed to give arrives from the wrong door. Refuse instead.
    sys.stdout.write("error  cannot read the rule set at %s (%s), so nothing "
                     "was checked\n" % (CONTRACT_PATH, _e))
    sys.exit(2)

SEC = ["## " + s["id"] for s in CONTRACT["sections"]]
# The gate must find a section at level two, not merely contain its string.
# "### 一、..." contains "## 一", so a report written entirely in ### satisfied
# every section and reported back clean -- and section 五 was then harvested
# from the wrong place. Anchored at the line start instead.
SEC_RE = [(re.compile(r"^" + re.escape(h), re.M), h[3:]) for h in SEC]
LAYERS = tuple(CONTRACT["layers"]["labels"])
# How much prose counts as "some" at all. A bare 20 sat in check(), the one
# threshold in this rule set that existed in no other place.
A8_GAP = CONTRACT["layers"]["prose_window_max_chars"]
BUCKETS = tuple(CONTRACT["problem_section"]["buckets"])
# Built from BUCKETS instead of re-spelling the four emoji, and DIAGRAM_LANG read
# from the contract instead of being written twice. Both are the second-copy
# defect: the priority colours appeared once in the contract and once here, and
# the Mermaid fence name appeared once in the gate and once in the fixer.
ROW = re.compile(r"^\|\s*(?:P[0-3][-.]?\d+|[%s])\s*\|"
                 % re.escape("".join(BUCKETS)), re.M)
DIAGRAM_LANG = CONTRACT["mermaid"]["fence_language"]
FENCE_LANGS = CONTRACT["layers"]["fence_languages"]
QUOTE_LANG = FENCE_LANGS["quotes_source"]
FIX_LANG = FENCE_LANGS["illustrates_a_fix"]
PSEC = CONTRACT["problem_section"]["heading"]
PSEC_RE = re.compile(r"^" + re.escape(PSEC), re.M)
# The problem section ends where the next section begins. Both bounds come from
# the contract: check() used to look for the literals "## 五" and "## 六", so
# editing problem_section.heading changed nothing and PSEC sat unused.
_IDS = [x["id"] for x in CONTRACT["sections"]]
_NEXT_SEC = (SEC[_IDS.index(CONTRACT["problem_section"]["id"]) + 1]
             if CONTRACT["problem_section"]["id"] in _IDS else None)
_NEXT_SEC_RE = (re.compile(r"^" + re.escape(_NEXT_SEC), re.M)
                if _NEXT_SEC else None)
# The English spellings require whitespace. Allowing \s* let `lines?\s*\d+` match
# LINE1 and LINE2, which are identifiers, and report them as line citations.
LINE_NUM = re.compile(
    "|".join("(?:%s)" % p["regex"]
             for p in CONTRACT["forbidden_in_location_labels"]["patterns"]), re.I)
FULLWIDTH = CONTRACT["mermaid"]["fullwidth"]
# The three characters the checker rejects are the contract's own list, not a
# second [<>#] literal. The class used to be spelled out in the checker and in
# the fixer separately; the file's docstring opens with the history of that
# exact split causing a reported defect the fixer skipped.
MM_BAD = re.compile(r"[%s]"
                    % re.escape("".join(CONTRACT["mermaid"]["forbid_in_display_text"])))


DENSITY_FLOOR = next(a["floor_blocks_per_subprogram"] for a in
                     CONTRACT["advisories"] if a["id"] == "density")
# LINE_NUM decides whether a backticked span is a citation at all, so this only
# has to pull the number out of one it already approved. Anchoring it to the whole
# string used to make three of the five forms the contract lists unparseable:
# `zvend.abap:104` and `（第 90-96 行）` are not "purely a line number", and they
# are the two examples SKILL.md prints as wrong, so --fix told the model to write
# them and then refused to repair them.
# First digit run, so a range resolves to its start -- the nearest preceding
# construct there is the one the range begins in.
# Take the widest digit run the contract admits, out of the contract, so no
# accepted citation is ever left unparsed and check() and fix_ln() cannot
# disagree about what a citation is. A copied {2,5} cap made check() accept
# `L100000` while fix_ln() read it as 10000, compared that with the line
# count and reported a number past the end of a file it had never counted.
_CITE_LIM = [int(x) for p in CONTRACT["forbidden_in_location_labels"]["patterns"]
             for x in re.findall(r"\\d\{(\d+),\}", p["regex"])]
CITE_NUM = re.compile(r"(\d{%d,})" % (min(_CITE_LIM) if _CITE_LIM else 1))

# ABAP constructs usable as location anchors, ordered so the more specific
# pattern wins: CLASS x IMPLEMENTATION. must beat CLASS x.
ANCHORS = [
    (re.compile(r"^\s*CLASS\s+(\w+)\s+IMPLEMENTATION", re.M), "CLASS {0} IMPLEMENTATION"),
    (re.compile(r"^\s*(?:INTERFACE)\s+(\w+)", re.M), "INTERFACE {0}"),
    (re.compile(r"^\s*CLASS\s+(\w+)", re.M), "CLASS {0}"),
    (re.compile(r"^\s*METHODS?\s+(\w+)", re.M), "METHOD {0}"),
    (re.compile(r"^\s*FORM\s+(\w+)", re.M), "FORM {0}"),
    (re.compile(r"^\s*FUNCTION\s+(\w+)", re.M), "FUNCTION {0}"),
    (re.compile(r"^\s*MODULE\s+(\w+)\s+(INPUT|OUTPUT)", re.M), "MODULE {0} {1}"),
    (re.compile(r"^\s*DEFINE\s+(\w+)", re.M), "DEFINE {0}"),
    (re.compile(r"^\s*PROCEDURE\s+(\w+)", re.M), "PROCEDURE {0}"),
]
