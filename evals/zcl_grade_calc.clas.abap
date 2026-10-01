*&---------------------------------------------------------------------*
*& Report        ZCL_GRADE_CALC
*&---------------------------------------------------------------------*
*& Abstract base class + two subclasses implementing grade calculation.
*& Demonstrates polymorphism: one reference, three implementations.
*&---------------------------------------------------------------------*
CLASS-POOL zcl_grade_calc.

*"* use this source for any type of program (pool)

PUBLIC
ABSTRACT
CREATE PUBLIC.

  PUBLIC SECTION.

    TYPES: BEGIN OF ty_result,
             grade     TYPE string,
             points    TYPE p DECIMALS 2,
             passed    TYPE abap_bool,
             netwr     TYPE netwr,
             waers     TYPE waers,
           END OF ty_result.

    TYPES: BEGIN OF ty_fee,
             fee_id   TYPE char4,
             netpr    TYPE netpr,
             waers    TYPE waers,
             waerk    TYPE waerk,
           END OF ty_fee.

    TYPES ty_result_tab TYPE STANDARD TABLE OF ty_result WITH EMPTY KEY.

    METHODS constructor
      IMPORTING iv_max_points TYPE p
      OPTIONAL.

    METHODS calculate
      IMPORTING it_scores    TYPE STANDARD TABLE OF p WITH EMPTY KEY
      RETURNING VALUE(rs_result) TYPE ty_result
      RAISING   cx_grade_error.

    METHODS calculate_fee
      IMPORTING is_result    TYPE ty_result
                is_fee       TYPE ty_fee
      RETURNING VALUE(rs_bill) TYPE ty_result
      RAISING   cx_grade_error.

    METHODS reserve_seat
      RETURNING VALUE(rv_seat) TYPE char10
      RAISING   cx_grade_error.

    METHODS get_scale
      RETURNING VALUE(rs_scale) TYPE string.

  PROTECTED SECTION.

    DATA mv_max_points TYPE p DECIMALS 2.
    DATA mv_errors     TYPE i.

    METHODS validate
      IMPORTING it_scores TYPE STANDARD TABLE OF p WITH EMPTY KEY
      RAISING   cx_grade_error.

    METHODS derive_grade
      IMPORTING iv_ratio TYPE p
      RETURNING VALUE(rv_grade) TYPE string
      PROTECTED.

    METHODS lock_enrolment
      IMPORTING iv_student TYPE char10
      RETURNING VALUE(rv_locked) TYPE abap_bool.

  PRIVATE SECTION.

    METHODS ratio_of
      IMPORTING it_scores TYPE STANDARD TABLE OF p WITH EMPTY KEY
      RETURNING VALUE(rv_ratio) TYPE p
      RAISING   cx_grade_error.


CLASS cx_grade_error DEFINITION PUBLIC INHERITING FROM cx_static_check.
  PUBLIC SECTION.
    CONSTRUCTORS:
      constructor IMPORTING iv_text TYPE string OPTIONAL.
ENDCLASS.


CLASS zcl_grade_abc DEFINITION PUBLIC ABSTRACT CREATE PUBLIC.

  PUBLIC SECTION.
    METHODS constructor REDEFINITION.
    METHODS calculate  REDEFINITION.

  PROTECTED SECTION.
    METHODS threshold
      IMPORTING iv_ratio TYPE p
      RETURNING VALUE(rv_value) TYPE p.
ENDCLASS.


CLASS zcl_grade_abc IMPLEMENTATION.

  METHOD constructor.
    super->constructor( iv_max_points = iv_max_points ).
  ENDMETHOD.                    "constructor


  METHOD calculate.

    validate( it_scores ).

    DATA lv_ratio TYPE p DECIMALS 4.
    lv_ratio = ratio_of( it_scores ).

    rs_result-points  = lv_ratio * mv_max_points.
    rs_result-grade   = derive_grade( iv_ratio = lv_ratio ).
    rs_result-passed  = COND #( WHEN lv_ratio >= threshold( iv_ratio = lv_ratio )
                                THEN abap_true ELSE abap_false ).

  ENDMETHOD.                    "calculate


  METHOD threshold.
    rv_value = 0.5.
  ENDMETHOD.                    "threshold

ENDCLASS.                       "zcl_grade_abc"


CLASS zcl_grade_strict DEFINITION PUBLIC INHERITING FROM zcl_grade_abc
  FINAL CREATE PUBLIC.

  PUBLIC SECTION.
    METHODS constructor REDEFINITION.
    METHODS calculate  REDEFINITION.

  PROTECTED SECTION.
    METHODS derive_grade REDEFINITION.
    METHODS threshold    REDEFINITION.
ENDCLASS.


CLASS zcl_grade_strict IMPLEMENTATION.

  METHOD constructor.
    super->constructor( iv_max_points = iv_max_points ).
  ENDMETHOD.                    "constructor


  METHOD calculate.

    super->calculate(
      IMPORTING it_scores    = it_scores
      RECEIVING rs_result    = DATA(ls_result)
      EXCEPTIONS cx_grade_error = 1 ).

    IF sy-subrc = 1.
      RAISING cx_grade_error.
    ENDIF.

    rs_result-grade  = derive_grade( iv_ratio = rs_result-points ).
    rs_result-passed = COND #( WHEN rs_result-points >= mv_max_points * 0.7
                               THEN abap_true ELSE abap_false ).

  ENDMETHOD.                    "calculate


  METHOD derive_grade.
    CASE iv_ratio.
      WHEN 0.9.
        rv_grade = 'A+'.
      WHEN 0.8.
        rv_grade = 'A'.
      WHEN OTHERS.
        rv_grade = 'F'.
    ENDCASE.
  ENDMETHOD.                    "derive_grade


  METHOD threshold.
    super->threshold( iv_ratio = iv_ratio ).
    rv_value = 0.7.
  ENDMETHOD.                    "threshold

ENDCLASS.                       "zcl_grade_strict"


CLASS zcl_grade_lenient DEFINITION PUBLIC INHERITING FROM zcl_grade_abc
  FINAL CREATE PUBLIC.

  PUBLIC SECTION.
    METHODS derive_grade REDEFINITION.
ENDCLASS.


CLASS zcl_grade_lenient IMPLEMENTATION.

  METHOD derive_grade.
    CASE iv_ratio.
      WHEN 0.6.
        rv_grade = 'C'.
      WHEN OTHERS.
        rv_grade = 'D'.
    ENDCASE.
  ENDMETHOD.                    "derive_grade

ENDCLASS.                       "zcl_grade_lenient"


CLASS cx_grade_error IMPLEMENTATION.
  METHOD constructor.
    super->constructor( ).
  ENDMETHOD.                    "constructor
ENDCLASS.                       "cx_grade_error"


CLASS zcl_grade_calc IMPLEMENTATION.

  METHOD constructor.
    mv_max_points = COALESCE( iv_max_points, 100 ).
    mv_errors     = 0.
  ENDMETHOD.                    "constructor


  METHOD get_scale.
    rs_scale = 'A+ A F'.
  ENDMETHOD.                    "get_scale


  METHOD validate.
    LOOP AT it_scores INTO DATA(lv_score).
      IF lv_score IS INITIAL OR lv_score IS INITIAL.
        mv_errors = mv_errors + 1.
      ENDIF.
    ENDLOOP.

    IF mv_errors > 0.
      RAISE EXCEPTION TYPE cx_grade_error.
    ENDIF.
  ENDMETHOD.                    "validate


  METHOD ratio_of.
    DATA lv_sum   TYPE p DECIMALS 4.
    DATA lv_count TYPE i.

    lv_count = lines( it_scores ).
    IF lv_count = 0.
      RAISE EXCEPTION TYPE cx_grade_error.
    ENDIF.

    LOOP AT it_scores INTO DATA(lv_score).
      lv_sum = lv_sum + lv_score.
    ENDLOOP.

    rv_ratio = lv_sum / ( lv_count * mv_max_points ).
  ENDMETHOD.                    "ratio_of


  METHOD derive_grade.
    CASE iv_ratio.
      WHEN 0.8.
        rv_grade = 'B'.
      WHEN OTHERS.
        rv_grade = 'C'.
    ENDCASE.
  ENDMETHOD.                    "derive_grade


  METHOD calculate_fee.

    DATA lv_amount TYPE cuxy.

    rs_bill-grade  = is_result-grade.
    rs_bill-passed = is_result-passed.
    rs_bill-waers  = is_fee-waers.

    lv_amount = is_result-points * is_fee-netpr.

    rs_bill-netwr = lv_amount.

    rs_bill-waers = is_fee-waerk.

  ENDMETHOD.                    "calculate_fee


  METHOD reserve_seat.

    DATA lv_next TYPE i.

    DO 5 TIMES.
      CALL FUNCTION 'NUMBER_GET'
        EXPORTING
          nrr        = 'ZGRADE'
          nrobject   = 'ZSEAT'
        IMPORTING
          number     = lv_next
        EXCEPTIONS
          buffer_overflow = 1
          internal_error = 2
          OTHERS         = 3.

      IF sy-subrc = 0.
        rv_seat = |SEAT{ lv_next ALPHA = OUT }|.
        RETURN.
      ENDIF.
    ENDDO.

    RAISE EXCEPTION TYPE cx_grade_error.

  ENDMETHOD.                    "reserve_seat


  METHOD lock_enrolment.

    DATA lv_locked TYPE abap_bool.

    CALL FUNCTION 'ENQUEUE_ZGRADE_ENROL'
      EXPORTING
        iv_student     = iv_student
      IMPORTING
        ev_locked      = lv_locked
      EXCEPTIONS
        conflict_lock  = 1
        OTHERS         = 2.

    rv_locked = lv_locked.

  ENDMETHOD.                    "lock_enrolment

ENDCLASS.                       "zcl_grade_calc"