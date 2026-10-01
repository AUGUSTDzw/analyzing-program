REPORT  Z_DYNITALV.

TYPE-POOLS: slis.
DATA :
*--  VARIABLES for function REUSE_ALV_DISPLAY
* Interface consistency check log output
i_interface_check,
* Ignore all buffers?
i_bypassing_buffer TYPE  char01,
* Buffer active
i_buffer_active          VALUE space,
* Name of the calling program
i_callback_program       LIKE sy-repid VALUE space,
* Set EXIT rountine to status
i_callback_pf_status_set TYPE slis_formname VALUE space,
* EXIT routine for command handling
i_callback_user_command  TYPE slis_formname VALUE space,
* Internal output table structure name
i_structure_name      
   LIKE dd02l-tabname,
* List layout specifications
is_layout                TYPE slis_layout_alv,
* Field catalog with field descriptions
it_fieldcat              TYPE slis_t_fieldcat_alv,
* Table of inactive function codes
it_excluding             TYPE slis_t_extab,
* Grouping fields for column selection
it_special_groups        TYPE slis_t_sp_group_alv,
* Sort criteria for first list display
it_sort                  TYPE slis_t_sortinfo_alv WITH HEADER LINE,
* Filter criteria for first list output
it_filter                TYPE slis_t_filter_alv,
* Selection information modification
is_sel_hide              TYPE slis_sel_hide_alv,
* Initial variant active/inactive logic
i_default                VALUE 'X',
* Variants can be saved
i_save                 VALUE space,
* Variant information
is_variant               LIKE disvariant,
* Table of events to perform
it_events                TYPE slis_t_event,
* Standard fcode exit requests table
it_event_exit            TYPE slis_t_event_exit,
* Print information
is_print                 TYPE slis_print_alv,
* Initialization key for Re/Re interface
is_reprep_id             TYPE slis_reprep_id,
* Coordinates for list in dialog box
i_screen_start_column    VALUE 0,
* Coordinates for list in dialog box
i_screen_start_line      VALUE 0,
* Coordinates for list in dialog box
i_screen_end_column      VALUE 0,
* Coordinates for list
 in dialog box
i_screen_end_line        VALUE 0,
e_exit_caused_by_caller,
es_exit_caused_by_user   TYPE slis_exit_by_user,
* Temporary structure for it_fieldcat
xfield                   TYPE slis_fieldcat_alv,
* Temporary structure for it_events
xxevent                   TYPE slis_alv_event.


DATA: new_table TYPE REF TO data,
      new_line  TYPE REF TO data,
      IS_LVC_CAT type LVC_S_FCAT,
      IT_LVC_CAT type LVC_T_FCAT,
      IS_FIELDCAT type SLIS_FIELDCAT_ALV.

FIELD-SYMBOLS: <l_table> TYPE TABLE,
               <l_line>  TYPE ANY,
               <l_field> TYPE ANY.
*Main Program
START-OF-SELECTION.
  PERFORM Field_Catalog.
  PERFORM SET_DATA.
  PERFORM DISPLAY_ALV.

FORM Field_Catalog.
" Here we create the field catalog for dynamic internal table.
" And create table dynamicly using method: create_dynamic_table from class: cl_alv_table_create.
FORM Field_Catalog .

  IS_LVC_CAT-fieldname = 'BUKRS'.
  IS_LVC_CAT-ref_field = 'BUKRS'.
  IS_LVC_CAT-ref_table = 'PA0001'.
  IS_LVC_CAT-SCRTEXT_S  = IS_LVC_CAT-SCRTEXT_M =
  IS_LVC_CAT-SCRTEXT_L  = 'Company Code'.
  APPEND IS_LVC_CAT TO IT_LVC_CAT.

  IS_FIELDCAT-fieldname     = 'BUKRS'.
  IS_FIELDCAT-ref_fieldname = 'BUKRS'.
  IS_FIELDCAT-ref_tabname   = 'PA0001'.
  IS_FIELDCAT-OUTPUTLEN     = 10.
  IS_FIELDCAT-SELTEXT_S = IS_FIELDCAT-SELTEXT_M =
                          IS_FIELDCAT-SELTEXT_L = 'Company Code'.
  APPEND IS_FIELDCAT TO IT_FIELDCAT.

  IS_LVC_CAT-fieldname = 'WERKS'.
  IS_LVC_CAT-ref_field = 'WERKS'.
  IS_LVC_CAT-ref_table =
 'PA0001'.
  IS_LVC_CAT-SCRTEXT_S  = IS_LVC_CAT-SCRTEXT_M =
  IS_LVC_CAT-SCRTEXT_L  = 'Pers.Area'.
  APPEND IS_LVC_CAT TO IT_LVC_CAT.

  IS_FIELDCAT-fieldname     = 'WERKS'.
  IS_FIELDCAT-ref_fieldname = 'WERKS'.
  IS_FIELDCAT-ref_tabname   = 'PA0001'.
  IS_FIELDCAT-OUTPUTLEN     = 10.
  IS_FIELDCAT-SELTEXT_S = IS_FIELDCAT-SELTEXT_M =
                          IS_FIELDCAT-SELTEXT_L = 'Pers.Area'.
  APPEND IS_FIELDCAT TO IT_FIELDCAT.

  IS_LVC_CAT-fieldname = 'BTRTL'.
  IS_LVC_CAT-ref_field = 'BTRTL'.
  IS_LVC_CAT-ref_table = 'PA0001'.
  IS_LVC_CAT-SCRTEXT_S  = IS_LVC_CAT-SCRTEXT_M =
  IS_LVC_CAT-SCRTEXT_L  = 'Pers.SubArea'.
  APPEND IS_LVC_CAT TO IT_LVC_CAT.

  IS_FIELDCAT-fieldname     = 'BTRTL'.
  IS_FIELDCAT-ref_fieldname = 'BTRTL'.
  IS_FIELDCAT-ref_tabname   = 'PA0001'.
  IS_FIELDCAT-OUTPUTLEN     = 10.
  IS_FIELDCAT-SELTEXT_S = IS_FIELDCAT-SELTEXT_M =
                         
 IS_FIELDCAT-SELTEXT_L = 'Pers.SubArea'.
  APPEND IS_FIELDCAT TO IT_FIELDCAT.

  IS_LVC_CAT-fieldname = 'CNAME'.
  IS_LVC_CAT-ref_field = 'CNAME'.
  IS_LVC_CAT-ref_table = 'PA0002'.
  IS_LVC_CAT-SCRTEXT_S  = IS_LVC_CAT-SCRTEXT_M =
  IS_LVC_CAT-SCRTEXT_L  = 'Name'.
  APPEND IS_LVC_CAT TO IT_LVC_CAT.

  IS_FIELDCAT-fieldname     = 'CNAME'.
  IS_FIELDCAT-ref_fieldname = 'CNAME'.
  IS_FIELDCAT-ref_tabname   = 'PA0002'.
  IS_FIELDCAT-OUTPUTLEN     = 20.
  IS_FIELDCAT-SELTEXT_S = IS_FIELDCAT-SELTEXT_M =
                          IS_FIELDCAT-SELTEXT_L = 'Name'.
  APPEND IS_FIELDCAT TO IT_FIELDCAT.

* Create a new Table
  CALL METHOD cl_alv_table_create=>create_dynamic_table
    EXPORTING
      it_fieldcatalog = IT_LVC_CAT
    IMPORTING
      ep_table        = new_table.

* Create a new Line with the same
 structure of the table.
  ASSIGN new_table->* TO <l_table>.
  CREATE DATA new_line LIKE LINE OF <l_table>.
  ASSIGN new_line->* TO <l_line>.

ENDFORM.                    " CREATE_LAYOUT
" Form Set_Data.
" Here we input our data.
FORM SET_DATA .
* Test it...
    DO 3 TIMES.
      ASSIGN COMPONENT 'BUKRS' OF STRUCTURE <l_line> TO <l_field>.
      <l_field> = '8369'.

      ASSIGN COMPONENT 'WERKS' OF STRUCTURE <l_line> TO <l_field>.
      <l_field> = '1000'.

      ASSIGN COMPONENT 'BTRTL' OF STRUCTURE <l_line> TO <l_field>.
      <l_field> = '0100'.

      ASSIGN COMPONENT 'CNAME' OF STRUCTURE <l_line> TO <l_field>.
      <l_field> = 'Test Employee Name'.

      INSERT <l_line> INTO TABLE <l_table>.
   
 ENDDO.
ENDFORM.                    " SET_DATA
" Form Display_ALV
" We display our data using FM: 'REUSE_ALV_LIST_DISPLAY'.
FORM DISPLAY_ALV .

*  SET PAGE HEADER & END LIST.
  CLEAR xxevent.
  xxevent-name = 'TOP_OF_PAGE'.
  xxevent-form = 'TOP_OF_PAGE_ALV'.
  APPEND xxevent TO it_events.

  CLEAR xxevent.
  xxevent-name = 'END_OF_LIST'.
  xxevent-form = 'END_OF_LIST_ALV'.
  APPEND xxevent TO it_events.

* Layout
  IS_LAYOUT-COLWIDTH_OPTIMIZE = ''.

* setting variant
*  is_variant-variant = p_var.
  is_variant-report = sy-repid.
  is_variant-username = sy-uname.
* others
  i_save = 'A'.
  i_callback_program = sy-repid.

  CALL FUNCTION 'REUSE_ALV_LIST_DISPLAY'
       EXPORTING
            i_interface_check        = i_interface_check
            i_bypassing_buffer       =
 i_bypassing_buffer
            i_buffer_active          = i_buffer_active
            i_callback_program       = i_callback_program
            i_callback_pf_status_set = i_callback_pf_status_set
            i_callback_user_command  = i_callback_user_command
            i_structure_name         = i_structure_name
            is_layout                = is_layout
            it_fieldcat              = it_fieldcat
            it_excluding             = it_excluding
            it_special_groups        = it_special_groups
            it_sort                  = it_sort[]
            it_filter                = it_filter
            is_sel_hide              = is_sel_hide
            i_default                = i_default
            i_save                   = i_save
            is_variant               = is_variant
            it_events                = it_events
            it_event_exit            = it_event_exit
           
 is_print                 = is_print
            is_reprep_id             = is_reprep_id
*            i_screen_start_column    = i_screen_start_column
            i_screen_start_line      = i_screen_start_line
            i_screen_end_column      = i_screen_end_column
            i_screen_end_line        = i_screen_end_line
       IMPORTING
            e_exit_caused_by_caller  = e_exit_caused_by_caller
            es_exit_caused_by_user   = es_exit_caused_by_user
       TABLES
            t_outtab                 = <l_table>
       EXCEPTIONS
            program_error            = 1
            OTHERS                   = 2.

            .
  IF SY-SUBRC <> 0.
   MESSAGE ID SY-MSGID TYPE SY-MSGTY NUMBER SY-MSGNO
           WITH SY-MSGV1 SY-MSGV2 SY-MSGV3 SY-MSGV4.
  ENDIF.
ENDFORM.                    " DISPLAY_ALV
" Form TOP_OF_PAGE_ALV and END_OF_LIST_ALV.
" Here where we can put Report header and footer text.
FORM TOP_OF_PAGE_ALV .
  WRITE: 'Here Your Report Header'.
  WRITE:/'Sub Report Header '.
  SKIP.
ENDFORM.                    " TOP_OF_PAGE_ALV

FORM END_OF_LIST_ALV .
  WRITE:/'Here Your Report Footer'.
  WRITE:/'Sub Report Footer '.
  SKIP.
ENDFORM.                    " END_OF_LIST_ALV