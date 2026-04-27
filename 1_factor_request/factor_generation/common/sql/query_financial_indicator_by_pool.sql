SELECT
    f.S_INFO_WINDCODE AS stock_code,
    f.ANN_DT AS announce_date,
    f.REPORT_PERIOD AS report_period,
    f.S_FA_ROE AS roe,
    f.S_FA_YOY_OR AS revenue_yoy,
    f.S_FA_YOYNETPROFIT AS netprofit_yoy
FROM dbo.ASHAREFINANCIALINDICATOR f
WHERE f.ANN_DT <= ?
  AND f.S_INFO_WINDCODE IN ({stock_code_placeholders})
ORDER BY f.S_INFO_WINDCODE, f.ANN_DT;
