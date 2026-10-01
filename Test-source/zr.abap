REPORT zr.

TYPES: BEGIN OF ty_final,
  matnr TYPE mara-matnr,
  maktx TYPE makt-maktx,
  cellcolor TYPE lvc_t_scol,
  END OF ty_final.

TYPES: BEGIN OF ty_mara,
  matnr TYPE mara-matnr,
  END OF ty_mara.

TYPES : BEGIN OF ty_makt,
  matnr TYPE makt-matnr,
  maktx TYPE makt-maktx,
  END OF ty_makt.

DATA: it_final TYPE TABLE OF ty_final,
  wa_final TYPE ty_final,
  it_mara TYPE TABLE OF ty_mara,
  wa_mara TYPE ty_mara,
  it_makt TYPE TABLE OF ty_makt,
  wa_makt TYPE ty_makt,
  matnr TYPE mara-matnr,
  lv_index   TYPE sy-tabix,
  wa_cellcolor TYPE lvc_s_scol, "  for cell color
  wa_layout TYPE slis_layout_alv,
  ref1 TYPE REF TO cl_gui_alv_grid, " to capture changes in alv
  it_zfinal TYPE TABLE OF ty_final, "temproary final internal table
  wa_zfinal TYPE ty_final,
  wa_zzfinal TYPE ty_makt, "  temproary work area 
*to move changed values in alv
  it_fieldcat TYPE slis_t_fieldcat_alv, "  for Alv
  wa_fieldcat TYPE slis_fieldcat_alv.


SELECTION-SCREEN BEGIN OF BLOCK a.
  SELECT-OPTIONS: s_matnr FOR matnr.
  SELECTION-SCREEN END OF BLOCK a.

START-OF-SELECTION.
      PERFORM : getdata.
      PERFORM: f_build_layout .
      PERFORM: dispaly.

FORM getdata .

    SELECT matnr FROM mara INTO TABLE it_mara WHERE matnr IN S_matnr.
    IF it_mara IS NOT INITIAL.
    SELECT matnr maktx FROM makt INTO TABLE it_makt
    FOR ALL ENTRIES IN it_mara WHERE matnr = it_mara-matnr AND spras = 'EN'.
    ENDIF.
* moving values from temproary internal table to final internal table
    LOOP AT it_mara INTO wa_mara.
    wa_final-matnr = wa_mara-matnr.
    READ TABLE it_makt INTO wa_makt WITH KEY matnr = wa_mara-matnr.
    wa_final-maktx = wa_makt-maktx.
    wa_final-matnr = wa_mara-matnr.
    APPEND wa_final TO it_final.
    ENDLOOP.

IF it_final IS INITIAL.
  MESSAGE 'no values' TYPE 'I'.
  LEAVE TO CURRENT TRANSACTION.
  ENDIF.
*color code for the cells based on condition
  LOOP AT it_FINAL INTO wa_FINAL.
    lv_index = sy-tabix.
    IF  wa_final-matnr+0(1) = '0'.
    wa_cellcolor-fname = 'MATNR'.
    wa_cellcolor-color-col = 6.
    wa_cellcolor-color-int = '1'.
    wa_cellcolor-color-inv = '0'.
    APPEND wa_cellcolor TO wa_FINAL-cellcolor.
    CLEAR: wa_cellcolor.
    MODIFY it_final FROM wa_final INDEX lv_index TRANSPORTING cellcolor.
    CLEAR wa_final.
      ENDIF.
   ENDLOOP.
ENDFORM.
END-OF-SELECTION.

CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      i_callback_program                = sy-repid
      i_callback_pf_status_set          = 'PF_STATUS'
      i_callback_user_command           = 'USER_COMMAND'
      is_layout                         = wa_layout
      it_fieldcat                       = it_fieldcat
     TABLES
       t_outtab                          = it_final
    EXCEPTIONS
      PROGRAM_ERROR                     = 1
      OTHERS                            = 2
             .
   IF sy-subrc <> 0.
* Implement suitable error handling here
   ENDIF.
*appending values to fieldcatalogue.
FORM dispaly .

  wa_fieldcat-tabname = 'IT_FINAL'.
  wa_fieldcat-fieldname = 'MATNR'.
  wa_fieldcat-seltext_m = 'Material'.

  APPEND wa_fieldcat TO it_fieldcat.
  CLEAR: wa_fieldcat.

  wa_fieldcat-tabname = 'IT_FINAL'.
  wa_fieldcat-fieldname = 'MAKTX'.
  wa_fieldcat-seltext_m = 'Description'.
  wa_fieldcat-edit ='X'.

  APPEND wa_fieldcat TO it_fieldcat.
  CLEAR: wa_fieldcat.
*appending values form final internal table to
* temproary final table for data comparision
  it_zfinal[] = it_final[].

ENDFORM.

*syntax for declarin usercommand
FORM user_command USING p_ucomm TYPE sy-ucomm
                        p_selfield TYPE slis_selfield.
CASE p_ucomm.
    WHEN '&IC1'.
      LOOP AT it_final INTO wa_final.
      READ TABLE it_final INTO wa_final WITH KEY matnr = wa_final-matnr.
      WRITE: / wa_final-matnr.
      ENDLOOP.

    WHEN 'SAVE'.

      CALL FUNCTION 'GET_GLOBALS_FROM_SLVC_FULLSCR' "Capturing changes in ALV
      IMPORTING
        e_grid = ref1.
      CALL METHOD ref1->check_changed_data.
*moving changed value into ztable on saving
LOOP AT it_final INTO wa_final.
  READ TABLE it_zfinal INTO wa_zfinal WITH KEY matnr = wa_final-matnr.
  IF wa_zfinal-matnr = wa_final-matnr AND wa_zfinal-maktx NE wa_final-maktx.
    MOVE-CORRESPONDING wa_final TO wa_zzfinal.
    MODIFY zfinal FROM wa_zzfinal.
  ENDIF.
ENDLOOP.
    CLEAR: wa_final,wa_zfinal, wa_zzfinal.
ENDCASE.
ENDFORM.
*se41 create, generate, activate the buttons and assing it.
FORM pf_status USING rt_extab TYPE slis_t_extab.
  SET PF-STATUS 'ZPF_STATUS'.
ENDFORM.
*color code building for FM
FORM f_build_layout .
  CLEAR wa_layout.
  wa_layout-colwidth_optimize = 'X'.
  wa_layout-coltab_fieldname = 'CELLCOLOR'.

ENDFORM.