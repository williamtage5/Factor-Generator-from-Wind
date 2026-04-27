WITH cal AS (
    SELECT TRADE_DAYS AS trade_date
    FROM dbo.ASHARECALENDAR
    WHERE S_INFO_EXCHMARKET = ?
      AND TRADE_DAYS BETWEEN ? AND ?
),
effective_weight_date AS (
    SELECT
        c.trade_date,
        wd.weight_date
    FROM cal c
    OUTER APPLY (
        SELECT TOP 1 w.TRADE_DT AS weight_date
        FROM dbo.AINDEXHS300FREEWEIGHT w
        WHERE w.S_INFO_WINDCODE = ?
          AND w.TRADE_DT <= c.trade_date
        ORDER BY w.TRADE_DT DESC
    ) wd
)
SELECT
    e.trade_date,
    e.weight_date AS effective_weight_date,
    w.S_CON_WINDCODE AS stock_code,
    w.I_WEIGHT AS index_weight
FROM effective_weight_date e
JOIN dbo.AINDEXHS300FREEWEIGHT w
  ON w.S_INFO_WINDCODE = ?
 AND w.TRADE_DT = e.weight_date
ORDER BY e.trade_date, w.S_CON_WINDCODE;

