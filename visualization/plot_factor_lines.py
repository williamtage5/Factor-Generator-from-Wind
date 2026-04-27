from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd


KEY_COLS = ["trade_date", "stock_code"]


def _normalize_yyyymmdd(series: pd.Series) -> pd.Series:
    return series.astype(str).str.extract(r"(\d{8})", expand=False)


def _resolve_daily_dir(root: Path, factor_name: str) -> Path:
    p1 = root / factor_name / "output" / "daily"
    if p1.exists():
        return p1
    p2 = root / factor_name
    if p2.exists():
        return p2
    return p1


def _list_factors(raw_root: Path, proc_root: Path) -> list[str]:
    raw = {d.name for d in raw_root.iterdir() if d.is_dir() and (d / "output" / "daily").exists()}
    proc = {d.name for d in proc_root.iterdir() if d.is_dir()}
    factors = sorted(raw & proc)
    if not factors:
        raise ValueError("No intersected factors found between raw and processed roots.")
    return factors


def _detect_value_col(file_path: Path, factor_name: str) -> str:
    d = pd.read_csv(file_path, encoding="utf-8-sig", low_memory=False, nrows=30)
    if factor_name in d.columns:
        return factor_name
    cols = [c for c in d.columns if c not in KEY_COLS]
    if not cols:
        raise ValueError(f"No factor value column found in {file_path}")
    return cols[0]


def _load_one_factor_series(daily_dir: Path, factor_name: str, stock_code: str, all_days: list[str]) -> pd.Series:
    files = sorted(daily_dir.glob("*.csv"))
    if not files:
        return pd.Series(index=all_days, dtype=float, name=factor_name)

    value_col = _detect_value_col(files[0], factor_name)
    values: dict[str, float] = {}

    for f in files:
        td = f.stem
        d = pd.read_csv(f, encoding="utf-8-sig", low_memory=False)
        if "stock_code" not in d.columns:
            continue
        if "trade_date" in d.columns:
            d["trade_date"] = _normalize_yyyymmdd(d["trade_date"])
        else:
            d["trade_date"] = td
        d["stock_code"] = d["stock_code"].astype(str).str.strip()
        if value_col not in d.columns:
            alt = [c for c in d.columns if c not in KEY_COLS]
            if not alt:
                continue
            value_col = alt[0]
        row = d[d["stock_code"] == stock_code]
        if row.empty:
            continue
        v = pd.to_numeric(row.iloc[-1][value_col], errors="coerce")
        values[str(row.iloc[-1]["trade_date"])] = float(v) if pd.notna(v) else float("nan")

    s = pd.Series(values, name=factor_name)
    s = s.reindex(all_days)
    return s


def _load_trading_days(csv_path: Path) -> list[str]:
    d = pd.read_csv(csv_path, encoding="utf-8-sig", low_memory=False)
    if "trade_date" not in d.columns:
        raise ValueError(f"trade_date missing in {csv_path}")
    d["trade_date"] = _normalize_yyyymmdd(d["trade_date"])
    d = d.dropna(subset=["trade_date"]).drop_duplicates(subset=["trade_date"]).sort_values("trade_date")
    return d["trade_date"].tolist()


def _choose_9_factors(raw_df: pd.DataFrame, proc_df: pd.DataFrame) -> list[str]:
    score = (raw_df.notna().sum() + proc_df.notna().sum()).sort_values(ascending=False)
    return score.head(9).index.tolist()


def _plot_grid(
    raw_df: pd.DataFrame,
    proc_df: pd.DataFrame,
    factors: list[str],
    stock_code: str,
    title: str,
    out_path: Path,
    n_cols: int,
) -> None:
    n = len(factors)
    n_rows = math.ceil(n / n_cols)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(n_cols * 4.4, n_rows * 2.6), sharex=True)
    axes_list = axes.flatten() if isinstance(axes, (list, tuple)) else axes.ravel()

    x = pd.to_datetime(raw_df.index, format="%Y%m%d", errors="coerce")
    for i, fac in enumerate(factors):
        ax = axes_list[i]
        ax.plot(x, raw_df[fac], linewidth=1.0, label="Raw", color="#1f77b4")
        ax.plot(x, proc_df[fac], linewidth=1.0, label="Processed", color="#d62728")
        ax.set_title(fac, fontsize=9)
        ax.grid(alpha=0.25)

    for j in range(n, len(axes_list)):
        axes_list[j].axis("off")

    handles, labels = axes_list[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=2, frameon=False)
    fig.suptitle(f"{title}\nStock: {stock_code}", fontsize=13, y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=170)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot raw vs processed factor lines by date (no aggregation).")
    parser.add_argument("--stock-code", default="000001.SZ", help="Stock code for line charts, e.g. 000001.SZ")
    parser.add_argument(
        "--raw-root",
        default=str(Path("1_factor_request") / "factor_generation"),
        help="Raw factor root dir",
    )
    parser.add_argument(
        "--processed-root",
        default=str(Path("2_factor_orthogonalization") / "output" / "factor_daily"),
        help="Processed factor root dir",
    )
    parser.add_argument(
        "--trading-days-csv",
        default=str(Path("0_universal_information_definition") / "outputs" / "trading_days.csv"),
        help="Trading days csv",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path("visualization") / "output" / "line_compare"),
        help="Output directory",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stock_code = args.stock_code.strip()
    raw_root = Path(args.raw_root).resolve()
    proc_root = Path(args.processed_root).resolve()
    trading_days_csv = Path(args.trading_days_csv).resolve()
    output_dir = Path(args.output_dir).resolve() / stock_code

    all_days = _load_trading_days(trading_days_csv)
    factors = _list_factors(raw_root, proc_root)

    raw_series: dict[str, pd.Series] = {}
    proc_series: dict[str, pd.Series] = {}
    for fac in factors:
        raw_series[fac] = _load_one_factor_series(_resolve_daily_dir(raw_root, fac), fac, stock_code, all_days)
        proc_series[fac] = _load_one_factor_series(_resolve_daily_dir(proc_root, fac), fac, stock_code, all_days)

    raw_df = pd.DataFrame(raw_series, index=all_days)
    proc_df = pd.DataFrame(proc_series, index=all_days)

    # Figure 1: all factors (7x4 for 28 factors)
    fig_all = output_dir / f"{stock_code}_all_factors_raw_vs_processed.png"
    _plot_grid(
        raw_df=raw_df,
        proc_df=proc_df,
        factors=factors,
        stock_code=stock_code,
        title="All Factors Line Comparison",
        out_path=fig_all,
        n_cols=4,
    )

    # Figure 2: selected 3x3 factors
    selected = _choose_9_factors(raw_df, proc_df)
    fig_3x3 = output_dir / f"{stock_code}_selected_3x3_raw_vs_processed.png"
    _plot_grid(
        raw_df=raw_df,
        proc_df=proc_df,
        factors=selected,
        stock_code=stock_code,
        title="Selected 3x3 Factors Line Comparison",
        out_path=fig_3x3,
        n_cols=3,
    )

    selected_csv = output_dir / f"{stock_code}_selected_3x3_factors.csv"
    pd.DataFrame({"factor_name": selected}).to_csv(selected_csv, index=False, encoding="utf-8-sig")

    print(f"[OK] all={fig_all}")
    print(f"[OK] selected_3x3={fig_3x3}")
    print(f"[OK] selected_factors={selected_csv}")


if __name__ == "__main__":
    main()

