REPORT zorder_dialog.

*"----------------------------------------------------------------------
*"* Interactive order entry: selection screen, dynpro 0100 with
*"* PBO/PAI modules, change order.
*"----------------------------------------------------------------------

TYPES: BEGIN OF ty_order,
         vbeln TYPE vbeln_va,
         kunnr TYPE kunnr,
         waerk TYPE waerk,
         netwr TYPE netwr,
         menge TYPE menge,
       END OF ty_order.

TYPES ty_order_tab TYPE STANDARD TABLE OF ty_order WITH EMPTY KEY.

DATA gt_order TYPE ty_order_tab.
DATA gs_order TYPE ty_order.
DATA gv_user  TYPE sy-uname.
DATA gv_datum TYPE sy-datum.
DATA gv_init  TYPE abap_bool.

SELECTION-SCREEN BEGIN OF BLOCK b1 WITH FRAME TITLE TEXT-001.
  SELECT-OPTIONS s_vbeln FOR gs_order-vbeln.
  PARAMETERS p_waerk TYPE waerk DEFAULT 'EUR'.
SELECTION-SCREEN END OF BLOCK b1.

INITIALIZATION.
  gv_datum = sy-datum.
  gv_user  = sy-uname.

AT SELECTION-SCREEN OUTPUT.
  LOOP AT SCREEN.
    IF SCREEN-NAME = 'P_WAERK'.
      SCREEN-INTENSIFIED = '1'.
      MODIFY SCREEN.
    ENDIF.
  ENDLOOP.

AT SELECTION-SCREEN ON VALUE-REQUEST FOR s_vbeln.
  READ TABLE gt_order INTO gs_order INDEX 1.
  MESSAGE 'No order data loaded yet' TYPE 'S'.

START-OF-SELECTION.
  SELECT vbeln kunnr waerk netwr menge
    FROM vbak
    INTO TABLE gt_order
    WHERE vbeln IN s_vbeln
      AND waerk = p_waerk.

  CALL SCREEN 0100.


MODULE status_0100 OUTPUT.

  SET PF-STATUS 'S0100'.
  SET TITLEBAR 'T0100'.

  LOOP AT SCREEN.
    IF SCREEN-NAME = 'P_WAERK'.
      SCREEN-DISPLAY-MODE = '1'.
      MODIFY SCREEN.
    ENDIF.
  ENDLOOP.

ENDMODULE.                     "status_0100


MODULE save_order INPUT.

  DATA lv_check TYPE c LENGTH 1.
  DATA ls_order TYPE ty_order.

  IF gs_order-vbeln IS INITIAL.
    MESSAGE 'Sales order number is mandatory' TYPE 'E'.
  ENDIF.

  SELECT SINGLE * FROM vbak INTO ls_order
    WHERE vbeln = gs_order-vbeln.

  CALL FUNCTION 'AUTHORITY-CHECK'
    EXPORTING
      OBJECT        = 'V_VBAK_VKO'
      TCD           = 'VBA1'
      ACTIVITY      = '01'
    EXCEPTIONS
      NOT_AUTHORIZED = 1
      OTHERS         = 2.

  IF sy-subrc = 1.
    MESSAGE 'Not authorized for sales orders' TYPE 'E'.
  ENDIF.

  INSERT INTO vbak VALUES ls_order.

  COMMIT WORK.

  MESSAGE 'Order saved' TYPE 'S'.
  SET SCREEN 0000.
  LEAVE PROGRAM.

ENDMODULE.                     "save_order


MODULE back INPUT.
  CALL SCREEN 0000.
  LEAVE PROGRAM.
ENDMODULE.                     "back


MODULE user_command_0100 INPUT.

  DATA lv_ok_code TYPE sy-ucomm.

  lv_ok_code = ok_code.
  CLEAR ok_code.

  CASE lv_ok_code.
    WHEN 'SAVE'.
      SET SCREEN 0100.
    WHEN 'BACK' OR 'EXIT'.
      SET SCREEN 0000.
    WHEN 'CANC'.
      SET SCREEN 0000.
  ENDCASE.

ENDMODULE.                     "user_command_0100