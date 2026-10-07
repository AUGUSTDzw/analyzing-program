*&---------------------------------------------------------------------* 
*&  Include  zsolid_report_i01 
*&---------------------------------------------------------------------* 
INTERFACE if_reporter. 
  METHODS: 
    at_selection_screen, 
    get_data, 
    get_screen. 
ENDINTERFACE. 

INTERFACE if_event_handler. 
  METHODS on_user_command FOR EVENT added_function OF cl_salv_events 
    IMPORTING e_salv_function.

  METHODS on_double_click 
    FOR EVENT double_click OF cl_salv_events_table 
    IMPORTING !row !column. 

  METHODS on_line_click FOR EVENT link_click OF cl_salv_events_table 
    IMPORTING !row !column. 
ENDINTERFACE.
