from __future__ import annotations

import os
from pathlib import Path


class FactorConfig:
    BASE_DIR = Path(__file__).resolve().parent
    PROJECT_ROOT = BASE_DIR.parent
    MISSION_ROOT = PROJECT_ROOT.parent

    UNIVERSE_OUTPUT_DIR = MISSION_ROOT / "0_universal_information_definition" / "outputs"
    INPUT_TRADING_DAYS_CSV = Path(
        os.getenv("FACTOR_INPUT_TRADING_DAYS_CSV", str(UNIVERSE_OUTPUT_DIR / "trading_days.csv"))
    )
    INPUT_POOL_DAILY_DIR = Path(
        os.getenv("FACTOR_INPUT_POOL_DAILY_DIR", str(UNIVERSE_OUTPUT_DIR / "stock_pool_daily"))
    )

    OUTPUT_DIR = BASE_DIR / "output"

    START_DATE = os.getenv("FACTOR_START_DATE", "20230101")
    END_DATE = os.getenv("FACTOR_END_DATE", "20231231")
    BENCHMARK_INDEX_CODE = os.getenv("FACTOR_BENCHMARK_INDEX_CODE", "000001.SH")

    # For momentum/HAlpha history requirements:
    # 12m momentum needs around 240 trading days, HAlpha 60m needs much longer monthly history.
    # We query with buffer and then slice to [START_DATE, END_DATE] at output stage.
    LOOKBACK_TRADING_DAYS = int(os.getenv("FACTOR_LOOKBACK_TRADING_DAYS", "1600"))

    # Financial data can only be used from next trading day after ANN_DT.
    FIN_USE_TPLUS1 = True

    # Missing-value fill (applied per factor independently)
    FILL_RAW_MISSING = os.getenv("FACTOR_FILL_RAW_MISSING", "1") == "1"
    FILL_USE_CROSS_SECTION_MEDIAN = os.getenv("FACTOR_FILL_USE_CROSS_SECTION_MEDIAN", "1") == "1"
    FILL_USE_GLOBAL_MEDIAN = os.getenv("FACTOR_FILL_USE_GLOBAL_MEDIAN", "1") == "1"
    FILL_FALLBACK_VALUE = float(os.getenv("FACTOR_FILL_FALLBACK_VALUE", "0.0"))

    # Adaptive defaults by factor kind (can be overridden by per-factor config variables)
    ROLLING_FILL_PAST_DAYS = int(os.getenv("FACTOR_ROLLING_FILL_PAST_DAYS", "20"))
    MOMENTUM_FILL_PAST_DAYS = int(os.getenv("FACTOR_MOMENTUM_FILL_PAST_DAYS", "60"))
    FUNDAMENTAL_FILL_PAST_DAYS = int(os.getenv("FACTOR_FUNDAMENTAL_FILL_PAST_DAYS", "120"))
    CROSS_SECTION_FILL_PAST_DAYS = int(os.getenv("FACTOR_CROSS_SECTION_FILL_PAST_DAYS", "10"))

    ROLLING_MAX_FORWARD_DAYS = int(os.getenv("FACTOR_ROLLING_MAX_FORWARD_DAYS", "5"))
    MOMENTUM_MAX_FORWARD_DAYS = int(os.getenv("FACTOR_MOMENTUM_MAX_FORWARD_DAYS", "10"))
    FUNDAMENTAL_MAX_FORWARD_DAYS = int(os.getenv("FACTOR_FUNDAMENTAL_MAX_FORWARD_DAYS", "250"))
    CROSS_SECTION_MAX_FORWARD_DAYS = int(os.getenv("FACTOR_CROSS_SECTION_MAX_FORWARD_DAYS", "3"))

    # Cross-sectional operations (MAD clipping + z-score standardization)
    CS_MAD_K = float(os.getenv("FACTOR_CS_MAD_K", "5.0"))
    CS_STANDARDIZE = os.getenv("FACTOR_CS_STANDARDIZE", "1") == "1"
