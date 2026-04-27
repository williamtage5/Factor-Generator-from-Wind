SELECT
    d.S_INFO_WINDCODE AS stock_code,
    d.TRADE_DT AS trade_date,
    d.S_VAL_MV AS mv_raw
FROM dbo.ASHAREEODDERIVATIVEINDICATOR d
WHERE d.TRADE_DT = ?
  AND d.S_INFO_WINDCODE IN ({stock_code_placeholders})
ORDER BY d.S_INFO_WINDCODE;

