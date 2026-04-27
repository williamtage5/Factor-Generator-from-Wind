from __future__ import annotations

import numpy as np
import pandas as pd


def fill_raw_missing_per_factor(
    panel: pd.DataFrame,
    value_col: str,
    past_days: int,
    max_forward_days: int,
    use_cs_median: bool = True,
    use_global_median: bool = True,
    fallback_value: float = 0.0,
) -> pd.DataFrame:
    out = panel.copy()
    out = out.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    s = pd.to_numeric(out[value_col], errors="coerce")

    # 1) history-only rolling median (strictly backward to avoid leakage)
    if past_days > 0:
        hist_med = s.groupby(out["stock_code"], sort=False).transform(
            lambda x: x.shift(1).rolling(past_days, min_periods=1).median()
        )
        s = s.fillna(hist_med)

    # 2) bounded forward-fill for continuity (different bound per factor kind)
    if max_forward_days > 0:
        s = s.groupby(out["stock_code"], sort=False).transform(lambda x: x.ffill(limit=max_forward_days))

    # 3) same-day cross-sectional median
    if use_cs_median:
        cs_med = s.groupby(out["trade_date"], sort=False).transform("median")
        s = s.fillna(cs_med)

    # 4) global median fallback
    if use_global_median:
        med = s.median()
        if pd.notna(med):
            s = s.fillna(med)

    s = s.fillna(float(fallback_value))
    out[value_col] = s
    return out


def cross_sectional_mad_clip_and_zscore(
    panel: pd.DataFrame,
    value_col: str,
    mad_k: float = 5.0,
    standardize: bool = True,
) -> pd.DataFrame:
    out = panel.copy()
    x = pd.to_numeric(out[value_col], errors="coerce")

    med = x.groupby(out["trade_date"]).transform("median")
    abs_dev = (x - med).abs()
    mad = abs_dev.groupby(out["trade_date"]).transform("median")
    mad_scaled = 1.4826 * mad

    # Robust fallback when MAD collapses (e.g., flat cross section)
    mu = x.groupby(out["trade_date"]).transform("mean")
    sig = x.groupby(out["trade_date"]).transform("std")
    scale = mad_scaled.where(mad_scaled > 1e-12, sig)
    scale = scale.where(scale > 1e-12, 1.0)

    lower = med - mad_k * scale
    upper = med + mad_k * scale
    out[f"{value_col}_clip"] = x.clip(lower=lower, upper=upper)

    if standardize:
        zsig = out[f"{value_col}_clip"].groupby(out["trade_date"]).transform("std")
        zmu = out[f"{value_col}_clip"].groupby(out["trade_date"]).transform("mean")
        out[f"{value_col}_z"] = np.where(
            zsig > 1e-12,
            (out[f"{value_col}_clip"] - zmu) / zsig,
            0.0,
        )
    else:
        out[f"{value_col}_z"] = out[f"{value_col}_clip"]
    return out
