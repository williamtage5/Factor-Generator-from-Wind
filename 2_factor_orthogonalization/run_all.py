from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from .config import OrthoConfig
except ImportError:
    from config import OrthoConfig  # type: ignore


KEY_COLS = ["trade_date", "stock_code"]


def _normalize_yyyymmdd(series: pd.Series) -> pd.Series:
    return series.astype(str).str.extract(r"(\d{8})", expand=False)


def _clean_csv_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for f in path.glob("*.csv"):
        f.unlink(missing_ok=True)


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _import_run_query():
    util_root = OrthoConfig.PROJECT_ROOT / "1_factor_request"
    if str(util_root) not in sys.path:
        sys.path.append(str(util_root))
    from util.request_from_sqlsever import run_query

    return run_query


RUN_QUERY = _import_run_query()


def _read_target_inputs() -> tuple[list[str], pd.DataFrame]:
    trading_days = pd.read_csv(OrthoConfig.INPUT_TRADING_DAYS_CSV, encoding="utf-8-sig", low_memory=False)
    if "trade_date" not in trading_days.columns:
        raise ValueError("trading_days.csv must contain trade_date")
    trading_days["trade_date"] = _normalize_yyyymmdd(trading_days["trade_date"])
    trading_days = trading_days.dropna(subset=["trade_date"])
    trading_days = trading_days[
        (trading_days["trade_date"] >= OrthoConfig.START_DATE) & (trading_days["trade_date"] <= OrthoConfig.END_DATE)
    ]
    trading_days = trading_days[["trade_date"]].drop_duplicates().sort_values("trade_date")
    td_list = trading_days["trade_date"].tolist()
    if not td_list:
        raise ValueError("No target trading days in configured range.")

    td_set = set(td_list)
    pool_frames: list[pd.DataFrame] = []
    for f in sorted(OrthoConfig.INPUT_POOL_DAILY_DIR.glob("*.csv")):
        td = f.stem
        if td not in td_set:
            continue
        d = pd.read_csv(f, encoding="utf-8-sig", low_memory=False)
        if "stock_code" not in d.columns:
            raise ValueError(f"{f} missing stock_code")
        if "trade_date" not in d.columns:
            d["trade_date"] = td
        d["trade_date"] = _normalize_yyyymmdd(d["trade_date"])
        d["stock_code"] = d["stock_code"].astype(str).str.strip()
        pool_frames.append(d[["trade_date", "stock_code"]])
    if not pool_frames:
        raise ValueError("No pool daily files matched configured date range.")

    pool_target = pd.concat(pool_frames, ignore_index=True)
    pool_target = pool_target.dropna(subset=KEY_COLS)
    pool_target = pool_target.drop_duplicates(subset=KEY_COLS).sort_values(KEY_COLS).reset_index(drop=True)
    return td_list, pool_target


def _available_factor_dirs() -> list[str]:
    out: list[str] = []
    for d in sorted(OrthoConfig.INPUT_FACTOR_ROOT_DIR.iterdir()):
        if not d.is_dir():
            continue
        daily_dir = d / "output" / "daily"
        if daily_dir.exists():
            out.append(d.name)
    return out


def _selected_factors() -> list[str]:
    available = _available_factor_dirs()
    env = os.getenv("FACTOR_NAMES", "").strip()
    if not env:
        return available
    picked = [x.strip() for x in env.split(",") if x.strip()]
    invalid = [x for x in picked if x not in available]
    if invalid:
        raise ValueError(f"Invalid FACTOR_NAMES entries: {invalid}")
    return picked


def _read_sql(path: Path) -> str:
    if not path.exists():
        raise ValueError(f"missing sql file: {path}")
    return path.read_text(encoding="utf-8")


def _query_mv_panel(td_list: list[str], pool_target: pd.DataFrame) -> pd.DataFrame:
    sql_template = _read_sql(OrthoConfig.SQL_MV_DAILY)
    pool_map = {k: g["stock_code"].tolist() for k, g in pool_target.groupby("trade_date", sort=False)}
    parts: list[pd.DataFrame] = []
    chunk_size = 800

    for td in td_list:
        codes = pool_map.get(td, [])
        if not codes:
            continue
        for i in range(0, len(codes), chunk_size):
            chunk = codes[i : i + chunk_size]
            placeholders = ",".join(["?"] * len(chunk))
            sql = sql_template.replace("{stock_code_placeholders}", placeholders)
            params: list[Any] = [td] + chunk
            part = RUN_QUERY(sql, params=params)
            parts.append(part)

    if not parts:
        return pool_target.assign(mv_raw=np.nan)[KEY_COLS + [OrthoConfig.MV_COL]]

    mv = pd.concat(parts, ignore_index=True)
    mv["trade_date"] = _normalize_yyyymmdd(mv["trade_date"])
    mv["stock_code"] = mv["stock_code"].astype(str).str.strip()
    mv[OrthoConfig.MV_COL] = pd.to_numeric(mv[OrthoConfig.MV_COL], errors="coerce")
    mv = mv.dropna(subset=KEY_COLS).drop_duplicates(subset=KEY_COLS, keep="last")

    out = pool_target.merge(mv[KEY_COLS + [OrthoConfig.MV_COL]], on=KEY_COLS, how="left")
    return out


def _query_industry_dict() -> pd.DataFrame:
    sql = _read_sql(OrthoConfig.SQL_IND_DICT)
    d = RUN_QUERY(sql, params=["b10%", 2])
    if d.empty:
        raise ValueError("Industry dictionary query returned empty.")
    d["citic_l1_code"] = d["citic_l1_code"].astype(str).str.strip()
    d["citic_l1_name"] = d["citic_l1_name"].astype(str).str.strip()
    d = d.drop_duplicates(subset=["citic_l1_code"]).sort_values("citic_l1_code").reset_index(drop=True)
    return d[["citic_l1_code", "citic_l1_name"]]


def _query_industry_lifecycle(stock_codes: list[str]) -> pd.DataFrame:
    if not stock_codes:
        return pd.DataFrame(columns=["stock_code", "citics_ind_code", "entry_dt", "remove_dt", "opdate", "citic_l1_code"])

    sql_template = _read_sql(OrthoConfig.SQL_IND_LIFECYCLE)
    parts: list[pd.DataFrame] = []
    chunk_size = 800

    for i in range(0, len(stock_codes), chunk_size):
        chunk = stock_codes[i : i + chunk_size]
        placeholders = ",".join(["?"] * len(chunk))
        sql = sql_template.replace("{stock_code_placeholders}", placeholders)
        params = chunk + ["b10%"]
        parts.append(RUN_QUERY(sql, params=params))

    d = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if d.empty:
        return d
    d["stock_code"] = d["stock_code"].astype(str).str.strip()
    d["citics_ind_code"] = d["citics_ind_code"].astype(str).str.strip()
    d["citic_l1_code"] = d["citics_ind_code"].str.slice(0, 4) + "000000000000"
    d["entry_dt"] = _normalize_yyyymmdd(d["entry_dt"])
    d["remove_dt"] = _normalize_yyyymmdd(d["remove_dt"])
    d["opdate"] = pd.to_datetime(d["opdate"], errors="coerce")
    return d


def _pick_industry_effective_rows(day_rows: pd.DataFrame, td: str) -> pd.DataFrame:
    if day_rows.empty:
        return day_rows
    m1 = day_rows["entry_dt"].notna() & (day_rows["entry_dt"] <= td)
    m2 = day_rows["remove_dt"].isna() | (day_rows["remove_dt"] >= td)
    eff = day_rows[m1 & m2].copy()
    if eff.empty:
        return eff
    eff = eff.sort_values(["stock_code", "entry_dt", "opdate", "citics_ind_code"])
    eff = eff.groupby("stock_code", as_index=False).tail(1)
    return eff


def _build_industry_onehot_panel(td_list: list[str], pool_target: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    ind_dict = _query_industry_dict()
    ind_codes = ind_dict["citic_l1_code"].tolist()
    lifecycle = _query_industry_lifecycle(sorted(pool_target["stock_code"].unique().tolist()))
    lifecycle = lifecycle[lifecycle["citic_l1_code"].isin(ind_codes)].copy()

    day_parts: list[pd.DataFrame] = []
    pool_by_day = {k: g.copy() for k, g in pool_target.groupby("trade_date", sort=False)}

    for td in td_list:
        day_pool = pool_by_day[td][KEY_COLS].copy()
        day_life = lifecycle[lifecycle["stock_code"].isin(day_pool["stock_code"])].copy() if not lifecycle.empty else lifecycle
        picked = _pick_industry_effective_rows(day_life, td)
        picked = picked[["stock_code", "citic_l1_code"]] if not picked.empty else pd.DataFrame(columns=["stock_code", "citic_l1_code"])
        day = day_pool.merge(picked, on="stock_code", how="left")
        day["citic_l1_code"] = day["citic_l1_code"].fillna("unknown")
        cats = pd.Categorical(day["citic_l1_code"], categories=ind_codes + ["unknown"])
        onehot = pd.get_dummies(cats, prefix="ind")
        onehot.index = day.index
        day = pd.concat([day[KEY_COLS], onehot], axis=1)
        day_parts.append(day)

    out = pd.concat(day_parts, ignore_index=True)
    ind_cols = [c for c in out.columns if c.startswith("ind_")]
    for c in ind_cols:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0).astype(int)
    out = out.drop_duplicates(subset=KEY_COLS).sort_values(KEY_COLS).reset_index(drop=True)
    return out, ind_cols


def _factor_daily_dir(factor_name: str) -> Path:
    return OrthoConfig.INPUT_FACTOR_ROOT_DIR / factor_name / "output" / "daily"


def _read_factor_value_column(sample_file: Path) -> str:
    d = pd.read_csv(sample_file, encoding="utf-8-sig", low_memory=False, nrows=20)
    cols = [c for c in d.columns if c not in KEY_COLS]
    if not cols:
        raise ValueError(f"No factor value column in {sample_file}")
    return cols[0]


def _load_factor_panel(factor_name: str, td_list: list[str], pool_target: pd.DataFrame) -> pd.DataFrame:
    daily_dir = _factor_daily_dir(factor_name)
    sample = next(iter(sorted(daily_dir.glob("*.csv"))), None)
    if sample is None:
        raise ValueError(f"No daily factor files for {factor_name}")
    value_col = _read_factor_value_column(sample)

    parts: list[pd.DataFrame] = []
    for td in td_list:
        f = daily_dir / f"{td}.csv"
        if not f.exists():
            continue
        d = pd.read_csv(f, encoding="utf-8-sig", low_memory=False)
        if "stock_code" not in d.columns:
            raise ValueError(f"{f} missing stock_code")
        if "trade_date" not in d.columns:
            d["trade_date"] = td
        d["trade_date"] = _normalize_yyyymmdd(d["trade_date"])
        d["stock_code"] = d["stock_code"].astype(str).str.strip()
        if value_col not in d.columns:
            alt_cols = [c for c in d.columns if c not in KEY_COLS]
            if not alt_cols:
                raise ValueError(f"No factor value column in {f}")
            value_col = alt_cols[0]
        d[value_col] = pd.to_numeric(d[value_col], errors="coerce")
        d = d[KEY_COLS + [value_col]].dropna(subset=KEY_COLS).drop_duplicates(subset=KEY_COLS, keep="last")
        parts.append(d)

    raw = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=KEY_COLS + [value_col])
    raw = raw.rename(columns={value_col: factor_name})
    panel = pool_target.merge(raw, on=KEY_COLS, how="left")
    return panel.sort_values(KEY_COLS).reset_index(drop=True)


def _solve_wls_resid(y: np.ndarray, x: np.ndarray, w: np.ndarray) -> np.ndarray:
    sw = np.sqrt(np.clip(w, 1e-12, None))
    yw = y * sw
    xw = x * sw[:, None]
    beta, _, _, _ = np.linalg.lstsq(xw, yw, rcond=None)
    return y - x @ beta


def _regress_one_factor(
    panel: pd.DataFrame,
    factor_name: str,
    td_list: list[str],
    ind_cols: list[str],
    skip_mv_neutralize: set[str],
    skip_ind_neutralize: set[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    df = panel.copy()
    df[factor_name] = pd.to_numeric(df[factor_name], errors="coerce")
    mv = pd.to_numeric(df[OrthoConfig.MV_COL], errors="coerce")
    df[OrthoConfig.MV_COL] = mv
    df[OrthoConfig.MV_LOG_COL] = np.where(mv > 0, np.log(mv), np.nan)

    use_mv = factor_name not in skip_mv_neutralize
    use_ind = factor_name not in skip_ind_neutralize
    mv_col = OrthoConfig.MV_LOG_COL if use_mv else None

    resid_col = f"{factor_name}_resid_raw"
    df[resid_col] = np.nan

    day_stats: list[dict[str, Any]] = []

    for td in td_list:
        day = df[df["trade_date"] == td].copy()
        if day.empty:
            continue

        x_cols: list[str] = []
        if mv_col is not None:
            x_cols.append(mv_col)
        if use_ind:
            day_ind_cols = [c for c in ind_cols if c in day.columns and int(day[c].sum()) > 0]
            if day_ind_cols:
                day_ind_cols = day_ind_cols[1:]
                x_cols.extend(day_ind_cols)

        work_cols = [factor_name, OrthoConfig.MV_COL] + x_cols
        work = day[work_cols].copy()

        # MV missing means this sample is excluded from orthogonalization.
        work = work[work[OrthoConfig.MV_COL] > 0]
        work = work.dropna(subset=[factor_name] + x_cols)

        n = int(work.shape[0])
        p = len(x_cols) + 1  # intercept
        min_n = p + OrthoConfig.MIN_SAMPLE_BUFFER

        if n < min_n:
            day_stats.append({"trade_date": td, "samples": n, "params": p, "status": "insufficient_sample"})
            continue

        y = work[factor_name].to_numpy(dtype=float)
        if float(np.nanstd(y)) <= 1e-12:
            day_stats.append({"trade_date": td, "samples": n, "params": p, "status": "flat_y"})
            continue

        x = np.ones((n, p), dtype=float)
        if x_cols:
            x[:, 1:] = work[x_cols].to_numpy(dtype=float)

        if OrthoConfig.USE_WLS and OrthoConfig.WLS_WEIGHT == "sqrt_mv":
            w = np.sqrt(work[OrthoConfig.MV_COL].to_numpy(dtype=float))
        else:
            w = np.ones(n, dtype=float)

        try:
            resid = _solve_wls_resid(y, x, w)
        except np.linalg.LinAlgError:
            day_stats.append({"trade_date": td, "samples": n, "params": p, "status": "linalg_error"})
            continue

        aligned = pd.Series(index=work.index, data=resid)
        day_idx = day.index
        df.loc[day_idx, resid_col] = aligned.reindex(day_idx).to_numpy()
        day_stats.append({"trade_date": td, "samples": n, "params": p, "status": "ok"})

    stats = pd.DataFrame(day_stats)
    stat: dict[str, Any] = {
        "samples_days": int(stats.shape[0]),
        "ok_days": int((stats["status"] == "ok").sum()) if not stats.empty else 0,
        "fail_days": int((stats["status"] != "ok").sum()) if not stats.empty else 0,
        "use_mv_neutralize": use_mv,
        "use_industry_neutralize": use_ind,
    }
    if not stats.empty:
        status_counts = stats["status"].value_counts().to_dict()
        stat["status_counts"] = {str(k): int(v) for k, v in status_counts.items()}
    return df[KEY_COLS + [resid_col]], stat


def _fill_raw_missing_per_factor(
    panel: pd.DataFrame,
    value_col: str,
    past_days: int,
    max_forward_days: int,
    use_cs_median: bool,
    use_global_median: bool,
    fallback_value: float,
) -> pd.DataFrame:
    out = panel.copy().sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    s = pd.to_numeric(out[value_col], errors="coerce")

    if past_days > 0:
        hist = s.groupby(out["stock_code"], sort=False).transform(lambda x: x.shift(1).rolling(past_days, min_periods=1).median())
        s = s.fillna(hist)

    if max_forward_days > 0:
        s = s.groupby(out["stock_code"], sort=False).transform(lambda x: x.ffill(limit=max_forward_days))

    if use_cs_median:
        cs_med = s.groupby(out["trade_date"], sort=False).transform("median")
        s = s.fillna(cs_med)

    if use_global_median:
        gmed = s.median()
        if pd.notna(gmed):
            s = s.fillna(gmed)

    s = s.fillna(float(fallback_value))
    out[value_col] = s
    return out


def _mad_clip_and_zscore(panel: pd.DataFrame, value_col: str, mad_k: float, standardize: bool) -> pd.DataFrame:
    out = panel.copy()
    x = pd.to_numeric(out[value_col], errors="coerce")
    med = x.groupby(out["trade_date"]).transform("median")
    mad = (x - med).abs().groupby(out["trade_date"]).transform("median")
    mad_scaled = 1.4826 * mad
    mu = x.groupby(out["trade_date"]).transform("mean")
    sig = x.groupby(out["trade_date"]).transform("std")
    scale = mad_scaled.where(mad_scaled > 1e-12, sig).where(lambda z: z > 1e-12, 1.0)

    lower = med - mad_k * scale
    upper = med + mad_k * scale
    clipped = x.clip(lower=lower, upper=upper)

    if standardize:
        zmu = clipped.groupby(out["trade_date"]).transform("mean")
        zsig = clipped.groupby(out["trade_date"]).transform("std")
        out[value_col] = np.where(zsig > 1e-12, (clipped - zmu) / zsig, 0.0)
    else:
        out[value_col] = clipped
    return out


def _write_factor_daily(factor_name: str, panel: pd.DataFrame) -> None:
    out_dir = OrthoConfig.OUTPUT_FACTOR_DAILY_DIR / factor_name
    _clean_csv_dir(out_dir)
    for td, g in panel.groupby("trade_date", sort=True):
        day = g[KEY_COLS + [factor_name]].sort_values("stock_code").reset_index(drop=True)
        _write_csv(day, out_dir / f"{td}.csv")


def _write_merged_daily(merged: pd.DataFrame, td_list: list[str]) -> None:
    _clean_csv_dir(OrthoConfig.OUTPUT_DAILY_DIR)
    grouped = {k: g for k, g in merged.groupby("trade_date", sort=False)}
    for td in td_list:
        day = grouped.get(td)
        if day is None:
            day = pd.DataFrame(columns=merged.columns)
        day = day.sort_values("stock_code").reset_index(drop=True)
        _write_csv(day, OrthoConfig.OUTPUT_DAILY_DIR / f"{td}.csv")


def main() -> None:
    OrthoConfig.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OrthoConfig.OUTPUT_META_DIR.mkdir(parents=True, exist_ok=True)

    td_list, pool_target = _read_target_inputs()
    factors = _selected_factors()
    if not factors:
        raise ValueError("No factors found from 1_factor_request/factor_generation/*/output/daily")

    mv_panel = _query_mv_panel(td_list, pool_target)
    ind_panel, ind_cols = _build_industry_onehot_panel(td_list, pool_target)
    base = pool_target.merge(mv_panel, on=KEY_COLS, how="left").merge(ind_panel, on=KEY_COLS, how="left")
    for c in ind_cols:
        base[c] = pd.to_numeric(base[c], errors="coerce").fillna(0).astype(int)

    default_skip_mv = {"size_log_mcap"}
    env_skip_mv = {x.strip() for x in os.getenv("ORTHO_SKIP_MV_NEUTRALIZE_FACTORS", "").split(",") if x.strip()}
    env_skip_ind = {x.strip() for x in os.getenv("ORTHO_SKIP_INDUSTRY_NEUTRALIZE_FACTORS", "").split(",") if x.strip()}
    skip_mv = default_skip_mv | env_skip_mv
    skip_ind = env_skip_ind

    merged = pool_target.copy()
    run_stats: dict[str, Any] = {
        "start_date": OrthoConfig.START_DATE,
        "end_date": OrthoConfig.END_DATE,
        "input_trading_days_csv": str(OrthoConfig.INPUT_TRADING_DAYS_CSV),
        "input_pool_daily_dir": str(OrthoConfig.INPUT_POOL_DAILY_DIR),
        "factor_root_dir": str(OrthoConfig.INPUT_FACTOR_ROOT_DIR),
        "target_days": int(len(td_list)),
        "target_rows": int(pool_target.shape[0]),
        "target_codes": int(pool_target["stock_code"].nunique()),
        "factors_requested": factors,
        "factors": {},
        "mv_missing_rows": int(pd.to_numeric(base[OrthoConfig.MV_COL], errors="coerce").isna().sum()),
        "industry_unknown_rows": int(base.get(OrthoConfig.INDUSTRY_UNKNOWN_COL, pd.Series(dtype=float)).sum())
        if OrthoConfig.INDUSTRY_UNKNOWN_COL in base.columns
        else 0,
    }

    for factor_name in factors:
        factor_panel = _load_factor_panel(factor_name, td_list, pool_target)
        panel = base.merge(factor_panel, on=KEY_COLS, how="left")

        resid_panel, reg_stat = _regress_one_factor(
            panel=panel,
            factor_name=factor_name,
            td_list=td_list,
            ind_cols=ind_cols,
            skip_mv_neutralize=skip_mv,
            skip_ind_neutralize=skip_ind,
        )

        resid_col = f"{factor_name}_resid_raw"
        proc = resid_panel.rename(columns={resid_col: factor_name})

        miss_before = int(proc[factor_name].isna().sum())
        if OrthoConfig.FILL_RESID_MISSING:
            proc = _fill_raw_missing_per_factor(
                panel=proc,
                value_col=factor_name,
                past_days=OrthoConfig.FILL_PAST_DAYS,
                max_forward_days=OrthoConfig.FILL_MAX_FORWARD_DAYS,
                use_cs_median=OrthoConfig.FILL_USE_CROSS_SECTION_MEDIAN,
                use_global_median=OrthoConfig.FILL_USE_GLOBAL_MEDIAN,
                fallback_value=OrthoConfig.FILL_FALLBACK_VALUE,
            )
        miss_after_fill = int(proc[factor_name].isna().sum())

        proc = _mad_clip_and_zscore(
            panel=proc,
            value_col=factor_name,
            mad_k=OrthoConfig.CS_MAD_K,
            standardize=OrthoConfig.CS_STANDARDIZE,
        )
        miss_after_final = int(proc[factor_name].isna().sum())

        _write_factor_daily(factor_name, proc)
        merged = merged.merge(proc, on=KEY_COLS, how="left")

        run_stats["factors"][factor_name] = {
            "rows": int(proc.shape[0]),
            "missing_before_fill": miss_before,
            "missing_after_fill": miss_after_fill,
            "missing_after_final": miss_after_final,
            "output_dir": str(OrthoConfig.OUTPUT_FACTOR_DAILY_DIR / factor_name),
            **reg_stat,
        }
        print(f"[OK] {factor_name}")

    _write_merged_daily(merged, td_list)
    _write_csv(pd.DataFrame([{"trade_date": d} for d in td_list]), OrthoConfig.OUTPUT_META_DIR / "run_dates.csv")
    _write_csv(
        pd.DataFrame(
            [
                {"factor_name": k, **(v if isinstance(v, dict) else {})}
                for k, v in run_stats["factors"].items()
            ]
        ),
        OrthoConfig.OUTPUT_META_DIR / "factor_run_stats.csv",
    )

    run_stats["merged_daily_dir"] = str(OrthoConfig.OUTPUT_DAILY_DIR)
    run_stats["merged_files_written"] = int(len(td_list))
    run_stats["merged_rows"] = int(merged.shape[0])
    run_stats["merged_columns"] = list(merged.columns)

    (OrthoConfig.OUTPUT_META_DIR / "run_summary.json").write_text(
        json.dumps(run_stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(run_stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

