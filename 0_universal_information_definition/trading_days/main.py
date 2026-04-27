from __future__ import annotations

from pathlib import Path

import pandas as pd

try:
    from ..common.db_client import run_query
    from ..common.io_csv import write_csv
    from ..common.validators import validate_config
    from ..config import AppConfig
except ImportError:
    import sys

    THIS_FILE = Path(__file__).resolve()
    PROJECT_ROOT = THIS_FILE.parents[1]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from common.db_client import run_query  # type: ignore
    from common.io_csv import write_csv  # type: ignore
    from common.validators import validate_config  # type: ignore
    from config import AppConfig  # type: ignore


def build_trading_days() -> pd.DataFrame:
    sql = (Path(__file__).resolve().parent / "query.sql").read_text(encoding="utf-8")
    df = run_query(
        sql,
        params=[AppConfig.CALENDAR_MARKET, AppConfig.START_DATE, AppConfig.END_DATE],
    )
    if df.empty:
        raise ValueError(
            f"No trading days found for market={AppConfig.CALENDAR_MARKET}, "
            f"range={AppConfig.START_DATE}-{AppConfig.END_DATE}"
        )
    df["trade_date"] = df["trade_date"].astype(str).str.extract(r"(\d{8})", expand=False)
    df = df.dropna(subset=["trade_date"]).drop_duplicates().sort_values("trade_date")
    if df.empty:
        raise ValueError("Trading days became empty after date normalization.")
    return df.reset_index(drop=True)


def main() -> None:
    validate_config()
    trade_days = build_trading_days()
    out_file = AppConfig.OUTPUT_DIR / "trading_days.csv"
    write_csv(trade_days, out_file)
    print(
        f"trading_days rows={len(trade_days)} "
        f"start={trade_days['trade_date'].min()} end={trade_days['trade_date'].max()} "
        f"output={out_file}"
    )


if __name__ == "__main__":
    main()
