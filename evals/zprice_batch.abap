REPORT zprice_batch.

*"----------------------------------------------------------------------
*"* Nightly price recalculation. Runs both interactively and as a
*"* background job — detects which, then behaves accordingly.
*"----------------------------------------------------------------------

TYPES: BEGIN OF ty_job,
         matnr   TYPE mara-matnr,
         werks   TYPE marc-werks,
         netpr   TYPE marc-netpr,
         waers   TYPE marc-waers,
         eintr   TYPE marc-eintr,
         datnr   TYPE marc-datnr,
         status  TYPE char1,
       END OF ty_job.

TYPES ty_job_tab TYPE STANDARD TABLE OF ty_job WITH EMPTY KEY.

DATA gt_jobs   TYPE ty_job_tab.
DATA gv_run    TYPE i.
DATA gv_ok     TYPE i.
DATA gv_failed TYPE i.
DATA gv_batch  TYPE abap_bool.
DATA gv_commit TYPE i.

SELECTION-SCREEN BEGIN OF BLOCK b.
  SELECT-OPTIONS s_matnr FOR gt_jobs-matnr.
  PARAMETERS p_test AS CHECKBOX.
  PARAMETERS p_commit AS CHECKBOX.
SELECTION-SCREEN END OF BLOCK b.

INITIALIZATION.
  gv_run = 1.

START-OF-SELECTION.

  IF sy-batch = 'X'.
    gv_batch = abap_true.
  ENDIF.

  PERFORM read_prices.
  PERFORM recalculate.
  PERFORM finalize.


FORM read_prices.

  SELECT matnr werks netpr waers eintr datnr
    FROM marc
    INTO TABLE gt_jobs
    WHERE matnr IN s_matnr
      AND waers <> ' '.

  IF gt_jobs IS INITIAL.
    MESSAGE 'No price records found' TYPE 'S'.
    LEAVE TO CURRENT TRANSACTION.
  ENDIF.

ENDFORM.                       "read_prices


FORM recalculate.

  DATA lv_factor TYPE p DECIMALS 4.

  LOOP AT gt_jobs INTO DATA(ls_job).

    gv_run = gv_run + 1.

    lv_factor = COND #( WHEN sy-batch = 'X' THEN 1.02 ELSE 1.05 ).

    ls_job-netpr  = ls_job-netpr * lv_factor.
    ls_job-status = 'X'.

    MODIFY gt_jobs FROM ls_job.

    IF p_test IS INITIAL.
      MODIFY marc FROM ls_job.
      gv_ok = gv_ok + 1.
    ELSE.
      gv_failed = gv_failed + 1.
    ENDIF.

  ENDLOOP.

  WRITE: / 'run', gv_run, 'ok', gv_ok, 'failed', gv_failed.

ENDFORM.                       "recalculate


FORM finalize.

  IF p_test EQ 'X'.
    MESSAGE 'Test mode - no data written' TYPE 'S'.
    RETURN.
  ENDIF.

  IF p_commit EQ 'X'.
    COMMIT WORK.
    WRITE: / 'committed'.
  ENDIF.

  IF gv_batch EQ abap_true.
    WRITE: / 'batch run finished'.
  ENDIF.

ENDFORM.                       "finalize