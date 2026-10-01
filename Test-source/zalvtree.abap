*&---------------------------------------------------------------------*
*& Report ZALVTREE *
*& *
*&---------------------------------------------------------------------*
*& *
*& *
*&---------------------------------------------------------------------*

REPORT ZALVTREE .

*Data Declaration
*----------------
TABLES: ekko.
TYPE-POOLS: slis. "ALV Declarations

TYPES: BEGIN OF t_ekko,
ebeln TYPE ekpo-ebeln,
ebelp TYPE ekpo-ebelp,
statu TYPE ekpo-statu,
aedat TYPE ekpo-aedat,
matnr TYPE ekpo-matnr,
menge TYPE ekpo-menge,
meins TYPE ekpo-meins,
netpr TYPE ekpo-netpr,
peinh TYPE ekpo-peinh,
END OF t_ekko.

DATA: it_ekko TYPE STANDARD TABLE OF t_ekko INITIAL SIZE 0,
it_ekpo TYPE STANDARD TABLE OF t_ekko INITIAL SIZE 0,
it_emptytab TYPE STANDARD TABLE OF t_ekko INITIAL SIZE 0,
wa_ekko TYPE t_ekko,
wa_ekpo TYPE t_ekko.

DATA: ok_code like sy-ucomm, "OK-Code
save_ok like sy-ucomm.

*ALV data declarations
DATA: fieldcatalog TYPE lvc_t_fcat WITH HEADER LINE.

DATA: gd_fieldcat TYPE lvc_t_fcat,
gd_tab_group TYPE slis_t_sp_group_alv,
gd_layout TYPE slis_layout_alv.

*ALVtree data declarations
CLASS cl_gui_column_tree DEFINITION LOAD.
CLASS cl_gui_cfw DEFINITION LOAD.

DATA: gd_tree TYPE REF TO cl_gui_alv_tree,
gd_hierarchy_header TYPE treev_hhdr,
gd_report_title TYPE slis_t_listheader,
gd_logo TYPE sdydo_value,
gd_variant TYPE disvariant.

*Create container for alv-tree
DATA: l_tree_container_name(30) TYPE c,
l_custom_container TYPE REF TO cl_gui_custom_container.


************************************************************************
*Includes
*INCLUDE ZDEMO_ALVTREEO01. "Screen PBO Modules
*INCLUDE ZDEMO_ALVTREEI01. "Screen PAI Modules
*INCLUDE ZDEMO_ALVTREEF01. "ABAP Subroutines(FORMS)

************************************************************************
*Start-of-selection.
START-OF-SELECTION.

* ALVtree setup data
PERFORM data_retrieval.
PERFORM build_fieldcatalog.
PERFORM build_layout.
PERFORM build_hierarchy_header CHANGING gd_hierarchy_header.
PERFORM build_report_title USING gd_report_title gd_logo.
PERFORM build_variant.

* Display ALVtree report
call screen 100.


*&---------------------------------------------------------------------*
*& Form DATA_RETRIEVAL
*&---------------------------------------------------------------------*
* Retrieve data into Internal tables
*----------------------------------------------------------------------*
FORM data_retrieval.
SELECT ebeln
UP TO 10 ROWS
FROM ekko
INTO corresponding fields of TABLE it_ekko.

loop at it_ekko into wa_ekko.
SELECT ebeln ebelp statu aedat matnr menge meins netpr peinh
FROM ekpo
appending TABLE it_ekpo
where ebeln eq wa_ekko-ebeln.
endloop.
ENDFORM. " DATA_RETRIEVAL


*&---------------------------------------------------------------------*
*& Form BUILD_FIELDCATALOG
*&---------------------------------------------------------------------*
* Build Fieldcatalog for ALV Report
*----------------------------------------------------------------------*
FORM build_fieldcatalog.
* Please not there are a number of differences between the structure of
* ALVtree fieldcatalogs and ALVgrid fieldcatalogs.
* For example the field seltext_m is replace by scrtext_m in ALVtree.

fieldcatalog-fieldname = 'EBELN'. "Field name in itab
fieldcatalog-scrtext_m = 'Purchase Order'. "Column text
fieldcatalog-col_pos = 0. "Column position
fieldcatalog-outputlen = 15. "Column width
fieldcatalog-emphasize = 'X'. "Emphasize (X or SPACE)
fieldcatalog-key = 'X'. "Key Field? (X or SPACE)
* fieldcatalog-do_sum = 'X'. "Sum Column?
* fieldcatalog-no_zero = 'X'. "Don't display if zero
APPEND fieldcatalog TO gd_fieldcat.
CLEAR fieldcatalog.

fieldcatalog-fieldname = 'EBELP'.
fieldcatalog-scrtext_m = 'PO Iten'.
fieldcatalog-outputlen = 15.
fieldcatalog-col_pos = 1.
APPEND fieldcatalog TO gd_fieldcat..
CLEAR fieldcatalog.

fieldcatalog-fieldname = 'STATU'.
fieldcatalog-scrtext_m = 'Status'.
fieldcatalog-outputlen = 15.
fieldcatalog-col_pos = 2.
APPEND fieldcatalog TO gd_fieldcat..
CLEAR fieldcatalog.

fieldcatalog-fieldname = 'AEDAT'.
fieldcatalog-scrtext_m = 'Item change date'.
fieldcatalog-outputlen = 15.
fieldcatalog-col_pos = 3.
APPEND fieldcatalog TO gd_fieldcat..
CLEAR fieldcatalog.

fieldcatalog-fieldname = 'MATNR'.
fieldcatalog-scrtext_m = 'Material Number'.
fieldcatalog-outputlen = 15.
fieldcatalog-col_pos = 4.
APPEND fieldcatalog TO gd_fieldcat..
CLEAR fieldcatalog.

fieldcatalog-fieldname = 'MENGE'.
fieldcatalog-scrtext_m = 'PO quantity'.
fieldcatalog-outputlen = 15.
fieldcatalog-col_pos = 5.
APPEND fieldcatalog TO gd_fieldcat..
CLEAR fieldcatalog.

fieldcatalog-fieldname = 'MEINS'.
fieldcatalog-scrtext_m = 'Order Unit'.
fieldcatalog-outputlen = 15.
fieldcatalog-col_pos = 6.
APPEND fieldcatalog TO gd_fieldcat..
CLEAR fieldcatalog.

fieldcatalog-fieldname = 'NETPR'.
fieldcatalog-scrtext_m = 'Net Price'.
fieldcatalog-outputlen = 15.
fieldcatalog-col_pos = 7.
fieldcatalog-datatype = 'CURR'.
APPEND fieldcatalog TO gd_fieldcat..
CLEAR fieldcatalog.

fieldcatalog-fieldname = 'PEINH'.
fieldcatalog-scrtext_m = 'Price Unit'.
fieldcatalog-outputlen = 15.
fieldcatalog-col_pos = 8.
APPEND fieldcatalog TO gd_fieldcat..
CLEAR fieldcatalog.
ENDFORM. " BUILD_FIELDCATALOG


*&---------------------------------------------------------------------*
*& Form BUILD_LAYOUT
*&---------------------------------------------------------------------*
* Build layout for ALV grid report
*----------------------------------------------------------------------*
FORM build_layout.
gd_layout-no_input = 'X'.
gd_layout-colwidth_optimize = 'X'.
gd_layout-totals_text = 'Totals'(201).
* gd_layout-totals_only = 'X'.
* gd_layout-f2code = 'DISP'. "Sets fcode for when double
* "click(press f2)
* gd_layout-zebra = 'X'.
* gd_layout-group_change_edit = 'X'.
* gd_layout-header_text = 'helllllo'.
ENDFORM. " BUILD_LAYOUT


*&---------------------------------------------------------------------*
*& Form build_hierarchy_header
*&---------------------------------------------------------------------*
* build hierarchy-header-information
*----------------------------------------------------------------------*
* -->P_L_HIERARCHY_HEADER structure for hierarchy-header
*----------------------------------------------------------------------*
FORM build_hierarchy_header CHANGING
p_hierarchy_header TYPE treev_hhdr.

p_hierarchy_header-heading = 'Hierarchy Header'(013).
p_hierarchy_header-tooltip = 'This is the Hierarchy Header !'(014).
p_hierarchy_header-width = 30.
p_hierarchy_header-width_pix = ''.
ENDFORM. " build_hierarchy_header

*&---------------------------------------------------------------------*
*& Form BUILD_REPORT_TITLE
*&---------------------------------------------------------------------*
* Build table for ALVtree header
*----------------------------------------------------------------------*
* <-> p1 Header details
* <-> p2 Logo value
*----------------------------------------------------------------------*
FORM build_report_title CHANGING
pt_report_title TYPE slis_t_listheader
pa_logo TYPE sdydo_value.

DATA: ls_line TYPE slis_listheader,
ld_date(10) TYPE c.

* List Heading Line(TYPE H)
CLEAR ls_line.
ls_line-typ = 'H'.
* ls_line-key "Not Used For This Type(H)
ls_line-info = 'PO ALVTree Display'.
APPEND ls_line TO pt_report_title.

* Status Line(TYPE S)
ld_date(2) = sy-datum+6(2).
ld_date+2(1) = '/'.
ld_date+3(2) = sy-datum+4(2).
ld_date+5(1) = '/'.
ld_date+6(4) = sy-datum(4).

ls_line-typ = 'S'.
ls_line-key = 'Date'.
ls_line-info = ld_date.
APPEND ls_line TO pt_report_title.

* Action Line(TYPE A)
CLEAR ls_line.
ls_line-typ = 'A'.
CONCATENATE 'Report: ' sy-repid INTO ls_line-info SEPARATED BY space.
APPEND ls_line TO pt_report_title.
ENDFORM.


*&---------------------------------------------------------------------*
*& Form BUILD_VARIANT
*&---------------------------------------------------------------------*
* Build variant
*----------------------------------------------------------------------*
form build_variant.
* Set repid for storing variants
gd_variant-report = sy-repid.
endform. " BUILD_VARIANT 