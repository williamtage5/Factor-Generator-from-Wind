SELECT
    d.S_INFO_WINDCODE AS stock_code,
    d.TRADE_DT AS trade_date,
    d.S_VAL_PE_TTM AS pe_ttm,
    d.S_VAL_PB_NEW AS pb_lf,
    d.S_VAL_MV AS total_market_cap
FROM dbo.ASHAREEODDERIVATIVEINDICATOR d
WHERE d.TRADE_DT BETWEEN ? AND ?
  AND d.S_INFO_WINDCODE IN ({stock_code_placeholders})
ORDER BY d.S_INFO_WINDCODE, d.TRADE_DT;
