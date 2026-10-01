*&---------------------------------------------------------------------*
*& Report        ZSALES_SYNCH
*&---------------------------------------------------------------------*
*& Pulls sales order data from a CDS view and pushes a daily summary
*& to an external REST endpoint.
*&---------------------------------------------------------------------*
REPORT zsales_synch.

TYPES: BEGIN OF ty_order,
         vbeln    TYPE vbeln_va,
         kunnr    TYPE kunnr,
         waerk    TYPE waerk,
         netwr    TYPE netwr,
         menge    TYPE menge,
         wrdat    TYPE wrdat,
       END OF ty_order.

TYPES ty_order_tab TYPE STANDARD TABLE OF ty_order WITH EMPTY KEY.

DATA gt_orders TYPE ty_order_tab.
DATA gv_base_url TYPE string.
DATA gv_json TYPE string.
DATA gv_user  TYPE sy-uname.

SELECTION-SCREEN BEGIN OF BLOCK b.
  PARAMETERS p_url TYPE string LOWER CASE DEFAULT 'https://api.example.com'.
  PARAMETERS p_dryrun AS CHECKBOX DEFAULT 'X'.
SELECTION-SCREEN END OF BLOCK b.

INITIALIZATION.
  gv_base_url = p_url.
  gv_user     = sy-uname.

START-OF-SELECTION.

  PERFORM read_from_cds.
  PERFORM build_payload.
  PERFORM push_to_service.
  PERFORM log_result.


FORM read_from_cds.

  SELECT vbeln kunnr waerk netwr menge wrdat
    FROM z_i_vbak_open
    INTO TABLE gt_orders
    WHERE waerk = 'USD'
      AND wrdat >= '20240101'.

  IF sy-subrc <> 0.
    MESSAGE 'CDS view returned no rows' TYPE 'S'.
  ENDIF.

  WRITE: / 'orders', lines( gt_orders ).

ENDFORM.                       "read_from_cds


FORM build_payload.

  DATA lv_row TYPE string.

  gv_json = '['.

  LOOP AT gt_orders INTO DATA(ls_order).

    lv_row = |{ |"vbeln": "{ ls_order-vbeln }",| &
              |"customer": "{ ls_order-kunnr }",| &
              |"amount": { ls_order-netwr },| &
              |"currency": "{ ls_order-waerk }",| &
              |"date": "{ ls_order-wrdat CONDENSE SPACE }" }|.

    IF sy-tabix > 1.
      gv_json = gv_json && |,|.
    ENDIF.

    gv_json = gv_json && lv_row.

  ENDLOOP.

  gv_json = gv_json && ']'.

ENDFORM.                       "build_payload


FORM push_to_service.

  DATA lo_client  TYPE REF TO if_http_client.
  DATA lv_xstring TYPE xstring.
  DATA lv_status  TYPE i.

  CREATE XSTRING LV_XSTRING DATA GV_JSON.

  cl_http_client=>create_by_url(
    EXPORTING
      url                = gv_base_url
    IMPORTING
      client             = lo_client
    EXCEPTIONS
      argument_not_found = 1
      plugin_not_active  = 2
      OTHERS             = 3 ).

  IF sy-subrc <> 0.
    WRITE: / 'client creation failed', sy-subrc.
    RETURN.
  ENDIF.

  lo_client->request->set_cdata( lv_xstring ).
  lo_client->request->set_content_type( 'application/json' ).

  lo_client->send(
    EXPORTING
      timeout = 3
    EXCEPTIONS
      http_communication_failure = 1
      http_invalid_state         = 2
      http_processing_failed     = 3
      OTHERS                     = 4 ).

  lo_client->receive(
    EXCEPTIONS
      http_communication_failure = 1
      http_invalid_state         = 2
      OTHERS                     = 3 ).

  IF sy-subrc = 0.
    lv_status = lo_client->response->get_status( ).
  ENDIF.

  IF lv_status >= 400.
    MESSAGE 'Remote service rejected the payload' TYPE 'S'.
  ENDIF.

  lo_client->close( ).

ENDFORM.                       "push_to_service


FORM log_result.

  IF p_dryrun IS INITIAL.
    WRITE: / 'posted to', gv_base_url, 'by', gv_user.
  ENDIF.

ENDFORM.                       "log_result