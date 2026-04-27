from __future__ import annotations

import os
from pathlib import Path


class OrthoConfig:
    BASE_DIR = Path(__file__).resolve().parent
    PROJECT_ROOT = BASE_DIR.parent

    UNIVERSAL_OUTPUT_DIR = PROJECT_ROOT / "0_universal_information_definition" / "outputs"
    FACTOR_ROOT_DIR = PROJECT_ROOT / "1_factor_request" / "factor_generation"

    INPUT_TRADING_DAYS_CSV = Path(
        os.getenv("ORTHO_INPUT_TRADING_DAYS_CSV", str(UNIVERSAL_OUTPUT_DIR / "trading_days.csv"))
    )
    INPUT_POOL_DAILY_DIR = Path(
        os.getenv("ORTHO_INPUT_POOL_DAILY_DIR", str(UNIVERSAL_OUTPUT_DIR / "stock_pool_daily"))
    )
    INPUT_FACTOR_ROOT_DIR = Path(os.getenv("ORTHO_INPUT_FACTOR_ROOT_DIR", str(FACTOR_ROOT_DIR)))

    OUTPUT_DIR = BASE_DIR / "output"
    OUTPUT_DAILY_DIR = OUTPUT_DIR / "daily"
    OUTPUT_FACTOR_DAILY_DIR = OUTPUT_DIR / "factor_daily"
    OUTPUT_META_DIR = OUTPUT_DIR / "meta"

    SQL_DIR = BASE_DIR / "sql"
    SQL_MV_DAILY = SQL_DIR / "query_mv_s_val_mv.sql"
    SQL_IND_DICT = SQL_DIR / "query_industry_dict.sql"
    SQL_IND_LIFECYCLE = SQL_DIR / "query_industry_lifecycle.sql"

    START_DATE = os.getenv("ORTHO_START_DATE", "20230101")
    END_DATE = os.getenv("ORTHO_END_DATE", "20231231")

    # Regression spec
    USE_WLS = os.getenv("ORTHO_USE_WLS", "1") == "1"
    WLS_WEIGHT = os.getenv("ORTHO_WLS_WEIGHT", "sqrt_mv")  # sqrt_mv | equal
    MV_COL = os.getenv("ORTHO_MV_COL", "mv_raw")
    MV_LOG_COL = "ln_mv"

    # Missing handling during regression
    INDUSTRY_UNKNOWN_COL = "ind_unknown"
    MIN_SAMPLE_BUFFER = int(os.getenv("ORTHO_MIN_SAMPLE_BUFFER", "5"))

    # Residual post-process (applied independently per factor)
    FILL_RESID_MISSING = os.getenv("ORTHO_FILL_RESID_MISSING", "1") == "1"
    FILL_USE_CROSS_SECTION_MEDIAN = os.getenv("ORTHO_FILL_USE_CROSS_SECTION_MEDIAN", "1") == "1"
    FILL_USE_GLOBAL_MEDIAN = os.getenv("ORTHO_FILL_USE_GLOBAL_MEDIAN", "1") == "1"
    FILL_FALLBACK_VALUE = float(os.getenv("ORTHO_FILL_FALLBACK_VALUE", "0.0"))
    FILL_PAST_DAYS = int(os.getenv("ORTHO_FILL_PAST_DAYS", "20"))
    FILL_MAX_FORWARD_DAYS = int(os.getenv("ORTHO_FILL_MAX_FORWARD_DAYS", "5"))

    CS_MAD_K = float(os.getenv("ORTHO_CS_MAD_K", "5.0"))
    CS_STANDARDIZE = os.getenv("ORTHO_CS_STANDARDIZE", "1") == "1"

