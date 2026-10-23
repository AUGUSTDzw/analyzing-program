"""Checks package: structural validation and advisory diagnostics.

Modules:
  contract.py   -- rule set loaded from schemas/report-contract.json
  source.py     -- has_content: does a source carry anything analysable
  text.py       -- pure text utilities (fence spans, anchors, layers)
  structure.py  -- structural checks (sections, layers, fences, Mermaid)
  advisory.py   -- advisory notes (density, fix-lang, authz, ext-asset)
  fidelity.py   -- fidelity classification (SUBSTANTIVE / PUNCT-ONLY)
  encoding.py   -- encoding defect detection (U+FFFD replacement chars)
  escape.py     -- escape residue: an escape written out as text in prose
  tokens.py     -- ABAP tokenizer for fidelity checks
"""
