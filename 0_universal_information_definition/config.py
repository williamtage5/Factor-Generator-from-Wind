from __future__ import annotations

import os
from pathlib import Path


class SQLConfig:
    """SQL Server connection configuration."""

    SQL_SERVER = os.getenv("SQL_SERVER", ".")
    SQL_DATABASE = os.getenv("SQL_DATABASE", "winddb20260405")
    SQL_USERNAME = os.getenv("SQL_USERNAME", "")
    SQL_PASSWORD = os.getenv("SQL_PASSWORD", "")


class AppConfig:
    """Universe building configuration."""

    # Use a short default range for quick verification; override by env in production.
    START_DATE = os.getenv("START_DATE", "20230101")
    END_DATE = os.getenv("END_DATE", "20231231")

    CALENDAR_MARKET = os.getenv("CALENDAR_MARKET", "SSE")
    UNIVERSE_SOURCE = os.getenv("UNIVERSE_SOURCE", "index")
    UNIVERSE_CODE = os.getenv("UNIVERSE_CODE", "000300.SH")
    UNIVERSE_MODE = os.getenv("UNIVERSE_MODE", "daily_dynamic")

    BASE_DIR = Path(__file__).resolve().parent
    OUTPUT_DIR = BASE_DIR / "outputs"
    OUTPUT_DAILY_DIR = OUTPUT_DIR / "stock_pool_daily"
