from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

try:
    from ..common.db_client import run_query
    from ..common.io_csv import clean_csv_dir, write_csv
    from ..common.validators import validate_config
    from ..config import AppConfig
    from ..trading_days.main import build_trading_days
except ImportError:
    import sys

    THIS_FILE = Path(__file__).resolve()
    PROJECT_ROOT = THIS_FILE.parents[1]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from common.db_client import run_query  # type: ignore
    from common.io_csv import clean_csv_dir, write_csv  # type: ignore
    from common.validators import validate_config  # type: ignore
    from config import AppConfig  # type: ignore
    from trading_days.main import build_trading_days  # type: ignore


def build_daily_pool(trading_days: pd.DataFrame) -> pd.DataFrame:
    if trading_days.empty:
        raise ValueError("trading_days is empty.")

    t_start = trading_days["trade_date"].min()
    t_end = trading_days["trade_date"].max()

    sql = (Path(__file__).resolve().parent / "query_daily_dynamic.sql").read_text(encoding="utf-8")
    df = run_query(
        sql,
        params=[
            AppConfig.CALENDAR_MARKET,
            t_start,
            t_end,
            AppConfig.UNIVERSE_CODE,
            AppConfig.UNIVERSE_CODE,
        ],
    )
    if df.empty:
        raise ValueError(
            f"No stock pool data found for code={AppConfig.UNIVERSE_CODE}, "
            f"range={t_start}-{t_end}"
        )

    for c in ["trade_date", "effective_weight_date"]:
        df[c] = df[c].astype(str).str.extract(r"(\d{8})", expand=False)
    df["stock_code"] = df["stock_code"].astype(str).str.strip()

    df = (
        df.dropna(subset=["trade_date", "effective_weight_date", "stock_code"])
        .drop_duplicates(subset=["trade_date", "stock_code"], keep="last")
        .sort_values(["trade_date", "stock_code"])
        .reset_index(drop=True)
    )
    if df.empty:
        raise ValueError("Daily stock pool became empty after normalization.")

    return df


def build_stock_code_effective_dates(daily_pool: pd.DataFrame) -> pd.DataFrame:
    g = daily_pool.groupby("stock_code", as_index=False)
    summary = g.agg(
        first_effective_trade_date=("trade_date", "min"),
        last_effective_trade_date=("trade_date", "max"),
        active_trade_days=("trade_date", "nunique"),
    )
    return summary.sort_values(["first_effective_trade_date", "stock_code"]).reset_index(drop=True)


def run_validations(daily_pool: pd.DataFrame, trading_days: pd.DataFrame) -> dict[str, object]:
    issues: list[str] = []

    td_set = set(trading_days["trade_date"].tolist())
    pool_td_set = set(daily_pool["trade_date"].tolist())
    missing_days = sorted(td_set - pool_td_set)
    extra_days = sorted(pool_td_set - td_set)
    if missing_days:
        issues.append(f"missing_pool_days={len(missing_days)} sample={missing_days[:10]}")
    if extra_days:
        issues.append(f"extra_pool_days={len(extra_days)} sample={extra_days[:10]}")

    bad_future = daily_pool[daily_pool["effective_weight_date"] > daily_pool["trade_date"]]
    if not bad_future.empty:
        issues.append(f"future_leakage_rows={len(bad_future)}")

    dup_cnt = int(daily_pool.duplicated(["trade_date", "stock_code"]).sum())
    if dup_cnt > 0:
        issues.append(f"duplicated_trade_date_stock_code={dup_cnt}")

    counts = daily_pool.groupby("trade_date")["stock_code"].nunique()
    non_300 = counts[counts != 300]
    if not non_300.empty:
        sample = [(idx, int(v)) for idx, v in non_300.head(10).items()]
        issues.append(f"daily_count_not_300_days={len(non_300)} sample={sample}")

    return {
        "trading_days_total": int(len(trading_days)),
        "pool_days_total": int(counts.shape[0]),
        "pool_rows_total": int(len(daily_pool)),
        "pool_unique_codes": int(daily_pool["stock_code"].nunique()),
        "pool_start_date": str(daily_pool["trade_date"].min()),
        "pool_end_date": str(daily_pool["trade_date"].max()),
        "daily_count_min": int(counts.min()),
        "daily_count_max": int(counts.max()),
        "issues": issues,
    }


def main() -> None:
    validate_config()
    AppConfig.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    clean_csv_dir(AppConfig.OUTPUT_DAILY_DIR)

    trading_days = build_trading_days()
    write_csv(trading_days, AppConfig.OUTPUT_DIR / "trading_days.csv")

    daily_pool = build_daily_pool(trading_days)

    for trade_date, day_df in daily_pool.groupby("trade_date", sort=True):
        write_csv(
            day_df[["trade_date", "stock_code", "index_weight", "effective_weight_date"]],
            AppConfig.OUTPUT_DAILY_DIR / f"{trade_date}.csv",
        )

    codes = build_stock_code_effective_dates(daily_pool)
    write_csv(codes, AppConfig.OUTPUT_DIR / "stock_pool_codes.csv")

    summary = run_validations(daily_pool, trading_days)
    summary.update(
        {
            "universe_code": AppConfig.UNIVERSE_CODE,
            "universe_mode": AppConfig.UNIVERSE_MODE,
            "calendar_market": AppConfig.CALENDAR_MARKET,
            "start_date": AppConfig.START_DATE,
            "end_date": AppConfig.END_DATE,
        }
    )
    summary_file = AppConfig.OUTPUT_DIR / "run_summary.json"
    summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"summary_file={summary_file}")


if __name__ == "__main__":
    main()
