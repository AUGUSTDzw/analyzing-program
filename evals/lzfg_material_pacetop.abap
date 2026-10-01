*&---------------------------------------------------------------------*
*& Report        LZFG_MATERIAL_PACETOP
*&---------------------------------------------------------------------*
*& Global data of function group ZFG_MATERIAL_PRICE
*&---------------------------------------------------------------------*

TYPES: BEGIN OF ty_price_row,
         matnr   TYPE mara-matnr,
         werks   TYPE marc-werks,
         lgort   TYPE marc-lgort,
         eina    TYPE mara-eina,
         brgew   TYPE mara-brgew,
         ntgew   TYPE mara-ntgew,
         netpr   TYPE marc-netpr,
         waers   TYPE marc-waers,
         eifn    TYPE marc-eifn,
       END OF ty_price_row.

TYPES ty_price_rows TYPE STANDARD TABLE OF ty_price_row WITH EMPTY KEY.

DATA: gt_cache    TYPE ty_price_rows,
      gv_run_date TYPE datum,
      gv_user     TYPE sy-uname,
      gv_language TYPE sy-langu.

CONSTANTS gc_weight_tol TYPE p DECIMALS 4 VALUE '0.5'.
CONSTANTS gc_cap_currency TYPE c LENGTH 3 VALUE 'USD'.