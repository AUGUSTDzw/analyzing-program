CLASS zcl_zreuse_so_002_chdo DEFINITION
  PUBLIC
  CREATE PUBLIC .

  PUBLIC SECTION.

    INTERFACES if_chdo_enhancements .

    CLASS-DATA objectclass TYPE if_chdo_object_tools_rel=>ty_cdobjectcl READ-ONLY VALUE 'ZREUSE_SO_002' ##NO_TEXT.

    CLASS-METHODS write
      IMPORTING
        !objectid                TYPE if_chdo_object_tools_rel=>ty_cdobjectv
        !utime                   TYPE if_chdo_object_tools_rel=>ty_cduzeit
        !udate                   TYPE if_chdo_object_tools_rel=>ty_cddatum
        !username                TYPE if_chdo_object_tools_rel=>ty_cdusername
        !planned_change_number   TYPE if_chdo_object_tools_rel=>ty_planchngnr DEFAULT space
        !object_change_indicator TYPE if_chdo_object_tools_rel=>ty_cdchngindh DEFAULT 'U'
        !planned_or_real_changes TYPE if_chdo_object_tools_rel=>ty_cdflag DEFAULT space
        !no_change_pointers      TYPE if_chdo_object_tools_rel=>ty_cdflag DEFAULT space
        !o_zreuse_head_002       TYPE zreuse_head_002 OPTIONAL
        !n_zreuse_head_002       TYPE zreuse_head_002 OPTIONAL
        !upd_zreuse_head_002     TYPE if_chdo_object_tools_rel=>ty_cdchngindh DEFAULT space
        !o_zreuse_item_002       TYPE zreuse_item_002 OPTIONAL
        !n_zreuse_item_002       TYPE zreuse_item_002 OPTIONAL
        !upd_zreuse_item_002     TYPE if_chdo_object_tools_rel=>ty_cdchngindh DEFAULT space
      EXPORTING
        VALUE(changenumber)      TYPE if_chdo_object_tools_rel=>ty_cdchangenr
      RAISING
        cx_chdo_write_error .
  PROTECTED SECTION.
  PRIVATE SECTION.
ENDCLASS.



CLASS ZCL_ZREUSE_SO_002_CHDO IMPLEMENTATION.


  METHOD  if_chdo_enhancements~authority_check.
    "add application specific authorization check
    "example
    "enduser shall not be able to see change docs for all company codes

    rv_is_authorized = abap_true.
  ENDMETHOD.


  METHOD  if_chdo_enhancements~check_authorization_for_delete.
    "add application specific authorization check
    "example
    "enduser shall not be able to see change docs for all company codes

    rv_is_authorized-all = abap_true.
    rv_is_authorized-individual = abap_true.
  ENDMETHOD.


  METHOD write.
*"----------------------------------------------------------------------
*"         this WRITE method is generated for object ZREUSE_SO_002
*"         never change it manually, please!        :10/02/2024
*"         All changes will be overwritten without a warning!
*"
*"         CX_CHDO_WRITE_ERROR is used for error handling
*"----------------------------------------------------------------------

    DATA: l_upd        TYPE if_chdo_object_tools_rel=>ty_cdchngind.

    CALL METHOD cl_chdo_write_tools=>changedocument_open
      EXPORTING
        objectclass             = objectclass
        objectid                = objectid
        planned_change_number   = planned_change_number
        planned_or_real_changes = planned_or_real_changes.

    IF ( n_zreuse_head_002 IS INITIAL ) AND
       ( o_zreuse_head_002 IS INITIAL ).
      l_upd  = space.
    ELSE.
      l_upd = upd_zreuse_head_002.
    ENDIF.

    IF  l_upd  NE space.
      CALL METHOD cl_chdo_write_tools=>changedocument_single_case
        EXPORTING
          tablename        = 'ZREUSE_HEAD_002'
          workarea_old     = o_zreuse_head_002
          workarea_new     = n_zreuse_head_002
          change_indicator = upd_zreuse_head_002
          docu_delete      = ''
          docu_insert      = ''
          docu_delete_if   = ''
          docu_insert_if   = ''.
    ENDIF.

    IF ( n_zreuse_item_002 IS INITIAL ) AND
       ( o_zreuse_item_002 IS INITIAL ).
      l_upd  = space.
    ELSE.
      l_upd = upd_zreuse_item_002.
    ENDIF.

    IF  l_upd  NE space.
      CALL METHOD cl_chdo_write_tools=>changedocument_single_case
        EXPORTING
          tablename        = 'ZREUSE_ITEM_002'
          workarea_old     = o_zreuse_item_002
          workarea_new     = n_zreuse_item_002
          change_indicator = upd_zreuse_item_002
          docu_delete      = ''
          docu_insert      = ''
          docu_delete_if   = ''
          docu_insert_if   = ''.
    ENDIF.

    CALL METHOD cl_chdo_write_tools=>changedocument_close
      EXPORTING
        objectclass             = objectclass
        objectid                = objectid
        date_of_change          = udate
        time_of_change          = utime
        username                = username
        object_change_indicator = object_change_indicator
        no_change_pointers      = no_change_pointers
      IMPORTING
        changenumber            = changenumber.

  ENDMETHOD.
ENDCLASS.
