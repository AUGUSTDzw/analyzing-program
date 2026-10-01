REPORT zvendor_notify.

*"----------------------------------------------------------------------
*"* Vendor master maintenance with message class, number range and
*"* table locking. Uses MESSAGE ID / NUMBER as the positive pattern.
*"----------------------------------------------------------------------

TYPES: BEGIN OF ty_vendor,
         lifnr   TYPE lfa1-lifnr,
         name1   TYPE lfa1-name1,
         ort01   TYPE lfa1-ort01,
         waerk   TYPE lfa1-waers,
         eikto   TYPE lfa1-eikto,
         status  TYPE char1,
       END OF ty_vendor.

TYPES ty_vendor_tab TYPE STANDARD TABLE OF ty_vendor WITH EMPTY KEY.

DATA gt_vendor  TYPE ty_vendor_tab.
DATA gs_vendor  TYPE ty_vendor.
DATA gv_locked  TYPE abap_bool.
DATA gv_dummy   TYPE i.

SELECT-OPTIONS s_lifnr FOR gs_vendor-lifnr.

INITIALIZATION.
  SET HANDLER 'ON_HELP_REQUEST'.

AT SELECTION-SCREEN ON HELP-REQUEST.

  MESSAGE ID 'ZVND' TYPE 'I' NUMBER '001'.

START-OF-SELECTION.

  PERFORM lock_records.
  PERFORM read_vendors.
  PERFORM notify_by_email.
  PERFORM release_lock.


FORM lock_records.

  LOOP AT s_lifnr.

    CLEAR gv_locked.

    CALL FUNCTION 'ENQUEUE_ZLFA1'
      EXPORTING
        iv_lifnr         = s_lifnr-low
      IMPORTING
        ev_locked        = gv_locked
      EXCEPTIONS
        conflict_lock    = 1
        OTHERS           = 2.

    IF sy-subrc <> 0.
      MESSAGE ID 'ZVND' TYPE 'E' NUMBER '002' WITH s_lifnr-low.
      CONTINUE.
    ENDIF.

  ENDLOOP.

ENDFORM.                       "lock_records


FORM read_vendors.

  SELECT lifnr name1 ort01 waerk eikto
    FROM lfa1
    INTO TABLE gt_vendor
    WHERE lifnr IN s_lifnr.

  IF gt_vendor IS INITIAL.
    MESSAGE ID 'ZVND' TYPE 'S' NUMBER '003'.
  ENDIF.

  LOOP AT gt_vendor INTO DATA(ls_vendor).

    IF ls_vendor-waerk IS INITIAL.
      MESSAGE ID 'ZVND' TYPE 'W' NUMBER '004' WITH ls_vendor-lifnr.
    ENDIF.

  ENDLOOP.

ENDFORM.                       "read_vendors


FORM notify_by_email.

  DATA lt_recipients TYPE STANDARD TABLE OF adr6-adr_email.
  DATA lv_body       TYPE string.

  CONCATENATE LINES OF lt_recipients INTO lv_body SEPARATED BY space.

  LOOP AT gt_vendor INTO DATA(ls_vendor).
    ls_vendor-status = 'X'.
    MODIFY gt_vendor FROM ls_vendor.
  ENDLOOP.

  IF lv_body IS INITIAL.
    MESSAGE ID 'ZVND' TYPE 'W' NUMBER '005'.
  ENDIF.

ENDFORM.                       "notify_by_email


FORM release_lock.

  LOOP AT s_lifnr.
    CALL FUNCTION 'DEQUEUE_ZLFA1'
      EXPORTING
        iv_lifnr = s_lifnr-low.
  ENDLOOP.

  gv_dummy = 1.

ENDFORM.                       "release_lock"