from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from util.request_from_sqlsever import run_query

try:
    from ..config import FactorConfig
except ImportError:
    from config import FactorConfig  # type: ignore

from .io_utils import read_sql_template


def _normalize_yyyymmdd(series: pd.Series) -> pd.Series:
    return series.astype(str).str.extract(r"(\d{8})", expand=False)


def _to_yyyymmdd(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def load_target_trading_days() -> pd.DataFrame:
    df = pd.read_csv(FactorConfig.INPUT_TRADING_DAYS_CSV, encoding="utf-8-sig", low_memory=False)
    if "trade_date" not in df.columns:
        raise ValueError("trading_days.csv must contain trade_date")
    df["trade_date"] = _normalize_yyyymmdd(df["trade_date"])
    df = df.dropna(subset=["trade_date"])
    df = df[(df["trade_date"] >= FactorConfig.START_DATE) & (df["trade_date"] <= FactorConfig.END_DATE)]
    df = df.drop_duplicates(subset=["trade_date"]).sort_values("trade_date").reset_index(drop=True)
    if df.empty:
        raise ValueError("No trading days in configured factor date range.")
    return df


def load_pool_target_daily(target_days: pd.DataFrame) -> pd.DataFrame:
    day_set = set(target_days["trade_date"].tolist())
    target_lut = target_days[["trade_date"]].drop_duplicates().copy()
    frames: list[pd.DataFrame] = []
    for f in sorted(FactorConfig.INPUT_POOL_DAILY_DIR.glob("*.csv")):
        td = f.stem
        if td not in day_set:
            continue
        d = pd.read_csv(f, encoding="utf-8-sig", low_memory=False)
        if "stock_code" not in d.columns:
            raise ValueError(f"{f} missing stock_code")
        d["trade_date"] = _normalize_yyyymmdd(d["trade_date"]) if "trade_date" in d.columns else td
        d["stock_code"] = d["stock_code"].astype(str).str.strip()
        keep_cols = ["trade_date", "stock_code"]
        if "index_weight" in d.columns:
            keep_cols.append("index_weight")
        frames.append(d[keep_cols])

    if not frames:
        raise ValueError("No pool daily files matched factor date range.")

    out = pd.concat(frames, ignore_index=True).dropna(subset=["trade_date", "stock_code"])
    out = out.drop_duplicates(subset=["trade_date", "stock_code"]).sort_values(["trade_date", "stock_code"]).reset_index(drop=True)

    # Ensure every target trading day exists in pool input
    day_present = set(out["trade_date"].unique().tolist())
    missing_days = [d for d in target_lut["trade_date"].tolist() if d not in day_present]
    if missing_days:
        raise ValueError(
            f"Pool daily files missing target trading days: count={len(missing_days)} sample={missing_days[:10]}"
        )

    if "index_weight" not in out.columns:
        out["index_weight"] = pd.NA
    out["is_in_pool"] = 1
    return out


def load_extended_trading_days(start_date: str, end_date: str, lookback_days: int) -> list[str]:
    # Pull target span plus enough pre-history for rolling windows.
    rough_start = _to_yyyymmdd(datetime.strptime(start_date, "%Y%m%d") - timedelta(days=lookback_days * 2))
    sql = """
    SELECT TRADE_DAYS AS trade_date
    FROM dbo.ASHARECALENDAR
    WHERE S_INFO_EXCHMARKET = 'SSE'
      AND TRADE_DAYS BETWEEN ? AND ?
    ORDER BY TRADE_DAYS;
    """
    df = run_query(sql, params=[rough_start, end_date])
    if df.empty:
        raise ValueError("Failed to load trading calendar from database.")
    df["trade_date"] = _normalize_yyyymmdd(df["trade_date"])
    dates = [d for d in df["trade_date"].tolist() if isinstance(d, str)]
    if not dates:
        raise ValueError("Trading calendar query returned no valid dates.")

    # Keep full target range and prepend at most lookback_days trading days before target start.
    start_idx = next((i for i, d in enumerate(dates) if d >= start_date), None)
    if start_idx is None:
        raise ValueError(f"No trading dates >= start_date={start_date} in extended calendar.")
    keep_from = max(0, start_idx - max(int(lookback_days), 0))
    return dates[keep_from:]


def _run_sql_with_chunks(sql_template: str, stock_codes: list[str], head_params: list[str], chunk_size: int = 800) -> pd.DataFrame:
    if not stock_codes:
        return pd.DataFrame()
    parts: list[pd.DataFrame] = []
    for i in range(0, len(stock_codes), chunk_size):
        chunk = stock_codes[i : i + chunk_size]
        placeholders = ",".join(["?"] * len(chunk))
        sql = sql_template.replace("{stock_code_placeholders}", placeholders)
        params = head_params + chunk
        parts.append(run_query(sql, params=params))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def query_price_by_pool(stock_codes: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    sql = read_sql_template(Path(__file__).resolve().parent / "sql" / "query_price_weight_by_pool.sql")
    df = _run_sql_with_chunks(sql, stock_codes, [start_date, end_date])
    if df.empty:
        return pd.DataFrame(columns=["stock_code", "trade_date", "close_price", "volume", "amount"])
    df["stock_code"] = df["stock_code"].astype(str).str.strip()
    df["trade_date"] = _normalize_yyyymmdd(df["trade_date"])
    for c in ["close_price", "volume", "amount"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["stock_code", "trade_date"]).drop_duplicates(subset=["trade_date", "stock_code"], keep="last")
    return df.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)


def query_derivative_by_pool(stock_codes: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    sql = read_sql_template(Path(__file__).resolve().parent / "sql" / "query_derivative_by_pool.sql")
    df = _run_sql_with_chunks(sql, stock_codes, [start_date, end_date])
    if df.empty:
        return pd.DataFrame(columns=["stock_code", "trade_date", "turn_d", "turn_float_d"])
    df["stock_code"] = df["stock_code"].astype(str).str.strip()
    df["trade_date"] = _normalize_yyyymmdd(df["trade_date"])
    for c in ["turn_d", "turn_float_d"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["stock_code", "trade_date"]).drop_duplicates(subset=["trade_date", "stock_code"], keep="last")
    return df.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)


def query_valuation_by_pool(stock_codes: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    sql = read_sql_template(Path(__file__).resolve().parent / "sql" / "query_valuation_by_pool.sql")
    df = _run_sql_with_chunks(sql, stock_codes, [start_date, end_date])
    if df.empty:
        return pd.DataFrame(columns=["stock_code", "trade_date", "pe_ttm", "pb_lf", "total_market_cap"])
    df["stock_code"] = df["stock_code"].astype(str).str.strip()
    df["trade_date"] = _normalize_yyyymmdd(df["trade_date"])
    for c in ["pe_ttm", "pb_lf", "total_market_cap"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["stock_code", "trade_date"]).drop_duplicates(subset=["trade_date", "stock_code"], keep="last")
    return df.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)


def query_financial_by_pool(stock_codes: list[str], end_date: str) -> pd.DataFrame:
    sql = read_sql_template(Path(__file__).resolve().parent / "sql" / "query_financial_indicator_by_pool.sql")
    df = _run_sql_with_chunks(sql, stock_codes, [end_date])
    if df.empty:
        return pd.DataFrame(columns=["stock_code", "announce_date", "report_period", "roe", "revenue_yoy", "netprofit_yoy"])
    df["stock_code"] = df["stock_code"].astype(str).str.strip()
    df["announce_date"] = _normalize_yyyymmdd(df["announce_date"])
    df["report_period"] = _normalize_yyyymmdd(df["report_period"])
    for c in ["roe", "revenue_yoy", "netprofit_yoy"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["stock_code", "announce_date"]).drop_duplicates(subset=["stock_code", "announce_date"], keep="last")
    return df.sort_values(["stock_code", "announce_date"]).reset_index(drop=True)


def query_index_price(index_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    sql = read_sql_template(Path(__file__).resolve().parent / "sql" / "query_index_price.sql")
    df = run_query(sql, params=[index_code, start_date, end_date])
    if df.empty:
        raise ValueError(f"No index price rows for {index_code} between {start_date} and {end_date}")
    df["trade_date"] = _normalize_yyyymmdd(df["trade_date"])
    df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
    df = df.dropna(subset=["trade_date", "close_price"]).drop_duplicates(subset=["trade_date"], keep="last")
    df = df.sort_values("trade_date").reset_index(drop=True)
    df["market_ret_1d"] = df["close_price"].pct_change()
    return df[["trade_date", "market_ret_1d"]]


def _align_financial_asof(
    panel: pd.DataFrame,
    fin: pd.DataFrame,
    trade_dates: list[str],
    tplus1: bool = True,
) -> pd.DataFrame:
    out = panel.copy()
    out["trade_date_dt"] = pd.to_datetime(out["trade_date"], format="%Y%m%d", errors="coerce")
    out = out.sort_values(["stock_code", "trade_date_dt"]).reset_index(drop=True)

    fin = fin.copy()
    fin["announce_date_dt"] = pd.to_datetime(fin["announce_date"], format="%Y%m%d", errors="coerce")
    td_dt = pd.to_datetime(pd.Series(trade_dates), format="%Y%m%d", errors="coerce")
    td_map = pd.DataFrame({"announce_date_dt": td_dt})
    td_map["usable_date_dt"] = td_map["announce_date_dt"] if not tplus1 else td_map["announce_date_dt"].shift(-1)
    fin = fin.merge(td_map, on="announce_date_dt", how="left")
    fin = fin.dropna(subset=["usable_date_dt"]).sort_values(["stock_code", "usable_date_dt"]).reset_index(drop=True)

    aligned_parts: list[pd.DataFrame] = []
    fin_groups = {k: g for k, g in fin.groupby("stock_code", sort=False)}
    cols = ["usable_date_dt", "announce_date", "report_period", "roe", "revenue_yoy", "netprofit_yoy"]

    for stock_code, left_g in out.groupby("stock_code", sort=False):
        left_g = left_g.sort_values("trade_date_dt").reset_index(drop=True)
        right_g = fin_groups.get(stock_code)
        if right_g is None or right_g.empty:
            for c in cols:
                if c != "usable_date_dt":
                    left_g[c] = pd.NA
            aligned_parts.append(left_g)
            continue
        right_g = right_g[cols].sort_values("usable_date_dt").reset_index(drop=True)
        aligned = pd.merge_asof(
            left_g,
            right_g,
            left_on="trade_date_dt",
            right_on="usable_date_dt",
            direction="backward",
            allow_exact_matches=True,
        )
        aligned_parts.append(aligned)

    out = pd.concat(aligned_parts, ignore_index=True)
    out = out.drop(columns=["trade_date_dt", "usable_date_dt"], errors="ignore")
    return out


def _impute_numeric(panel: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = panel.copy()
    out = out.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    out[cols] = out[cols].replace([float("inf"), float("-inf")], pd.NA)

    for col in cols:
        s = pd.to_numeric(out[col], errors="coerce")
        if col in ["volume", "amount", "turn_d", "turn_float_d"]:
            s = s.fillna(0.0)
        s = s.groupby(out["stock_code"], sort=False).transform(lambda x: x.ffill())
        daily_med = s.groupby(out["trade_date"], sort=False).transform("median")
        s = s.fillna(daily_med)
        s = s.fillna(s.median())
        out[col] = s
    return out


def build_base_panel() -> pd.DataFrame:
    target_days = load_target_trading_days()
    pool_target = load_pool_target_daily(target_days)

    target_start = target_days["trade_date"].min()
    target_dates = target_days["trade_date"].tolist()
    end_date = target_days["trade_date"].max()
    ext_days = load_extended_trading_days(
        start_date=target_start,
        end_date=end_date,
        lookback_days=FactorConfig.LOOKBACK_TRADING_DAYS,
    )
    ext_start = ext_days[0]

    stock_codes = sorted(pool_target["stock_code"].unique().tolist())
    full_pool_target = pool_target[["trade_date", "stock_code", "index_weight", "is_in_pool"]].copy()
    px = query_price_by_pool(stock_codes, ext_start, end_date)
    drv = query_derivative_by_pool(stock_codes, ext_start, end_date)
    val = query_valuation_by_pool(stock_codes, ext_start, end_date)
    fin = query_financial_by_pool(stock_codes, end_date)
    idx = query_index_price(FactorConfig.BENCHMARK_INDEX_CODE, ext_start, end_date)

    # Full history grid to avoid dropping rows on suspended/non-trading stock records.
    hist_grid = pd.MultiIndex.from_product(
        [ext_days, stock_codes],
        names=["trade_date", "stock_code"],
    ).to_frame(index=False)

    panel = hist_grid.merge(px, on=["trade_date", "stock_code"], how="left")
    panel = panel.merge(val, on=["trade_date", "stock_code"], how="left")
    panel = panel.merge(drv, on=["trade_date", "stock_code"], how="left")
    panel = panel.merge(idx, on="trade_date", how="left")

    panel = _align_financial_asof(
        panel=panel,
        fin=fin,
        trade_dates=ext_days,
        tplus1=FactorConfig.FIN_USE_TPLUS1,
    )

    panel = _impute_numeric(
        panel,
        cols=[
            "close_price",
            "volume",
            "amount",
            "turn_d",
            "turn_float_d",
            "pe_ttm",
            "pb_lf",
            "total_market_cap",
            "roe",
            "revenue_yoy",
            "netprofit_yoy",
        ],
    )

    panel["announce_date"] = panel["announce_date"].fillna(panel["trade_date"])
    panel["report_period"] = panel["report_period"].fillna(panel["announce_date"])

    panel["is_target_day"] = panel["trade_date"].isin(set(target_dates)).astype(int)
    panel = panel.merge(full_pool_target, on=["trade_date", "stock_code"], how="left")
    panel["is_in_pool"] = panel["is_in_pool"].fillna(0).astype(int)

    panel = panel.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    return panel
