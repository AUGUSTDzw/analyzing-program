# Planted defects in eval fixtures

Authored for this benchmark (not copied from any system or third-party source);
syntax and structure are grounded in SAP Help / SAP Community patterns for
`CL_GUI_ALV_GRID`, function groups and BAPI calls. Each fixture deliberately
contains realistic defects so the **content-type assertions** (A14–A18 in
`grade_v2.py`) have something to detect. A report that scores well on format
assertions but misses all of these is a report that is well-formatted and
technically wrong — which is exactly the failure mode the old benchmark could
not see.

| Fixture | Planted defect | Target assertion |
|---|---|---|
| `zcl_stock_check.clas.abap` | `collect_stock` builds a SQL string then never executes it; the real `SELECT` ignores `it_matnr` → FAE driver never used, filter silently ignored | A18 (side-effect / intent) |
| | `enrich_text`: `FOR ALL ENTRIES IN ct_stock` with **no** `IS INITIAL` guard | A15 |
| | `enrich_text`: `READ TABLE lt_text … ` with **no** `sy-subrc` check → stale `maktx` leaks across rows | A14 |
| | `enrich_text`: `spras = 'ZH'` hardcoded instead of `sy-langu` | A16 |
| | `calc_unit_weight` divides by `MARA-EINA` (包装单位, 一个 EA 的数量) and labels the result unit weight; denominator semantics ≠ numerator semantics | A17 |
| | `build_fieldcat` labels `MARA-NTGEW` (**净**重) as `Gross Weight (kg)` — net/gross mismatch | A17 |
| | `check_capacity`: `SELECT SINGLE mard-mvbeln INTO @lv_slots` — `MVBELN` is a document number, not a capacity slot | A17 |
| | `check_capacity` caps stock by silently **overwriting** `mstock` with the slot count | A18 |
| | `display_alv`: `set_table_for_first_display` exceptions swallowed into a local `lv_ok` that is never used; `lt_stock` is empty (collect never wired to display) | A18 |
| | `on_double_click`: `READ TABLE mt_stock INTO ms_stock` — neither `mt_stock` nor `ms_stock` is declared anywhere | A14 / A18 |
| | `set_cell_styles` strikes out every `MSTOCK` cell unconditionally | A18 |
| **9 methods** | A13 requires all 9 `METHOD` names to appear in the report | A13 |
| `zfg_material_price.fg.abap`<br>`lzfg_material_pacetop.abap`<br>`lzfg_material_pacu01.abap` | `z_update_net_price`: `MODIFY marc` + `UPDATE mard` with **no** `COMMIT WORK` and **no** `ROLLBACK` path | A18 |
| | `lv_weight = ls_row-brgew / ls_row-eina` — gross weight per order unit used where unit **net** weight is meant | A17 |
| | `ls_row-waers = gc_cap_currency` where `gc_cap_currency = 'USD'` — currency forced to a literal constant | A16 |
| | `READ TABLE gr_weight`-equivalent: `SELECT SINGLE * FROM marc INTO @ls_row` with no `sy-subrc` check | A14 |
| | `normalise_uom( is_row = ls_row-waers )` — passes a **currency** field into a unit-of-measure parameter | A17 |
| | `z_read_price_rows`: `FOR ALL ENTRIES IN it_rows` with no empty guard; `spras = '1'` hardcoded | A15 / A16 |
| | `RAISE EXCEPTION TYPE cx_sy_no_data` — CX_SY_NO_DATA is not a valid exception class (it is a data object); will not compile | A18 |
| | `APPEND LINES OF it_rows TO gt_cache` writes shared function-group memory with no invalidation | A18 |
| | `lv_count = lines( it_rows )` while an RFC caller receives `it_rows` **by reference** via `TABLES` | A18 |
| **2 FMs + 1 local class** | A13 requires all to be covered | A13 |
| `zreport_bapi_upload.abap` | `post_via_bapi` loops `gt_return` and only `WRITE`s it — **`BAPI_MATERIAL_MAINTAIN` errors are never acted on** | A18 |
| | No `BAPI_TRANSACTION_COMMIT` / `BAPI_TRANSACTION_ROLLBACK` anywhere | A18 |
| | `read_changes`: `FOR ALL ENTRIES IN gt_change` with no empty guard | A15 |
| | `read_changes`: `READ TABLE gr_weight … ` with no `sy-subrc` | A14 |
| | `ls_chg-netpr = ls_chg-netpr * ls_w-brgew` — **price** (per unit, currency) multiplied by **gross weight** (per EA, kg) → unit-mismatch currency value | A17 |
| | `waers` never filtered; currency taken from the read row but nothing validates it | A16 |
| | `replicate_remote`: `CALL FUNCTION … EXCEPTIONS` result (`sy-subrc`) never checked | A18 |
| | `p_dryrun` branch skips the BAPI call entirely, yet the following loop still reports every row as "uploaded" | A18 |
| **4 FORMs** | A13 requires all 4 to be covered | A13 |

## Notes on fairness

- Every defect is reachable by reading the code. None require cross-file
  archaeology beyond the declared includes, and the includes are shipped
  together as one fixture group.
- A13's trigger is computed from the source (all `METHOD … .` and `FORM … .`
  names), so a report that omits one method or FORM fails mechanically. This is
  a **coverage** assertion, not a quality assertion — it can be satisfied by
  name-dropping, so it should be read alongside the content assertions.
- A15/A16/A17/A18 are **keyword-presence** assertions. They can be satisfied
  by writing the words without understanding the defect. They are therefore a
  floor, not a ceiling: passing them does not mean the analysis is correct, and
  the benchmark should not be read as claiming otherwise.