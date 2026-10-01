*&---------------------------------------------------------------------*
*& Report        ZSLAV_PO_LIST
*&---------------------------------------------------------------------*
*& OO ALV (CL_SALV_TABLE) purchase order overview with totals and
*& double-click drill-down into order items.
*&---------------------------------------------------------------------*
REPORT zsalv_po_list.

TYPES: BEGIN OF ty_po,
         ebeln   TYPE ekko-ebeln,
         lifnr   TYPE ekko-lifnr,
         bedat   TYPE ekko-bedat,
         waers   TYPE ekko-waers,
         netwr   TYPE ekko-netwr,
         menge   TYPE ekko-kumqw,
         ebeln_t TYPE ekko-ebeln_txt,
       END OF ty_po.

TYPES: BEGIN OF ty_item,
         ebeln TYPE ekpo-ebeln,
         posnr TYPE ekpo-posnr,
         matnr TYPE ekpo-matnr,
         menge TYPE ekpo-menge,
         netwr TYPE ekpo-netwr,
       END OF ty_item.

CLASS lcl_event_handler DEFINITION FINAL.
  PUBLIC SECTION.
    METHODS on_double_click
      FOR EVENT double_click OF cl_salv_events_table
      IMPORTING row column.
    METHODS on_link_click
      FOR EVENT link_click OF cl_salv_events_table
      IMPORTING row column.
  PRIVATE SECTION.
    DATA mv_show TYPE REF TO cl_salv_table.
ENDCLASS.


CLASS lcl_handler DEFINITION.
  PUBLIC SECTION.
    METHODS get_data.
    METHODS display_alv.
    METHODS show_items
      IMPORTING iv_ebeln TYPE ekko-ebeln.

  PRIVATE SECTION.
    DATA mt_data TYPE ty_po.
ENDCLASS.


DATA gt_po   TYPE STANDARD TABLE OF ty_po WITH EMPTY KEY.
DATA gt_item TYPE STANDARD TABLE OF ty_item WITH EMPTY KEY.
DATA go_handler  TYPE REF TO lcl_event_handler.
DATA go_report   TYPE REF TO lcl_handler.

SELECT-OPTIONS s_ebeln FOR gs_key-ebeln.
DATA gs_key TYPE ty_po.

INITIALIZATION.
  gs_key-ebeln = '0000000001'.

START-OF-SELECTION.

  CREATE OBJECT go_report.
  go_report->get_data( ).
  go_report->display_alv( ).


CLASS lcl_handler IMPLEMENTATION.

  METHOD get_data.

    SELECT ebeln lifnr bedat waers netwr kumvw AS menge
      FROM ekko
      INTO TABLE mt_data
      WHERE ebeln IN s_ebeln.

    LOOP AT mt_data INTO DATA(ls_row).
      ls_row-ebeln_t = |Order { ls_row-ebeln }|.
      MODIFY mt_data FROM ls_row.
    ENDLOOP.

    SELECT ebeln bedat waers netwr
      INTO TABLE @gt_po
      FROM ekko
      WHERE ebeln IN s_ebeln
        AND waers = 'EUR'.

    WRITE: / 'loaded', lines( gt_po ).

  ENDMETHOD.                    "get_data


  METHOD display_alv.

    DATA lo_alv     TYPE REF TO cl_salv_table.
    DATA lo_cols    TYPE REF TO cl_salv_columns_table.
    DATA lo_col     TYPE REF TO cl_salv_column.
    DATA lo_events  TYPE REF TO cl_salv_events_table.
    DATA lo_aggr    TYPE REF TO cl_salv_aggregations.
    DATA lo_layout  TYPE REF TO cl_salv_layout.
    DATA lo_disp    TYPE REF TO cl_salv_display_settings.

    TRY.
        cl_salv_table=>factory(
          IMPORTING r_salv_table = lo_alv
          CHANGING  t_table      = gt_po ).
      CATCH cx_salv_msg.
        RETURN.
    ENDTRY.

    lo_aggr = lo_alv->get_aggregations( ).
    TRY.
        lo_aggr->add_aggregation(
          EXPORTING  columnname  = 'NETWR'
                     aggregation = if_salv_c_aggregation=>total ).
      CATCH cx_salv_data_error.
      CATCH cx_salv_not_found.
    ENDTRY.

    lo_layout = lo_alv->get_layout( ).
    lo_layout->set_key( VALUE #( report = sy-repid ) ).
    lo_layout->set_default( abap_true ).
    lo_layout->set_save_restriction( if_salv_c_layout=>restrict_none ).

    lo_disp = lo_alv->get_display_settings( ).
    lo_disp->set_striped_pattern( abap_true ).

    lo_cols = lo_alv->get_columns( ).
    lo_col ?= lo_cols->get_column( 'EBELN' ).
    lo_col->set_long_text( 'Purchase Order' ).
    lo_col ?= lo_cols->get_column( 'NETWR' ).
    lo_col->set_cell_type( if_salv_c_cell_type=>numeric ).

    CREATE OBJECT go_handler.
    go_handler->mv_show = lo_alv.
    lo_events = lo_alv->get_event( ).
    SET HANDLER go_handler->on_double_click FOR lo_events.
    SET HANDLER go_handler->on_link_click   FOR lo_events.

    lo_alv->display( ).

  ENDMETHOD.                    "display_alv


  METHOD show_items.

    SELECT ebeln posnr matnr menge netwr
      FROM ekpo
      INTO TABLE gt_item
      WHERE ebeln = iv_ebeln.

  ENDMETHOD.                    "show_items

ENDCLASS.                       "lcl_handler


CLASS lcl_event_handler IMPLEMENTATION.

  METHOD on_double_click.

    DATA lo_popup TYPE REF TO cl_salv_table.

    READ TABLE gt_po INTO DATA(ls_po) INDEX row.
    IF sy-subrc <> 0.
      RETURN.
    ENDIF.

    go_report->show_items( iv_ebeln = ls_po-ebeln ).

    TRY.
        cl_salv_table=>factory(
          EXPORTING list_display = if_salv_c_bool_sap=>false
          IMPORTING r_salv_table  = lo_popup
          CHANGING  t_table       = gt_item ).
      CATCH cx_salv_msg.
    ENDTRY.

    lo_popup->display( ).

  ENDMETHOD.                    "on_double_click


  METHOD on_link_click.

    READ TABLE gt_po INTO DATA(ls_po) INDEX row.
    WRITE: / 'clicked', ls_po-ebeln, column.

  ENDMETHOD.                    "on_link_click

ENDCLASS.                       "lcl_event_handler