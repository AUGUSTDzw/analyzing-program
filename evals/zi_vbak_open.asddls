@AbapCatalog.sqlViewName: 'ZVBAKOPEN'
@AccessControl.authorizationCheck: #NOT_REQUIRED
@EndUserText.label: 'Open sales order headers for batch pricing review'
define view entity ZI_VBAK_OPEN
  as select from vbak
  association [0..1] to ZI_KNA1_NAME as _Customer
    on $projection.kunnr = _Customer.kunnr
{
  key vbeln,
      kunnr,
      waerk,
      netwr,
      menge,
      wrdat,
      _Customer,
      @Semantics.amount.currencyCode: 'waerk'
      netwr as net_amount,
      cast( sy-datum as abap.dats ) as run_date
}
where
  wrdat >= '20240101'
  and waerk  = 'USD'