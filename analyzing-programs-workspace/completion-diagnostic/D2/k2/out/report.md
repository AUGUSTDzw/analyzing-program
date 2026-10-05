# ZCL_ABAPGIT_OBJECTS_PROGRAM — Method Inventory

| Method | Start | End | Description |
|---|---|---|---|
| add_tpool | 283 | 298 | Converts textpool rows into the abapGit tpool structure, splitting `S` (split) entries into separate `split`/`entry` fields. |
| auto_correct_cua_adm | 301 | 338 | Repairs a missing or invalid CUA ADM header by copying `actcode`/`mencode`/`pfkcode` from the first act/men/pfk entries (issue #1807). |
| create_vari | 341 | 374 | Creates a saved report variant via `RS_CREATE_VARIANT_255` and `RS_CHANGE_CREATED_VARIANT_255`, raising on failure. |
| delete_vari | 377 | 403 | Deletes a report variant via `RS_VARIANT_DELETE`, retrying without the newer suppress parameters on older releases. |
| deserialize_cua | 406 | 475 | Writes CUA data back for a program via `RS_CUA_INTERNAL_WRITE`, auto-correcting ADM and queuing CUAD activation. |
| deserialize_dynpros | 478 | 634 | Re-imports dynpro screens via `RPY_DYNPRO_INSERT` (or native insert) and deletes screens no longer present in the payload. |
| deserialize_exit_include | 637 | 665 | Deserializes exit/upgrade-include programs by updating an existing active version or inserting a new one. |
| deserialize_program | 668 | 717 | Main deserialization entry point: registers a transport object, then inserts or updates the program and queues REPS activation. |
| deserialize_textpool | 720 | 768 | Inserts or deletes a program textpool for a given language, flagging main-language entries for activation. |
| deserialize_varis | 771 | 854 | Reconciles stored variants against local ones, recreating changed variants and deleting removed ones while preserving protection flags. |
| get_program_title | 857 | 875 | Reads the program title from the textpool row with `id = 'R'`, clearing the shared `TTAB` buffer to work around an SAP bug. |
| get_varis_for_report | 878 | 906 | Lists saved report variants via `RS_ALL_VARIANTS_4_1_REPORT`, filtering out system variants matching `SAP&*`/`CUS&*`. |
| get_vari_data | 909 | 975 | Reads a variant's technical data, contents, objects and translations for serialization. |
| get_vari_screens | 978 | 997 | Fetches the dynpro screens assigned to a variant via `RS_GET_SCREENS_4_1_VARIANT`. |
| insert_program | 1000 | 1063 | Creates a new program via `RPY_PROGRAM_INSERT`, falling back to a two-state insert path for types the standard FM rejects (e.g. FUGR). |
| is_any_dynpro_locked | 1066 | 1087 | Checks whether any dynpro of the program has an ESCRp lock entry. |
| is_cua_locked | 1090 | 1101 | Checks for an ESCUAPAINT lock entry matching the program's CUA object key. |
| is_exit_include | 1104 | 1108 | Returns true when the program name matches the `LX*`/`SAPLX*` exit-include patterns. |
| is_text_locked | 1111 | 1120 | Checks for an EABAPTEXTE lock entry covering the program's textpool. |
| read_tpool | 1123 | 1139 | Inverse of `add_tpool` — merges `S` split entries back into the plain textpool table. |
| serialize_cua | 1142 | 1171 | Reads CUA data for a program via `RS_CUA_INTERNAL_FETCH` and returns it as a `ty_cua` structure. |
| serialize_dynpros | 1174 | 1308 | Reads all non-generated dynpro screens, stores flow logic as separate ABAP files, and normalizes fields/containers for XML output. |
| serialize_program | 1311 | 1418 | Main serialization entry point: reads source, progdir, dynpros, CUA, variants and textpool into XML plus ABAP source files. |
| serialize_varis | 1421 | 1454 | Collects all saved variants of a report (data, screens, objects, texts) into the `ty_vari_tt` structure for serialization. |
| set_vari_protection | 1457 | 1480 | Toggles the `protected` flag on a variant's `varid` row, returning the previous value. |
| strip_generation_comments | 1483 | 1536 | Strips generated header comment blocks from FUGR main-program source and MV FM include sources. |
| uncondense_flow | 1539 | 1557 | Expands condensed dynpro flow logic by re-applying per-line indentation shifts. |
| update_program | 1560 | 1596 | Updates an existing program's source and title via `RPY_INCLUDE_UPDATE`, mapping specific EU errors to exceptions. |
