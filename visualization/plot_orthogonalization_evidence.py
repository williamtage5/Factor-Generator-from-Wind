from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


KEY_COLS = ["trade_date", "stock_code"]


def _normalize_yyyymmdd(series: pd.Series) -> pd.Series:
    return series.astype(str).str.extract(r"(\d{8})", expand=False)


def _import_run_query(project_root: Path):
    util_root = project_root / "1_factor_request"
    if str(util_root) not in sys.path:
        sys.path.append(str(util_root))
    from util.request_from_sqlsever import run_query

    return run_query


def _resolve_factor_daily_dir(root: Path, factor_name: str) -> Path:
    p1 = root / factor_name / "output" / "daily"
    if p1.exists():
        return p1
    p2 = root / factor_name
    if p2.exists():
        return p2
    return p1


def _detect_factor_col(file_path: Path, factor_name: str) -> str:
    d = pd.read_csv(file_path, encoding="utf-8-sig", low_memory=False, nrows=20)
    if factor_name in d.columns:
        return factor_name
    cols = [c for c in d.columns if c not in KEY_COLS]
    if not cols:
        raise ValueError(f"No factor value column in {file_path}")
    return cols[0]


def _load_factor_panel(root: Path, factor_name: str) -> pd.DataFrame:
    daily_dir = _resolve_factor_daily_dir(root, factor_name)
    if not daily_dir.exists():
        raise FileNotFoundError(f"Missing daily dir: {daily_dir}")
    files = sorted(daily_dir.glob("*.csv"))
    if not files:
        raise ValueError(f"No daily csv under {daily_dir}")

    value_col = _detect_factor_col(files[0], factor_name)
    parts: list[pd.DataFrame] = []
    for f in files:
        td = f.stem
        d = pd.read_csv(f, encoding="utf-8-sig", low_memory=False)
        if "stock_code" not in d.columns:
            continue
        if "trade_date" not in d.columns:
            d["trade_date"] = td
        d["trade_date"] = _normalize_yyyymmdd(d["trade_date"])
        d["stock_code"] = d["stock_code"].astype(str).str.strip()
        if value_col not in d.columns:
            alt = [c for c in d.columns if c not in KEY_COLS]
            if not alt:
                continue
            value_col = alt[0]
        d[factor_name] = pd.to_numeric(d[value_col], errors="coerce")
        parts.append(d[KEY_COLS + [factor_name]])
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=KEY_COLS + [factor_name])
    out = out.dropna(subset=KEY_COLS).drop_duplicates(subset=KEY_COLS, keep="last")
    out = out.sort_values(KEY_COLS).reset_index(drop=True)
    return out


def _load_target_pool(trading_days_csv: Path, pool_daily_dir: Path, start_date: str, end_date: str) -> tuple[list[str], pd.DataFrame]:
    td = pd.read_csv(trading_days_csv, encoding="utf-8-sig", low_memory=False)
    if "trade_date" not in td.columns:
        raise ValueError("trading_days.csv missing trade_date")
    td["trade_date"] = _normalize_yyyymmdd(td["trade_date"])
    td = td.dropna(subset=["trade_date"])
    td = td[(td["trade_date"] >= start_date) & (td["trade_date"] <= end_date)]
    td = td.drop_duplicates(subset=["trade_date"]).sort_values("trade_date")
    days = td["trade_date"].tolist()
    if not days:
        raise ValueError("No trading days in selected range")

    dset = set(days)
    parts: list[pd.DataFrame] = []
    for f in sorted(pool_daily_dir.glob("*.csv")):
        tdv = f.stem
        if tdv not in dset:
            continue
        d = pd.read_csv(f, encoding="utf-8-sig", low_memory=False)
        if "stock_code" not in d.columns:
            continue
        if "trade_date" not in d.columns:
            d["trade_date"] = tdv
        d["trade_date"] = _normalize_yyyymmdd(d["trade_date"])
        d["stock_code"] = d["stock_code"].astype(str).str.strip()
        parts.append(d[KEY_COLS])
    if not parts:
        raise ValueError("No pool files matched selected dates")
    pool = pd.concat(parts, ignore_index=True).dropna(subset=KEY_COLS).drop_duplicates(subset=KEY_COLS)
    pool = pool.sort_values(KEY_COLS).reset_index(drop=True)
    return days, pool


def _read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _query_mv_panel(
    run_query,
    sql_mv_file: Path,
    days: list[str],
    pool: pd.DataFrame,
) -> pd.DataFrame:
    sql_tpl = _read_sql(sql_mv_file)
    day_map = {k: g["stock_code"].tolist() for k, g in pool.groupby("trade_date", sort=False)}
    parts: list[pd.DataFrame] = []
    chunk_size = 800
    for td in days:
        codes = day_map.get(td, [])
        for i in range(0, len(codes), chunk_size):
            chunk = codes[i : i + chunk_size]
            ph = ",".join(["?"] * len(chunk))
            sql = sql_tpl.replace("{stock_code_placeholders}", ph)
            params: list[Any] = [td] + chunk
            parts.append(run_query(sql, params=params))
    mv = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=KEY_COLS + ["mv_raw"])
    if mv.empty:
        return pool.assign(mv_raw=np.nan)
    mv["trade_date"] = _normalize_yyyymmdd(mv["trade_date"])
    mv["stock_code"] = mv["stock_code"].astype(str).str.strip()
    mv["mv_raw"] = pd.to_numeric(mv["mv_raw"], errors="coerce")
    mv = mv.dropna(subset=KEY_COLS).drop_duplicates(subset=KEY_COLS, keep="last")
    return pool.merge(mv[KEY_COLS + ["mv_raw"]], on=KEY_COLS, how="left")


def _query_industry_onehot(
    run_query,
    sql_dict_file: Path,
    sql_life_file: Path,
    days: list[str],
    pool: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    dsql = _read_sql(sql_dict_file)
    lsql_tpl = _read_sql(sql_life_file)

    ind_dict = run_query(dsql, params=["b10%", 2])
    ind_dict["citic_l1_code"] = ind_dict["citic_l1_code"].astype(str).str.strip()
    ind_codes = sorted(ind_dict["citic_l1_code"].dropna().unique().tolist())
    if not ind_codes:
        return pool.assign(ind_unknown=1), ["ind_unknown"]

    all_codes = sorted(pool["stock_code"].unique().tolist())
    parts: list[pd.DataFrame] = []
    chunk_size = 800
    for i in range(0, len(all_codes), chunk_size):
        chunk = all_codes[i : i + chunk_size]
        ph = ",".join(["?"] * len(chunk))
        sql = lsql_tpl.replace("{stock_code_placeholders}", ph)
        params = chunk + ["b10%"]
        parts.append(run_query(sql, params=params))
    life = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if life.empty:
        return pool.assign(ind_unknown=1), ["ind_unknown"]

    life["stock_code"] = life["stock_code"].astype(str).str.strip()
    life["citics_ind_code"] = life["citics_ind_code"].astype(str).str.strip()
    life["citic_l1_code"] = life["citics_ind_code"].str.slice(0, 4) + "000000000000"
    life["entry_dt"] = _normalize_yyyymmdd(life["entry_dt"])
    life["remove_dt"] = _normalize_yyyymmdd(life["remove_dt"])
    life["opdate"] = pd.to_datetime(life["opdate"], errors="coerce")
    life = life[life["citic_l1_code"].isin(ind_codes)].copy()

    out_parts: list[pd.DataFrame] = []
    day_map = {k: g.copy() for k, g in pool.groupby("trade_date", sort=False)}

    for td in days:
        dp = day_map.get(td)
        if dp is None:
            continue
        row = life[life["stock_code"].isin(dp["stock_code"])].copy()
        if not row.empty:
            m1 = row["entry_dt"].notna() & (row["entry_dt"] <= td)
            m2 = row["remove_dt"].isna() | (row["remove_dt"] >= td)
            row = row[m1 & m2]
            row = row.sort_values(["stock_code", "entry_dt", "opdate", "citics_ind_code"])
            row = row.groupby("stock_code", as_index=False).tail(1)
            row = row[["stock_code", "citic_l1_code"]]
        else:
            row = pd.DataFrame(columns=["stock_code", "citic_l1_code"])

        day = dp.merge(row, on="stock_code", how="left")
        day["citic_l1_code"] = day["citic_l1_code"].fillna("unknown")
        c = pd.Categorical(day["citic_l1_code"], categories=ind_codes + ["unknown"])
        onehot = pd.get_dummies(c, prefix="ind")
        onehot.index = day.index
        day = pd.concat([day[KEY_COLS], onehot], axis=1)
        out_parts.append(day)

    out = pd.concat(out_parts, ignore_index=True) if out_parts else pool.assign(ind_unknown=1)
    ind_cols = [c for c in out.columns if c.startswith("ind_")]
    for c in ind_cols:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0).astype(int)
    out = out.drop_duplicates(subset=KEY_COLS).sort_values(KEY_COLS).reset_index(drop=True)
    return out, ind_cols


def _daily_corr(df: pd.DataFrame, x_col: str, y_col: str) -> pd.DataFrame:
    parts: list[dict[str, Any]] = []
    for td, g in df.groupby("trade_date", sort=True):
        t = g[[x_col, y_col]].dropna()
        if t.shape[0] < 5:
            parts.append({"trade_date": td, "corr": np.nan})
            continue
        if float(t[x_col].std(ddof=0)) <= 1e-12 or float(t[y_col].std(ddof=0)) <= 1e-12:
            parts.append({"trade_date": td, "corr": np.nan})
            continue
        parts.append({"trade_date": td, "corr": float(t[x_col].corr(t[y_col]))})
    out = pd.DataFrame(parts)
    out["trade_date_dt"] = pd.to_datetime(out["trade_date"], format="%Y%m%d", errors="coerce")
    return out


def _daily_industry_dispersion(df: pd.DataFrame, val_col: str, ind_cols: list[str]) -> pd.DataFrame:
    parts: list[dict[str, Any]] = []
    for td, g in df.groupby("trade_date", sort=True):
        x = g[[val_col] + ind_cols].copy()
        x[val_col] = pd.to_numeric(x[val_col], errors="coerce")
        x = x.dropna(subset=[val_col])
        if x.empty:
            parts.append({"trade_date": td, "dispersion": np.nan})
            continue
        grp_means: list[float] = []
        for c in ind_cols:
            m = x[x[c] == 1][val_col].mean()
            if pd.notna(m):
                grp_means.append(float(m))
        if len(grp_means) <= 1:
            parts.append({"trade_date": td, "dispersion": np.nan})
        else:
            parts.append({"trade_date": td, "dispersion": float(np.std(grp_means, ddof=0))})
    out = pd.DataFrame(parts)
    out["trade_date_dt"] = pd.to_datetime(out["trade_date"], format="%Y%m%d", errors="coerce")
    return out


def _plot_delta_amplitude(panel: pd.DataFrame, factor: str, out_file: Path) -> None:
    d = panel.copy()
    d["delta_abs"] = (d["proc"] - d["raw"]).abs()
    s = d.groupby("trade_date", sort=True)["delta_abs"].median().reset_index()
    s["trade_date_dt"] = pd.to_datetime(s["trade_date"], format="%Y%m%d", errors="coerce")

    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(s["trade_date_dt"], s["delta_abs"], color="#1f77b4", linewidth=1.2)
    ax.set_title(f"{factor}: Daily Median |Processed - Raw|")
    ax.set_xlabel("Trade Date")
    ax.set_ylabel("Median Absolute Change")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_file, dpi=170)
    plt.close(fig)


def _plot_distribution(panel: pd.DataFrame, factor: str, out_file: Path, max_points: int = 300000) -> None:
    raw = panel["raw"].dropna()
    proc = panel["proc"].dropna()
    if raw.shape[0] > max_points:
        raw = raw.sample(max_points, random_state=42)
    if proc.shape[0] > max_points:
        proc = proc.sample(max_points, random_state=42)

    fig, ax = plt.subplots(figsize=(10, 4.5))
    bins = 120
    ax.hist(raw, bins=bins, density=True, alpha=0.35, label="Raw", color="#1f77b4")
    ax.hist(proc, bins=bins, density=True, alpha=0.35, label="Processed", color="#d62728")
    ax.set_title(f"{factor}: Distribution Raw vs Processed")
    ax.set_xlabel("Factor Value")
    ax.set_ylabel("Density")
    ax.legend()
    ax.grid(alpha=0.2)
    fig.tight_layout()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_file, dpi=170)
    plt.close(fig)


def _plot_processed_std_validity(panel: pd.DataFrame, factor: str, out_file: Path) -> None:
    s = panel.groupby("trade_date", sort=True)["proc"].agg(["mean", "std"]).reset_index()
    s["trade_date_dt"] = pd.to_datetime(s["trade_date"], format="%Y%m%d", errors="coerce")
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(s["trade_date_dt"], s["mean"], label="Processed Mean", color="#2ca02c", linewidth=1.1)
    ax.plot(s["trade_date_dt"], s["std"], label="Processed Std", color="#ff7f0e", linewidth=1.1)
    ax.axhline(0.0, color="#2ca02c", linestyle="--", linewidth=0.8, alpha=0.7)
    ax.axhline(1.0, color="#ff7f0e", linestyle="--", linewidth=0.8, alpha=0.7)
    ax.set_title(f"{factor}: Processed Standardization Check (Mean~0, Std~1)")
    ax.set_xlabel("Trade Date")
    ax.set_ylabel("Value")
    ax.legend()
    ax.grid(alpha=0.25)
    fig.tight_layout()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_file, dpi=170)
    plt.close(fig)


def _plot_neutralization_effect(
    corr_raw: pd.DataFrame,
    corr_proc: pd.DataFrame,
    disp_raw: pd.DataFrame,
    disp_proc: pd.DataFrame,
    factor: str,
    out_file: Path,
) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)

    axes[0].plot(corr_raw["trade_date_dt"], corr_raw["corr"], label="Raw vs ln(MV)", color="#1f77b4", linewidth=1.1)
    axes[0].plot(corr_proc["trade_date_dt"], corr_proc["corr"], label="Processed vs ln(MV)", color="#d62728", linewidth=1.1)
    axes[0].axhline(0.0, color="black", linestyle="--", linewidth=0.8, alpha=0.6)
    axes[0].set_ylabel("Correlation")
    axes[0].set_title(f"{factor}: MV Neutralization Effect")
    axes[0].legend()
    axes[0].grid(alpha=0.25)

    axes[1].plot(
        disp_raw["trade_date_dt"],
        disp_raw["dispersion"],
        label="Raw Industry Mean Dispersion",
        color="#1f77b4",
        linewidth=1.1,
    )
    axes[1].plot(
        disp_proc["trade_date_dt"],
        disp_proc["dispersion"],
        label="Processed Industry Mean Dispersion",
        color="#d62728",
        linewidth=1.1,
    )
    axes[1].set_ylabel("Dispersion")
    axes[1].set_xlabel("Trade Date")
    axes[1].set_title("Industry Neutralization Effect")
    axes[1].legend()
    axes[1].grid(alpha=0.25)

    fig.tight_layout()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_file, dpi=170)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evidence plots for orthogonalization + standardization changes.")
    parser.add_argument("--factor", default="bp_inv")
    parser.add_argument("--project-root", default=str(Path(".")))
    parser.add_argument("--start-date", default="20230101")
    parser.add_argument("--end-date", default="20231231")
    parser.add_argument(
        "--output-dir",
        default=str(Path("visualization") / "output" / "evidence"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    factor = args.factor.strip()
    project_root = Path(args.project_root).resolve()
    out_dir = Path(args.output_dir).resolve() / factor

    raw_root = project_root / "1_factor_request" / "factor_generation"
    proc_root = project_root / "2_factor_orthogonalization" / "output" / "factor_daily"
    trading_days_csv = project_root / "0_universal_information_definition" / "outputs" / "trading_days.csv"
    pool_daily_dir = project_root / "0_universal_information_definition" / "outputs" / "stock_pool_daily"

    run_query = _import_run_query(project_root)

    days, pool = _load_target_pool(trading_days_csv, pool_daily_dir, args.start_date, args.end_date)

    raw = _load_factor_panel(raw_root, factor).rename(columns={factor: "raw"})
    proc = _load_factor_panel(proc_root, factor).rename(columns={factor: "proc"})
    panel = pool.merge(raw, on=KEY_COLS, how="left").merge(proc, on=KEY_COLS, how="left")
    panel = panel.sort_values(KEY_COLS).reset_index(drop=True)

    sql_root = project_root / "2_factor_orthogonalization" / "sql"
    mv = _query_mv_panel(run_query, sql_root / "query_mv_s_val_mv.sql", days, pool)
    ind, ind_cols = _query_industry_onehot(
        run_query,
        sql_root / "query_industry_dict.sql",
        sql_root / "query_industry_lifecycle.sql",
        days,
        pool,
    )

    panel = panel.merge(mv, on=KEY_COLS, how="left").merge(ind, on=KEY_COLS, how="left")
    panel["ln_mv"] = np.where(pd.to_numeric(panel["mv_raw"], errors="coerce") > 0, np.log(panel["mv_raw"]), np.nan)

    corr_raw = _daily_corr(panel, "ln_mv", "raw")
    corr_proc = _daily_corr(panel, "ln_mv", "proc")
    disp_raw = _daily_industry_dispersion(panel, "raw", ind_cols)
    disp_proc = _daily_industry_dispersion(panel, "proc", ind_cols)

    fig1 = out_dir / f"{factor}_01_delta_amplitude.png"
    fig2 = out_dir / f"{factor}_02_distribution_compare.png"
    fig3 = out_dir / f"{factor}_03_processed_standardization_check.png"
    fig4 = out_dir / f"{factor}_04_neutralization_effect.png"

    _plot_delta_amplitude(panel, factor, fig1)
    _plot_distribution(panel, factor, fig2)
    _plot_processed_std_validity(panel, factor, fig3)
    _plot_neutralization_effect(corr_raw, corr_proc, disp_raw, disp_proc, factor, fig4)

    summary = {
        "factor": factor,
        "date_range": {"start": args.start_date, "end": args.end_date},
        "rows_total": int(panel.shape[0]),
        "raw_non_null": int(panel["raw"].notna().sum()),
        "proc_non_null": int(panel["proc"].notna().sum()),
        "median_abs_change": float((panel["proc"] - panel["raw"]).abs().median()),
        "mean_abs_change": float((panel["proc"] - panel["raw"]).abs().mean()),
        "corr_ln_mv_abs_mean_raw": float(corr_raw["corr"].abs().mean(skipna=True)),
        "corr_ln_mv_abs_mean_proc": float(corr_proc["corr"].abs().mean(skipna=True)),
        "industry_dispersion_mean_raw": float(disp_raw["dispersion"].mean(skipna=True)),
        "industry_dispersion_mean_proc": float(disp_proc["dispersion"].mean(skipna=True)),
        "figures": [str(fig1), str(fig2), str(fig3), str(fig4)],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{factor}_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    panel.to_csv(out_dir / f"{factor}_evidence_panel.csv", index=False, encoding="utf-8-sig")
    corr_raw.to_csv(out_dir / f"{factor}_corr_ln_mv_raw.csv", index=False, encoding="utf-8-sig")
    corr_proc.to_csv(out_dir / f"{factor}_corr_ln_mv_proc.csv", index=False, encoding="utf-8-sig")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

