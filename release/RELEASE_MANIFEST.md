# analyzing-programs v1.0.0 — release manifest

Build time: 2026-10-06 15:55:47
Source commit: `e3f3c429ffb682d3260370dbf227ea178e8564b9` (e3f3c42)
Commit subject: Docs point at shipped files: five references named scripts lost in the deletion incident, plus four stale counts

## Contents

17 files, 185232 bytes, packed into one 82279-byte archive.

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

``analyzing-programs-1.0.0.zip` — 82273 B compressed, 185232 B uncompressed, SHA256 `78013fc9379f1c9bbe811f219d556cac3fbd8b3d74949a5c07a899c27c9529d1`,
17 entries, `testzip` clean, no build artifacts.

## How the archive was produced

Git is the only durable store on this host. The release was built by reading the
blobs of the commit directly (`git ls-tree -r` + `git cat-file blob`) and writing
them out rather than copying the working tree, which is repeatedly emptied by an
external process and can lose a file within seconds of it being written.

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

Markers from the fidelity-gate work of the preceding session: 8/8
present in this release.

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
  this repository and has been stripped from the release.
- The development harness scripts named in the documentation
  (`check_evaluate_validation.py`, `check_skill_selfconsistent.py`,
  `build_isolation_variant.py`, `truncation_audit.py`, `evals/judge-defects.json`).
  They were destroyed in a deletion incident, are not rebuilt, and the
  documentation no longer points at them.
- `iteration-8/` workspace data. Upstream development evidence, not part of the
  skill.

## Known limitations

1. The report gate checks the report's own structure and contract, not its claims
   against the source program. It cannot tell a wrong conclusion from a
   well-structured wrong conclusion. Stated in `README.md`.
2. The `iteration-8` figures in `README.md` were measured against commit
   `b8f84e8`. The shipped skill has never been run end-to-end against that
   harness. Also stated in `README.md`.
3. Repository state on this host is not stable. Two different commit histories
   have been observed at `HEAD`, and revisions created during the preceding
   session disappeared from the object database entirely. This manifest records
   the commit the release was cut from so provenance can be checked
   independently.

## Checksums

`SHA256SUMS` lists all 17 files plus the archive, one line per path,
relative to this directory. Verify with `sha256sum -c SHA256SUMS` or
`Get-FileHash`.
