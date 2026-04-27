SELECT
    c.S_INFO_WINDCODE AS stock_code,
    c.CITICS_IND_CODE AS citics_ind_code,
    c.ENTRY_DT AS entry_dt,
    c.REMOVE_DT AS remove_dt,
    c.OPDATE AS opdate
FROM dbo.ASHAREINDUSTRIESCLASSCITICS c
WHERE c.S_INFO_WINDCODE IN ({stock_code_placeholders})
  AND c.CITICS_IND_CODE LIKE ?
ORDER BY c.S_INFO_WINDCODE, c.ENTRY_DT, c.OPDATE;

