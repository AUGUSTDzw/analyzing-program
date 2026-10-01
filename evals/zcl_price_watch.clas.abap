*&---------------------------------------------------------------------*
*& Report        ZCL_PRICE_WATCH
*&---------------------------------------------------------------------*
*& Price watch: a local publisher raises events when a watched material
*& drops below a threshold; one subscriber class reacts.
*&---------------------------------------------------------------------*
CLASS-POOL zcl_price_watch.

*"* use this source for any type of program (pool)

PUBLIC
FINAL
CREATE PUBLIC.

  PUBLIC SECTION.

    CLASS-EVENTS price_dropped
      EXPORTING iv_matnr TYPE mara-matnr
                iv_netpr TYPE marc-netpr.

    METHODS constructor
      IMPORTING iv_threshold TYPE marc-netpr.

    METHODS watch
      IMPORTING iv_matnr TYPE mara-matnr.

    METHODS forget
      IMPORTING iv_matnr TYPE mara-matnr.

    METHODS check
      IMPORTING iv_matnr TYPE mara-matnr
                iv_netpr TYPE marc-netpr.

    METHODS count_watched
      RETURNING VALUE(rv_count) TYPE i.

  PRIVATE SECTION.

    DATA mv_threshold TYPE marc-netpr.
    DATA mt_watched   TYPE STANDARD TABLE OF mara-matnr WITH EMPTY KEY.


CLASS lcl_alert DEFINITION FINAL.
  PUBLIC SECTION.
    INTERFACES if_price_listener.
ENDCLASS.


CLASS lcl_alert IMPLEMENTATION.
  METHOD if_price_listener~on_price_dropped.
    WRITE: / 'ALERT: price drop for', iv_matnr.
  ENDMETHOD.                    "if_price_listener~on_price_dropped
ENDCLASS.                       "lcl_alert


CLASS lcl_audit DEFINITION FINAL.
  PUBLIC SECTION.
    INTERFACES if_price_listener.
ENDCLASS.


CLASS lcl_audit IMPLEMENTATION.
  METHOD if_price_listener~on_price_dropped.
    WRITE: / 'AUDIT entry created for', iv_matnr, iv_netpr.
  ENDMETHOD.                    "if_price_listener~on_price_dropped
ENDCLASS.                       "lcl_audit


INTERFACE if_price_listener PUBLIC.
  METHODS on_price_dropped
    FOR EVENT price_dropped OF zcl_price_watch
    IMPORTING iv_matnr TYPE mara-matnr
              iv_netpr TYPE marc-netpr.
ENDINTERFACE.                   "if_price_listener


CLASS zcl_price_watch IMPLEMENTATION.

  METHOD constructor.
    mv_threshold = iv_threshold.

    SET HANDLER lcl_alert=>on_price_dropped.
    SET HANDLER lcl_audit=>on_price_dropped.
  ENDMETHOD.                    "constructor


  METHOD watch.
    IF iv_matnr IS INITIAL.
      RETURN.
    ENDIF.

    APPEND iv_matnr TO mt_watched.
  ENDMETHOD.                    "watch


  METHOD forget.
    DELETE mt_watched WHERE table_line = iv_matnr.
  ENDMETHOD.                    "forget


  METHOD check.
    READ TABLE mt_watched WITH TABLE KEY table_line = iv_matnr.
    IF sy-subrc <> 0.
      RETURN.
    ENDIF.

    IF iv_netpr < mv_threshold.
      RAISE EVENT price_dropped
        EXPORTING iv_matnr = iv_matnr
                  iv_netpr = iv_netpr.
    ENDIF.
  ENDMETHOD.                    "check


  METHOD count_watched.
    rv_count = lines( mt_watched ).
  ENDMETHOD.                    "count_watched

ENDCLASS.                       "zcl_price_watch"