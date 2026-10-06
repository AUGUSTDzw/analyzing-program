# analyzing-programs v1.0.0 — release manifest

Build time: 2026-10-06 16:03:48
Source commit: `0c829f1aca3138ea1ee428ca9e6d9f89f4383ead` (0c829f1)
Commit subject: release: add v1.0.0 archive (82273 B, sha256 1c47332edd76)

## Contents

17 files, 185232 bytes, packed into one 82273-byte archive.

| Path | Bytes | SHA256 (first 16) |
|---|---|---|
| `analyzing-programs-1.0.0/README.md` | 7892 | `f75a156d01496ec6` |
| `analyzing-programs-1.0.0/SKILL.md` | 14499 | `0dc9f17eb7ce7a90` |
| `analyzing-programs-1.0.0/evals/README.md` | 4250 | `153f7682e808caf9` |
| `analyzing-programs-1.0.0/evals/dialog_zmsa_r_chapter4_8.defects.json` | 4244 | `8165da33645e983b` |
| `analyzing-programs-1.0.0/evals/screen_manager_o01.defects.json` | 3723 | `ca4ff914c9a10459` |
| `analyzing-programs-1.0.0/evals/z_ave_standalone.defects.json` | 13721 | `539c5ac36a2cc277` |
| `analyzing-programs-1.0.0/evals/zbc_show_error_log.defects.json` | 3338 | `8119df7096876e26` |
| `analyzing-programs-1.0.0/evals/zcl_fi_toolkit.defects.json` | 15626 | `387a6f90d6e6ea95` |
| `analyzing-programs-1.0.0/evals/zvend.defects.json` | 9653 | `6ff35bca18f6d70a` |
| `analyzing-programs-1.0.0/references/README.md` | 1868 | `ad18ab72e1d880a9` |
| `analyzing-programs-1.0.0/references/example-report.md` | 35027 | `3bc277a591051b9a` |
| `analyzing-programs-1.0.0/references/large-inputs.md` | 7387 | `dd6d22c0c12c9ebe` |
| `analyzing-programs-1.0.0/schemas/report-contract.json` | 6247 | `2d1e308624b22f1b` |
| `analyzing-programs-1.0.0/scripts/evaluate.py` | 12359 | `d42d36230158bdc2` |
| `analyzing-programs-1.0.0/scripts/report_qc.py` | 24224 | `d91d3a5657863520` |
| `analyzing-programs-1.0.0/tests/test_contract_drift.py` | 6342 | `b4c53172c2050661` |
| `analyzing-programs-1.0.0/tests/test_skill.py` | 14832 | `d65a1cc8d5aaf8e2` |

`analyzing-programs-1.0.0.zip` — 82273 B compressed, 185232 B uncompressed, SHA256 `3e8901fdec579dc0db82c4b77b7233d4aa40efea7b01e5107f40cd29b342568b`,
17 entries, `testzip` clean, no build artifacts.

## Provenance

Git is the only durable store inside the repository, so the files were read from
the commit's blobs directly (`git ls-tree -r` + `git cat-file blob`) rather than
copied from the working tree.

Each extracted file was read back and hashed against its source blob, and each
archive entry was hashed against the same blob.

| Check | Result |
|---|---|
| Extracted files | 17/17 |
| Readback hash == source blob | 17/17 |
| Archive entries == source blob | 17/17 |
| Build artifacts (`*.pyc`, `__pycache__`) | absent from the release |

## Verification (run against the extracted copy)

| Command | Exit | Outcome |
|---|---|---|
| `tests/test_skill.py` | 0 | PASS |
| `tests/test_contract_drift.py` | 0 | PASS |
| `report_qc.py references/example-report.md` | 0 | PASS |
| `evaluate.py tasks --defects zcl_fi_toolkit.defects.json` | 0 | PASS |

## Feature audit

Fidelity-gate markers from the preceding session: 8/8 present.

| File | Marker | |
|---|---|---|
| `SKILL.md` | `abap-fix` | present |
| `references/example-report.md` | `abap-fix` | present |
| `schemas/report-contract.json` | `fix-lang` | present |
| `scripts/report_qc.py` | `def fix_lang_note` | present |
| `scripts/report_qc.py` | `QUOTE_LANG` | present |
| `scripts/report_qc.py` | `FIX_LANG` | present |
| `scripts/report_qc.py` | `def block_head` | present |
| `tests/test_skill.py` | `fence(s) sit inside` | present |

## What is and is not in this release

Included: `SKILL.md`, `README.md`, `schemas/report-contract.json`,
`scripts/evaluate.py`, `scripts/report_qc.py`, `references/` (3 files),
`evals/` (1 README + 6 defect lists), `tests/` (2 scripts).

Deliberately excluded:

- `__pycache__/` and any `.pyc`. Bytecode is a build artifact; it is committed in
  one revision of the repository and has been stripped from the release.
- The development harness scripts named in the documentation
  (`check_evaluate_validation.py`, `check_skill_selfconsistent.py`,
  `build_isolation_variant.py`, `truncation_audit.py`, `evals/judge-defects.json`).
  Destroyed in a deletion incident, not rebuilt, and the documentation no longer
  points at them.
- `iteration-8/` workspace data. Upstream development evidence, not part of the
  skill.

## Known limitations

1. The report gate checks the report's own structure and contract, not its claims
   against the source program. It cannot tell a wrong conclusion from a
   well-structured wrong conclusion. Stated in `README.md`.
2. The `iteration-8` figures in `README.md` were measured against commit
   `b8f84e8`. The shipped skill has never been run end-to-end against that
   harness. Also stated in `README.md`.
3. Repository state on the build host is not stable. Two different commit
   histories were observed at `HEAD`, the object database was replaced wholesale
   and destroyed commits created during the build, and the working tree is
   emptied repeatedly. This release was therefore also written to a location
   outside the repository.

## Checksums

`SHA256SUMS` lists all 17 files plus the archive, one line per path,
relative to this directory. Verify with `sha256sum -c SHA256SUMS` or
`Get-FileHash`.
