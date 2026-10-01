REPORT zmmr_perf_eval_vend.


"Types Declaration
TYPES:BEGIN OF t_disp,
   lifnr TYPE lifnr,
   name1 TYPE name1_gp,
   bedat TYPE bedat,
   rfq  TYPE I ,
   quot TYPE I ,
   po   TYPE I ,
   cont TYPE I ,
   sch  TYPE I ,
END OF t_disp,
BEGIN OF t_temp,
   lifnr TYPE lifnr,
  CNT   TYPE I ,
END OF t_temp,
BEGIN OF t_lfa1,
   lifnr TYPE lifnr,
   name1 TYPE name1_gp,
END OF t_lfa1.

"For ALV {
DATA: "it_layout   TYPE lvc_s_layo,
       gr_table TYPE REF TO cl_salv_table,
       gr_functions TYPE REF TO cl_salv_functions,
       gr_columns TYPE REF TO cl_salv_columns_table,
       gr_column TYPE REF TO cl_salv_column_table,
       gr_display TYPE REF TO cl_salv_display_settings,
       lr_grid TYPE REF TO cl_salv_form_layout_grid,
       lr_gridx TYPE REF TO cl_salv_form_layout_grid,
       lr_logo TYPE REF TO cl_salv_form_layout_logo,
       lr_label TYPE REF TO cl_salv_form_label,
       lr_text TYPE REF TO cl_salv_form_text,
       lr_footer TYPE REF TO cl_salv_form_layout_grid,
       ls_color TYPE lvc_s_colo
      .
" For ALV }

DATA: it_disp TYPE TABLE OF t_disp,
       wa_disp LIKE LINE OF it_disp,
       it_temp TYPE TABLE OF t_temp,
       wa_temp LIKE LINE OF it_temp,
       it_lfa1 TYPE TABLE OF t_lfa1,
       wa_lfa1 LIKE LINE OF it_lfa1.

SELECTION-SCREEN BEGIN OF BLOCK b1 WITH FRAME TITLE TEXT- 001.
  SELECT-OPTIONS : s_lifnr FOR wa_disp- lifnr,
   s_bedat FOR wa_disp- bedat.
SELECTION-SCREEN END OF BLOCK b1.

*----------------------------------------------------------------------*
*       CLASS lcl_Perf_Eval DEFINITION
*----------------------------------------------------------------------*
*
*----------------------------------------------------------------------*
CLASS lcl_perf_eval DEFINITION .
  PUBLIC SECTION.
  METHODS: constructor ,
   fill_disp.
  METHODS build_fc.
  METHODS disp_alv.
  METHODS set_tol.
  METHODS end_of_page.

ENDCLASS.                   "lcl_perf_eval DEFINITION


*----------------------------------------------------------------------*
*       CLASS lcl_perf_eval IMPLEMENTATION
*----------------------------------------------------------------------*
*
*----------------------------------------------------------------------*
CLASS lcl_perf_eval IMPLEMENTATION .
  METHOD constructor.
    TRY.
       cl_salv_table=> factory( IMPORTING r_salv_table = gr_table CHANGING t_table = it_disp ). "Calling Factory Obj of Cl_ALV_TABLE
    CATCH cx_salv_msg.
    ENDTRY .

    IF gr_table IS INITIAL .
      MESSAGE TEXT -002 TYPE 'I' DISPLAY LIKE 'E'.
      EXIT .
    ENDIF .
  ENDMETHOD.                   "constructor

  METHOD fill_disp.
    "RFQ
    SELECT a~lifnr COUNT( DISTINCT a~ebeln ) AS rfq FROM ekko AS a
    JOIN ekpo AS b ON a~ ebeln = b ~ebeln
    INTO CORRESPONDING FIELDS OF TABLE it_disp
    WHERE a~lifnr IN s_lifnr AND bedat IN s_bedat
    AND b~loekz NE 'X'
    AND a~bstyp = 'A'
    GROUP BY a~lifnr .

    "WRITE sy-dbcnt.
    "Quot
    SELECT lifnr COUNT( DISTINCT ebeln ) AS CNT FROM ekko
    APPENDING CORRESPONDING FIELDS OF TABLE it_temp
    WHERE lifnr IN s_lifnr AND bedat IN s_bedat
    AND loekz EQ space
    AND ( bstyp = 'A' AND statu = 'A' )
    GROUP BY lifnr.

    LOOP AT it_temp INTO wa_temp .
       wa_disp- lifnr = wa_temp -lifnr.
       wa_disp- quot = wa_temp -CNT.
      MODIFY it_disp FROM wa_disp TRANSPORTING lifnr quot WHERE lifnr = wa_temp-lifnr .
      CLEAR : wa_disp, wa_temp.
    ENDLOOP .

    " PO
    REFRESH it_temp.
    SELECT lifnr COUNT( DISTINCT a~ ebeln ) AS CNT FROM ekko AS a JOIN ekpo AS b ON a~ ebeln = b ~ebeln
    APPENDING CORRESPONDING FIELDS OF TABLE it_temp
    WHERE lifnr IN s_lifnr AND bedat IN s_bedat
    AND b~loekz EQ space
    AND bsart NE 'UB'
    AND ( a~ bstyp = 'F' )
    GROUP BY lifnr.

    LOOP AT it_temp INTO wa_temp .
       wa_disp- lifnr = wa_temp -lifnr.
       wa_disp- po = wa_temp -CNT.
      MODIFY it_disp FROM wa_disp TRANSPORTING lifnr po WHERE lifnr = wa_temp-lifnr .
      IF sy-subrc NE 0.
        APPEND wa_disp TO it_disp .
      ENDIF .
      CLEAR : wa_disp, wa_temp.
    ENDLOOP .

    "Cont. Created
    REFRESH it_temp.
    SELECT lifnr COUNT( DISTINCT a~ ebeln ) AS CNT FROM ekko AS a JOIN ekpo AS b ON a~ ebeln = b ~ebeln
    APPENDING CORRESPONDING FIELDS OF TABLE it_temp
    WHERE lifnr IN s_lifnr AND bedat IN s_bedat
    AND b~loekz EQ space
    AND ( a~ bstyp = 'K' )
    GROUP BY lifnr.

    LOOP AT it_temp INTO wa_temp .
       wa_disp- lifnr = wa_temp -lifnr.
       wa_disp- cont = wa_temp -CNT.
      MODIFY it_disp FROM wa_disp TRANSPORTING lifnr cont WHERE lifnr = wa_temp-lifnr .
      IF sy-subrc NE 0.
        APPEND wa_disp TO it_disp .
      ENDIF .
      CLEAR : wa_disp, wa_temp.
    ENDLOOP .

    "Sch Aggre
    REFRESH it_temp.
    SELECT lifnr COUNT( DISTINCT a~ ebeln ) AS CNT FROM ekko AS a JOIN ekpo AS b ON a~ ebeln = b ~ebeln
    APPENDING CORRESPONDING FIELDS OF TABLE it_temp
    WHERE lifnr IN s_lifnr AND bedat IN s_bedat
    AND b~loekz EQ space
    AND ( a~ bstyp = 'L' )
    GROUP BY lifnr.

    LOOP AT it_temp INTO wa_temp .
       wa_disp- lifnr = wa_temp -lifnr.
       wa_disp- sch = wa_temp -CNT.
      MODIFY it_disp FROM wa_disp TRANSPORTING lifnr sch WHERE lifnr = wa_temp-lifnr .
      IF sy-subrc NE 0.
        APPEND wa_disp TO it_disp .
      ENDIF .
      CLEAR : wa_disp, wa_temp.
    ENDLOOP .

    SELECT lifnr name1 FROM lfa1
    INTO CORRESPONDING FIELDS OF TABLE it_lfa1
    FOR ALL ENTRIES IN it_disp
    WHERE lifnr = it_disp -lifnr.

    LOOP AT it_disp INTO wa_disp .
      READ TABLE it_lfa1 INTO wa_lfa1 WITH KEY lifnr = wa_disp-lifnr .
      IF sy-subrc EQ 0.
         wa_disp- name1 = wa_lfa1 -name1.
        MODIFY it_disp FROM wa_disp TRANSPORTING lifnr name1 WHERE lifnr = wa_disp- lifnr .
      ENDIF .
    ENDLOOP .


    SORT it_disp BY lifnr .

  ENDMETHOD.                   "fill_disp
  METHOD build_fc.

    INCLUDE <color>.
    TRY.
       gr_columns = gr_table->get_columns ( ).
       gr_columns-> set_optimize( abap_true ).
       gr_column ?= gr_columns-> get_column( 'LIFNR' ).
       ls_color- col = 3 .
       gr_column-> set_color( ls_color ).

    CATCH cx_salv_not_found.
    ENDTRY .

    TRY.
       gr_column ?= gr_columns-> get_column( 'NAME1' ).
       gr_column-> set_long_text('Vendor Name' ).
       gr_column-> set_short_text( 'V.Name' ).
       gr_column-> set_medium_text('Vendor Name' ).
       ls_color- col = 3 .
       gr_column-> set_color( ls_color ).
    CATCH cx_salv_not_found.
    ENDTRY .

    TRY.
       gr_column ?= gr_columns-> get_column( 'BEDAT' ).
       gr_column-> set_visible( abap_false ).
       gr_column-> set_technical( VALUE = if_salv_c_bool_sap=> true ).
    CATCH cx_salv_not_found.
    ENDTRY .

    TRY.
       gr_column ?= gr_columns-> get_column( 'RFQ' ).
       gr_column-> set_short_text( 'RFQ' ).
       gr_column-> set_medium_text( 'RFQ Created' ).
    CATCH cx_salv_not_found.
    ENDTRY .

    TRY.
       gr_column ?= gr_columns-> get_column( 'QUOT' ).
       gr_column-> set_short_text( 'Quot.' ).
       gr_column-> set_medium_text( 'Quotation Maintained' ).
    CATCH cx_salv_not_found.
    ENDTRY .
    TRY.
       gr_column ?= gr_columns-> get_column( 'PO' ).
       gr_column-> set_short_text( 'PO Created' ).
    CATCH cx_salv_not_found.
    ENDTRY .

    TRY.
       gr_column ?= gr_columns-> get_column( 'CONT' ).
       gr_column-> set_short_text( 'Cont.' ).
       gr_column-> set_medium_text( 'Contract Created' ).
    CATCH cx_salv_not_found.
    ENDTRY .
    TRY.
       gr_column ?= gr_columns-> get_column( 'SCH' ).
       gr_column-> set_short_text( 'Sch. Crea.' ).
       gr_column-> set_medium_text( 'Sch. Agr. Created' ).
       gr_column-> set_long_text( 'Schedule Agreement Created' ).
    CATCH cx_salv_not_found.
    ENDTRY .

  ENDMETHOD.                   "build_fc

  METHOD disp_alv.

     set_tol( ).
     build_fc( ).
     end_of_page( ).

     gr_functions = gr_table->get_functions ( ).
     gr_functions-> set_all( abap_true ).
     gr_table-> set_top_of_list( lr_logo ).
     gr_table-> set_end_of_list( lr_footer ).
     gr_display = gr_table->get_display_settings ( ).
     gr_display-> set_striped_pattern( cl_salv_display_settings =>true ).


     gr_table-> display( ).

  ENDMETHOD.                   "disp_alv
  METHOD set_tol.
    DATA : lv_text( 30) TYPE C ,
           lv_date TYPE C LENGTH 10.

    CREATE OBJECT lr_grid.

     lr_grid-> create_header_information( row = 1 column = 1
    TEXT = 'MM: Vendor Evaluation'
     tooltip = 'MM: Vendor Evaluation' ).

     lr_gridx = lr_grid->create_grid ( row = 2 column = 1 ).
     lr_label = lr_gridx->create_label ( row = 2 column = 1
    TEXT = 'Vendor No # :' tooltip = 'Vendor #.' ).

    IF s_lifnr IS NOT INITIAL .
       lv_text = s_lifnr-low .
      IF s_lifnr-high IS NOT INITIAL.
        CONCATENATE lv_text ' to ' s_lifnr -high INTO lv_text SEPARATED BY space.
      ENDIF .
    ELSE .
       lv_text = 'Not Provided'.
    ENDIF .
     lr_text = lr_gridx->create_text ( row = 2 column = 2
    TEXT = lv_text tooltip = lv_text ).
    "Vendor
     lr_label = lr_gridx->create_label ( row = 3 column = 1
    TEXT = 'Posting Date:' tooltip = 'Posting Date' ).
    IF s_bedat IS NOT INITIAL .
      WRITE s_bedat-low DD/MM/YYYY TO lv_text .
      IF s_bedat-high IS NOT INITIAL.
        WRITE s_bedat-high DD/MM/YYYY TO lv_date.
        CONCATENATE lv_text ' to ' lv_date INTO lv_text SEPARATED BY space.
      ENDIF .
    ELSE .
       lv_text = 'Not Provided'.
    ENDIF .

     lr_text = lr_gridx->create_text ( row = 3 column = 2
    TEXT = lv_text  tooltip = lv_text ).

     lr_label = lr_gridx->create_label ( row = 4 column = 1
    TEXT = 'Run Date:' tooltip = 'Run Date' ).
     lr_text = lr_gridx->create_text ( row = 4 column = 2
    TEXT = sy- datum tooltip = sy -datum ).

     lr_label = lr_gridx->create_label ( row = 5 column = 1 ).
     lr_label = lr_gridx->create_label ( row = 6 column = 1 ).
     lr_label = lr_gridx->create_label ( row = 7 column = 1 ).
     lr_label = lr_gridx->create_label ( row = 8 column = 1 ).


* Create logo layout, set grid content on left and logo image on right
    CREATE OBJECT lr_logo.
     lr_logo-> set_left_content( lr_grid ).
     lr_logo-> set_right_logo( 'ZCHEM_N_LOGO_SMALL' ). " Image From OAER T.code

  ENDMETHOD.                   "set_Tol

  METHOD end_of_page.

    DATA :lf_lines TYPE sy-tfill .

    DATA : "lr_label TYPE REF TO cl_salv_form_label,
           lf_flow TYPE REF TO cl_salv_form_layout_flow .

    CREATE OBJECT lr_footer.
*--get total lines in internal table
     lf_lines = LINES( it_disp ).
     lr_label = lr_footer->create_label ( row = 1 column = 1 ).
     lr_label-> set_text( 'Information:' ).
     lf_flow = lr_footer->create_flow ( row = 2 column = 1 ).
     lf_flow-> create_text( TEXT = 'Total Number of Entries' ).
     lf_flow = lr_footer->create_flow ( row = 2 column = 2 ).
     lf_flow-> create_text( TEXT = lf_lines ).

  ENDMETHOD.                   "end_of_page

ENDCLASS.                   "lcl_perf_eval IMPLEMENTATION


START-OF-SELECTION.
DATA : obj_rep TYPE REF TO lcl_perf_eval. " Declaring Object for Class

CREATE OBJECT : obj_rep. " Creating Object

obj_rep->fill_disp( ). " Calling class Methods
obj_rep->disp_alv( ).