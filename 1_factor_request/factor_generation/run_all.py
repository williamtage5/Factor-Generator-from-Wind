from __future__ import annotations

import importlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from .config import FactorConfig
    from .common import clean_csv_dir, cross_sectional_mad_clip_and_zscore, fill_raw_missing_per_factor, write_csv
except ImportError:
    from config import FactorConfig  # type: ignore
    from common import clean_csv_dir, cross_sectional_mad_clip_and_zscore, fill_raw_missing_per_factor, write_csv  # type: ignore

from util.request_from_sqlsever import run_query


FACTOR_MODULES = [
    "halpha_12m",
    "return_1m",
    "return_3m",
    "return_6m",
    "return_12m",
    "wgt_return_1m",
    "wgt_return_3m",
    "wgt_return_6m",
    "wgt_return_12m",
    "exp_wgt_return_1m",
    "exp_wgt_return_3m",
    "exp_wgt_return_6m",
    "exp_wgt_return_12m",
    "momentum_5",
    "momentum_20",
    "momentum_60",
    "reversal_5",
    "volatility_20",
    "downside_vol_20",
    "drawdown_20",
    "turnover_proxy_20",
    "illiq_20",
    "roe",
    "size_log_mcap",
    "ep_ttm",
    "bp_inv",
    "revenue_yoy",
    "netprofit_yoy",
]


def _selected_factors() -> list[str]:
    env = os.getenv("FACTOR_NAMES", "").strip()
    if not env:
        return FACTOR_MODULES
    picked = [x.strip() for x in env.split(",") if x.strip()]
    invalid = [x for x in picked if x not in FACTOR_MODULES]
    if invalid:
        raise ValueError(f"Invalid FACTOR_NAMES entries: {invalid}")
    return picked


def _resolve_import_base() -> str:
    try:
        __package__  # type: ignore[name-defined]
    except Exception:
        return ""
    if __package__:
        return __package__
    return ""


def _read_target_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    trading_days = pd.read_csv(FactorConfig.INPUT_TRADING_DAYS_CSV, encoding="utf-8-sig", low_memory=False)
    if "trade_date" not in trading_days.columns:
        raise ValueError("trading_days.csv must contain trade_date")
    trading_days["trade_date"] = trading_days["trade_date"].astype(str).str.extract(r"(\d{8})", expand=False)
    trading_days = trading_days.dropna(subset=["trade_date"])
    trading_days = trading_days[
        (trading_days["trade_date"] >= FactorConfig.START_DATE) & (trading_days["trade_date"] <= FactorConfig.END_DATE)
    ]
    trading_days = trading_days[["trade_date"]].drop_duplicates().sort_values("trade_date").reset_index(drop=True)
    if trading_days.empty:
        raise ValueError("No target trading days in configured range.")

    td_set = set(trading_days["trade_date"].tolist())
    pool_frames: list[pd.DataFrame] = []
    for f in sorted(FactorConfig.INPUT_POOL_DAILY_DIR.glob("*.csv")):
        td = f.stem
        if td not in td_set:
            continue
        d = pd.read_csv(f, encoding="utf-8-sig", low_memory=False)
        if "stock_code" not in d.columns:
            raise ValueError(f"{f} missing stock_code")
        if "trade_date" not in d.columns:
            d["trade_date"] = td
        d["trade_date"] = d["trade_date"].astype(str).str.extract(r"(\d{8})", expand=False)
        d["stock_code"] = d["stock_code"].astype(str).str.strip()
        pool_frames.append(d[["trade_date", "stock_code"]])

    if not pool_frames:
        raise ValueError("No pool daily files matched factor date range.")

    pool_target = pd.concat(pool_frames, ignore_index=True)
    pool_target = pool_target.dropna(subset=["trade_date", "stock_code"])
    pool_target = pool_target.drop_duplicates(subset=["trade_date", "stock_code"]).sort_values(
        ["trade_date", "stock_code"]
    )
    pool_target = pool_target.reset_index(drop=True)
    return trading_days, pool_target


def _query_trading_days(start_date: str, end_date: str) -> list[str]:
    sql = """
    SELECT TRADE_DAYS AS trade_date
    FROM dbo.ASHARECALENDAR
    WHERE S_INFO_EXCHMARKET = 'SSE'
      AND TRADE_DAYS BETWEEN ? AND ?
    ORDER BY TRADE_DAYS;
    """
    df = run_query(sql, params=[start_date, end_date])
    if df.empty:
        return []
    d = df["trade_date"].astype(str).str.extract(r"(\d{8})", expand=False).dropna().tolist()
    return d


def _extended_date_range(target_start: str, target_end: str, lookback_trading_days: int) -> tuple[str, list[str]]:
    rough_start = (datetime.strptime(target_start, "%Y%m%d") - timedelta(days=max(lookback_trading_days, 1) * 3)).strftime(
        "%Y%m%d"
    )
    days = _query_trading_days(rough_start, target_end)
    if not days:
        raise ValueError(f"Cannot query trading calendar for extended range {rough_start}~{target_end}")
    idx = next((i for i, d in enumerate(days) if d >= target_start), None)
    if idx is None:
        raise ValueError(f"No trading date >= {target_start}")
    from_idx = max(0, idx - max(lookback_trading_days, 0))
    ext_days = days[from_idx:]
    return ext_days[0], ext_days


def _read_sql(path: Path) -> str:
    if not path.exists():
        raise ValueError(f"missing sql file: {path}")
    return path.read_text(encoding="utf-8")


def _run_sql_by_source(
    source: str,
    sql_text: str,
    stock_codes: list[str],
    ext_start: str,
    end_date: str,
) -> pd.DataFrame:
    if not stock_codes:
        return pd.DataFrame()

    parts: list[pd.DataFrame] = []
    chunk_size = 800
    for i in range(0, len(stock_codes), chunk_size):
        chunk = stock_codes[i : i + chunk_size]
        placeholders = ",".join(["?"] * len(chunk))
        sql = sql_text.replace("{stock_code_placeholders}", placeholders)

        if source == "fundamental":
            params: list[Any] = [end_date] + chunk
        elif source == "price_index":
            params = [FactorConfig.BENCHMARK_INDEX_CODE, ext_start, end_date] + chunk
        else:
            params = [ext_start, end_date] + chunk
        parts.append(run_query(sql, params=params))
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def _normalize_df_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in ["trade_date", "announce_date", "report_period"]:
        if c in out.columns:
            out[c] = out[c].astype(str).str.extract(r"(\d{8})", expand=False)
    if "stock_code" in out.columns:
        out["stock_code"] = out["stock_code"].astype(str).str.strip()

    numeric_cols = [
        "close_price",
        "amount",
        "turn_d",
        "turn_float_d",
        "pe_ttm",
        "pb_lf",
        "total_market_cap",
        "roe",
        "revenue_yoy",
        "netprofit_yoy",
        "index_close",
    ]
    for c in numeric_cols:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def _align_financial_to_panel(panel: pd.DataFrame, fin: pd.DataFrame, trading_days: list[str]) -> pd.DataFrame:
    if panel.empty:
        return panel
    out = panel.copy()
    out["trade_date_dt"] = pd.to_datetime(out["trade_date"], format="%Y%m%d", errors="coerce")
    out = out.sort_values(["stock_code", "trade_date_dt"]).reset_index(drop=True)

    if fin.empty:
        for c in ["announce_date", "report_period", "roe", "revenue_yoy", "netprofit_yoy"]:
            out[c] = pd.NA
        return out.drop(columns=["trade_date_dt"], errors="ignore")

    fin = fin.copy()
    fin["announce_date_dt"] = pd.to_datetime(fin["announce_date"], format="%Y%m%d", errors="coerce")
    td_dt = pd.to_datetime(pd.Series(trading_days), format="%Y%m%d", errors="coerce")
    td_map = pd.DataFrame({"announce_date_dt": td_dt})
    td_map["usable_date_dt"] = td_map["announce_date_dt"].shift(-1) if FactorConfig.FIN_USE_TPLUS1 else td_map["announce_date_dt"]
    fin = fin.merge(td_map, on="announce_date_dt", how="left")
    fin = fin.dropna(subset=["usable_date_dt"]).sort_values(["stock_code", "usable_date_dt"]).reset_index(drop=True)

    cols = ["usable_date_dt", "announce_date", "report_period", "roe", "revenue_yoy", "netprofit_yoy"]
    parts: list[pd.DataFrame] = []
    grouped_fin = {k: g for k, g in fin.groupby("stock_code", sort=False)}
    for code, lg in out.groupby("stock_code", sort=False):
        left = lg.sort_values("trade_date_dt").reset_index(drop=True)
        right = grouped_fin.get(code)
        if right is None or right.empty:
            for c in cols:
                if c != "usable_date_dt":
                    left[c] = pd.NA
            parts.append(left)
            continue
        right = right[cols].sort_values("usable_date_dt").reset_index(drop=True)
        aligned = pd.merge_asof(
            left,
            right,
            left_on="trade_date_dt",
            right_on="usable_date_dt",
            direction="backward",
            allow_exact_matches=True,
        )
        parts.append(aligned)
    out = pd.concat(parts, ignore_index=True)
    out = out.drop(columns=["trade_date_dt", "usable_date_dt"], errors="ignore")
    return out


def _build_factor_panel(
    source: str,
    raw_df: pd.DataFrame,
    pool_target: pd.DataFrame,
    ext_days: list[str],
    ext_start: str,
    end_date: str,
) -> pd.DataFrame:
    stock_codes = sorted(pool_target["stock_code"].unique().tolist())
    hist_grid = pd.MultiIndex.from_product([ext_days, stock_codes], names=["trade_date", "stock_code"]).to_frame(index=False)

    d = _normalize_df_cols(raw_df)

    if source == "fundamental":
        panel = hist_grid.copy()
        panel = _align_financial_to_panel(panel=panel, fin=d, trading_days=ext_days)
    elif source == "price_index":
        px_cols = [c for c in ["stock_code", "trade_date", "close_price", "index_close"] if c in d.columns]
        panel = hist_grid.merge(d[px_cols], on=["trade_date", "stock_code"], how="left")
        if "index_close" in panel.columns:
            idx = panel[["trade_date", "index_close"]].drop_duplicates(subset=["trade_date"], keep="last").sort_values("trade_date")
            idx["market_ret_1d"] = pd.to_numeric(idx["index_close"], errors="coerce").pct_change()
            panel = panel.drop(columns=["index_close"], errors="ignore")
            panel = panel.merge(idx[["trade_date", "market_ret_1d"]], on="trade_date", how="left")
    else:
        keep = [c for c in d.columns if c in {"trade_date", "stock_code", "close_price", "amount", "turn_d", "turn_float_d", "pe_ttm", "pb_lf", "total_market_cap"}]
        if not keep:
            panel = hist_grid.copy()
        else:
            panel = hist_grid.merge(d[keep], on=["trade_date", "stock_code"], how="left")

    panel["is_in_pool"] = panel.set_index(["trade_date", "stock_code"]).index.isin(
        pool_target.set_index(["trade_date", "stock_code"]).index
    ).astype(int)
    panel["is_target_day"] = panel["trade_date"].isin(set(pool_target["trade_date"].unique().tolist())).astype(int)
    panel = panel.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    return panel


def _kind_fill_defaults(kind: str) -> tuple[int, int]:
    if kind == "rolling":
        return FactorConfig.ROLLING_FILL_PAST_DAYS, FactorConfig.ROLLING_MAX_FORWARD_DAYS
    if kind == "momentum":
        return FactorConfig.MOMENTUM_FILL_PAST_DAYS, FactorConfig.MOMENTUM_MAX_FORWARD_DAYS
    if kind == "fundamental":
        return FactorConfig.FUNDAMENTAL_FILL_PAST_DAYS, FactorConfig.FUNDAMENTAL_MAX_FORWARD_DAYS
    return FactorConfig.CROSS_SECTION_FILL_PAST_DAYS, FactorConfig.CROSS_SECTION_MAX_FORWARD_DAYS


def _factor_settings(cfg_module: Any) -> dict[str, Any]:
    kind = str(getattr(cfg_module, "FACTOR_KIND", "cross_section"))
    past_days_default, fwd_days_default = _kind_fill_defaults(kind)
    return {
        "factor_kind": kind,
        "window": int(getattr(cfg_module, "WINDOW", 0)),
        "data_source": str(getattr(cfg_module, "DATA_SOURCE", "price")),
        "lookback_days": int(getattr(cfg_module, "LOOKBACK_TRADING_DAYS", FactorConfig.LOOKBACK_TRADING_DAYS)),
        "fill_enabled": bool(getattr(cfg_module, "FILL_MISSING", FactorConfig.FILL_RAW_MISSING)),
        "fill_past_days": int(getattr(cfg_module, "FILL_PAST_DAYS", past_days_default)),
        "fill_max_forward_days": int(getattr(cfg_module, "FILL_MAX_FORWARD_DAYS", fwd_days_default)),
        "fill_use_cs_median": bool(
            getattr(cfg_module, "FILL_USE_CROSS_SECTION_MEDIAN", FactorConfig.FILL_USE_CROSS_SECTION_MEDIAN)
        ),
        "fill_use_global_median": bool(getattr(cfg_module, "FILL_USE_GLOBAL_MEDIAN", FactorConfig.FILL_USE_GLOBAL_MEDIAN)),
        "fill_fallback_value": float(getattr(cfg_module, "FILL_FALLBACK_VALUE", FactorConfig.FILL_FALLBACK_VALUE)),
        "mad_k": float(getattr(cfg_module, "MAD_K", FactorConfig.CS_MAD_K)),
        "standardize": bool(getattr(cfg_module, "STANDARDIZE", FactorConfig.CS_STANDARDIZE)),
    }


def _daily_write_factor(
    factor_df: pd.DataFrame,
    pool_target: pd.DataFrame,
    out_dir: Path,
    value_col: str,
    factor_name: str,
) -> tuple[int, int, int, int]:
    daily_dir = out_dir / "daily"
    clean_csv_dir(daily_dir)
    total_rows = 0
    missing_rows = 0
    file_count = 0
    covered_days = 0

    merged = pool_target.merge(
        factor_df[["trade_date", "stock_code", value_col]],
        on=["trade_date", "stock_code"],
        how="left",
    )
    merged = merged.rename(columns={value_col: factor_name})
    merged = merged.sort_values(["trade_date", "stock_code"]).reset_index(drop=True)

    for td, day_df in merged.groupby("trade_date", sort=True):
        out = day_df[["trade_date", "stock_code", factor_name]].copy()
        out = out.sort_values("stock_code").reset_index(drop=True)
        write_csv(out, daily_dir / f"{td}.csv")
        file_count += 1
        covered_days += 1
        total_rows += int(out.shape[0])
        missing_rows += int(out[factor_name].isna().sum())
    return file_count, total_rows, missing_rows, covered_days


def main() -> None:
    run_started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    import_base = _resolve_import_base()
    run_factors = _selected_factors()
    target_days_df, pool_target = _read_target_inputs()
    target_start = target_days_df["trade_date"].min()
    target_end = target_days_df["trade_date"].max()
    pool_counts = pool_target.groupby("trade_date")["stock_code"].nunique()
    stock_codes = sorted(pool_target["stock_code"].unique().tolist())

    summary: dict[str, object] = {
        "run_started_at": run_started_at,
        "start_date": FactorConfig.START_DATE,
        "end_date": FactorConfig.END_DATE,
        "fin_use_tplus1": FactorConfig.FIN_USE_TPLUS1,
        "input_trading_days_csv": str(FactorConfig.INPUT_TRADING_DAYS_CSV),
        "input_pool_daily_dir": str(FactorConfig.INPUT_POOL_DAILY_DIR),
        "pool_target_rows": int(pool_target.shape[0]),
        "pool_target_days": int(target_days_df.shape[0]),
        "pool_target_codes": int(len(stock_codes)),
        "pool_target_day_count_min": int(pool_counts.min()),
        "pool_target_day_count_max": int(pool_counts.max()),
        "run_factors": run_factors,
        "factors": {},
    }

    for name in run_factors:
        mod_path = f"{import_base}.{name}.main" if import_base else f"factor_generation.{name}.main"
        cfg_path = f"{import_base}.{name}.config" if import_base else f"factor_generation.{name}.config"
        mod = importlib.import_module(mod_path)
        cfg = importlib.import_module(cfg_path)
        settings = _factor_settings(cfg)

        ext_start, ext_days = _extended_date_range(
            target_start=target_start,
            target_end=target_end,
            lookback_trading_days=settings["lookback_days"],
        )
        sql_path = Path(FactorConfig.BASE_DIR / name / "query.sql")
        sql_text = _read_sql(sql_path)
        raw_sql_df = _run_sql_by_source(
            source=settings["data_source"],
            sql_text=sql_text,
            stock_codes=stock_codes,
            ext_start=ext_start,
            end_date=target_end,
        )
        panel = _build_factor_panel(
            source=settings["data_source"],
            raw_df=raw_sql_df,
            pool_target=pool_target,
            ext_days=ext_days,
            ext_start=ext_start,
            end_date=target_end,
        )

        raw = mod.compute(panel)
        raw = raw.sort_values(["trade_date", "stock_code"]).reset_index(drop=True)
        raw = raw.merge(pool_target, on=["trade_date", "stock_code"], how="right")

        raw_missing_before = int(pd.to_numeric(raw["raw"], errors="coerce").isna().sum()) if "raw" in raw.columns else int(raw.shape[0])
        if settings["fill_enabled"]:
            raw = fill_raw_missing_per_factor(
                raw,
                value_col="raw",
                past_days=settings["fill_past_days"],
                max_forward_days=settings["fill_max_forward_days"],
                use_cs_median=settings["fill_use_cs_median"],
                use_global_median=settings["fill_use_global_median"],
                fallback_value=settings["fill_fallback_value"],
            )
        raw_missing_after = int(pd.to_numeric(raw["raw"], errors="coerce").isna().sum())

        proc = cross_sectional_mad_clip_and_zscore(
            raw,
            value_col="raw",
            mad_k=settings["mad_k"],
            standardize=settings["standardize"],
        )
        val_col = "raw_z" if settings["standardize"] else "raw_clip"

        out_dir = FactorConfig.BASE_DIR / name / "output"
        file_count, total_rows, missing_rows, covered_days = _daily_write_factor(
            factor_df=proc,
            pool_target=pool_target,
            out_dir=out_dir,
            value_col=val_col,
            factor_name=name,
        )

        summary["factors"][name] = {
            "factor_kind": settings["factor_kind"],
            "window": settings["window"],
            "data_source": settings["data_source"],
            "lookback_trading_days": settings["lookback_days"],
            "sql_path": str(sql_path),
            "sql_rows": int(raw_sql_df.shape[0]),
            "panel_rows": int(panel.shape[0]),
            "fill_enabled": settings["fill_enabled"],
            "fill_past_days": settings["fill_past_days"],
            "fill_max_forward_days": settings["fill_max_forward_days"],
            "mad_k": settings["mad_k"],
            "standardize": settings["standardize"],
            "raw_missing_before_fill": raw_missing_before,
            "raw_missing_after_fill": raw_missing_after,
            "files_written": file_count,
            "covered_days": covered_days,
            "rows_written": total_rows,
            "missing_written": missing_rows,
            "missing_rate_written": (missing_rows / total_rows if total_rows > 0 else None),
            "output_dir": str(out_dir / "daily"),
        }

    summary_path = FactorConfig.BASE_DIR / "output" / "run_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
