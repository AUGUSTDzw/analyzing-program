REPORT zmodern_lo.

*"----------------------------------------------------------------------
*"* Stock overview written with ABAP 7.40+ syntax: inline declarations,
*"* table expressions, string templates, FILTER / REDUCE / VALUE #.
*"----------------------------------------------------------------------

TYPES: BEGIN OF ty_stock,
         matnr TYPE mara-matnr,
         maktx TYPE makt-maktx,
         werks TYPE mard-werks,
         lgort TYPE mard-lgort,
         mstock TYPE mard-mstock,
         ntgew TYPE mara-ntgew,
         brgew TYPE mara-brgew,
         waers TYPE mara-waers,
       END OF ty_stock.

TYPES ty_stock_tab TYPE STANDARD TABLE OF ty_stock WITH EMPTY KEY.

DATA gt_stock   TYPE ty_stock_tab.
DATA gv_min     TYPE p DECIMALS 2.

SELECT-OPTIONS s_matnr FOR gt_stock-matnr.

START-OF-SELECTION.

  DATA(lv_waers) = 'USD'.

  PERFORM read_stock.
  PERFORM filter_and_aggregate.
  PERFORM report_output.


FORM read_stock.

  SELECT matnr werks lgort mstock ntgew brgew
    FROM mard
    INTO TABLE @gt_stock
    WHERE matnr IN @s_matnr
      AND werks  = 'A100'.

  DATA(lv_rows) = lines( gt_stock ).
  DATA(lv_first) = CONV i( REDUCE i( INIT m = 0
                                     FOR row IN gt_stock
                                     NEXT m = m + 1 ) ).

ENDFORM.                       "read_stock


FORM filter_and_aggregate.

  DATA(lv_missing) = REDUCE i( INIT sum = 0
                               FOR row IN gt_stock
                               NEXT sum = sum + COND i(
                                 WHEN row-mstock IS INITIAL THEN 1 ELSE 0 ) ).

  gt_stock = FILTER ty_stock_tab( gt_stock
                                  WHERE ntgew > brgew ).

  DATA(lv_total) = REDUCE p( INIT sum = 0
                             FOR row IN gt_stock
                             NEXT sum = sum + row-mstock ).

  WRITE: / lv_missing, lv_total.

ENDFORM.                       "filter_and_aggregate


FORM report_output.

  DATA(lv_header) = |Stock overview { lines( gt_stock ) } rows|
                    && | total qty { lv_total  W = 12 }|.

  WRITE: / lv_header.

  LOOP AT gt_stock INTO DATA(ls_row).

    WRITE: / |{ ls_row-matnr ALPHA = OUT } qty { ls_row-mstock W = 10 }|.

    IF ls_row-mstock > 0 AND ls_row-mstock <> gv_min.
      MESSAGE |Material { ls_row-matnr } below minimum| TYPE 'S'.
    ENDIF.

  ENDLOOP.

  DATA(lt_good) = VALUE ty_stock_tab(
    FOR row IN gt_stock
    WHERE ( mstock > 0 )
    ( matnr  = row-matnr
      maktx  = row-maktx
      mstock = row-mstock
      waers  = lv_waers ) ).

  WRITE: / lt_good.

ENDFORM.                       "report_output