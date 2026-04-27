SELECT
    v.S_INFO_WINDCODE AS stock_code,
    v.TRADE_DT AS trade_date,
    v.S_VAL_PE_TTM AS pe_ttm,
    v.S_VAL_PB_NEW AS pb_lf,
    v.S_VAL_MV AS total_market_cap
FROM dbo.ASHAREEODDERIVATIVEINDICATOR v
WHERE v.TRADE_DT BETWEEN ? AND ?
  AND v.S_INFO_WINDCODE IN ({stock_code_placeholders})
ORDER BY v.S_INFO_WINDCODE, v.TRADE_DT;
