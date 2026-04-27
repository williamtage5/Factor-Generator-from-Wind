SELECT
    p.S_INFO_WINDCODE AS stock_code,
    p.TRADE_DT AS trade_date,
    p.S_DQ_ADJCLOSE AS close_price
FROM dbo.ASHAREEODPRICES p
WHERE p.TRADE_DT BETWEEN ? AND ?
  AND p.S_INFO_WINDCODE IN ({stock_code_placeholders})
ORDER BY p.S_INFO_WINDCODE, p.TRADE_DT;
