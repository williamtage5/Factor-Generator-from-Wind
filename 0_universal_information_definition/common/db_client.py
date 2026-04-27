from __future__ import annotations

from typing import Iterable

import pandas as pd
import pyodbc

try:
    from ..config import SQLConfig
except ImportError:
    from config import SQLConfig  # type: ignore


def _pick_driver() -> str:
    drivers = [d for d in pyodbc.drivers() if "SQL Server" in d]
    preferred = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "SQL Server",
    ]
    for item in preferred:
        if item in drivers:
            return item
    if drivers:
        return drivers[-1]
    raise RuntimeError("No SQL Server ODBC driver found on this machine.")


def get_connection() -> pyodbc.Connection:
    driver = _pick_driver()

    if SQLConfig.SQL_USERNAME and SQLConfig.SQL_PASSWORD:
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={SQLConfig.SQL_SERVER};"
            f"DATABASE={SQLConfig.SQL_DATABASE};"
            f"UID={SQLConfig.SQL_USERNAME};"
            f"PWD={SQLConfig.SQL_PASSWORD};"
            "TrustServerCertificate=yes;"
        )
    else:
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={SQLConfig.SQL_SERVER};"
            f"DATABASE={SQLConfig.SQL_DATABASE};"
            "Trusted_Connection=yes;"
            "TrustServerCertificate=yes;"
        )
    return pyodbc.connect(conn_str)


def run_query(sql: str, params: Iterable | None = None) -> pd.DataFrame:
    with get_connection() as conn:
        if params is None:
            return pd.read_sql(sql, conn)
        return pd.read_sql(sql, conn, params=params)

