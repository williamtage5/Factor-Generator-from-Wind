from __future__ import annotations

import numpy as np
import pandas as pd


WINDOW_MAP = {
    "1m": 20,
    "3m": 60,
    "6m": 120,
    "12m": 240,
}


def month_window(tag: str) -> int:
    if tag not in WINDOW_MAP:
        raise ValueError(f"Unsupported month tag: {tag}")
    return WINDOW_MAP[tag]


def compute_return_nm(panel: pd.DataFrame, month_tag: str) -> pd.DataFrame:
    w = month_window(month_tag)
    out = panel[["trade_date", "stock_code", "close_price", "is_in_pool"]].copy()
    out = out.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    out["raw"] = out.groupby("stock_code", sort=False)["close_price"].pct_change(w)
    out = out[out["is_in_pool"] == 1].copy()
    return out[["trade_date", "stock_code", "raw"]]


def compute_wgt_return_nm(panel: pd.DataFrame, month_tag: str) -> pd.DataFrame:
    w = month_window(month_tag)
    out = panel[["trade_date", "stock_code", "close_price", "turn_d", "is_in_pool"]].copy()
    out = out.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    out["ret_1d"] = out.groupby("stock_code", sort=False)["close_price"].pct_change()
    out["w_ret"] = out["turn_d"] * out["ret_1d"]
    out["sum_w_ret"] = out.groupby("stock_code", sort=False)["w_ret"].transform(lambda x: x.rolling(w, min_periods=w).sum())
    out["sum_w"] = out.groupby("stock_code", sort=False)["turn_d"].transform(lambda x: x.rolling(w, min_periods=w).sum())
    out["raw"] = np.where(out["sum_w"].abs() > 1e-12, out["sum_w_ret"] / out["sum_w"], np.nan)
    out = out[out["is_in_pool"] == 1].copy()
    return out[["trade_date", "stock_code", "raw"]]


def compute_exp_wgt_return_nm(panel: pd.DataFrame, month_tag: str, halflife: float = 20.0) -> pd.DataFrame:
    w = month_window(month_tag)
    out = panel[["trade_date", "stock_code", "close_price", "turn_d", "is_in_pool"]].copy()
    out = out.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    out["ret_1d"] = out.groupby("stock_code", sort=False)["close_price"].pct_change()

    decay_lambda = np.log(2.0) / max(halflife, 1e-6)
    weights = np.exp(-decay_lambda * np.arange(w - 1, -1, -1, dtype=float))

    def _calc(group: pd.DataFrame) -> pd.Series:
        r = group["ret_1d"].to_numpy(dtype=float)
        t = group["turn_d"].to_numpy(dtype=float)
        raw = np.full_like(r, np.nan, dtype=float)
        for i in range(w - 1, len(group)):
            rr = r[i - w + 1 : i + 1]
            tt = t[i - w + 1 : i + 1]
            ww = tt * weights
            denom = np.nansum(ww)
            if np.isfinite(denom) and abs(denom) > 1e-12:
                raw[i] = np.nansum(ww * rr) / denom
        return pd.Series(raw, index=group.index)

    out["raw"] = out.groupby("stock_code", sort=False, group_keys=False).apply(_calc)
    out = out[out["is_in_pool"] == 1].copy()
    return out[["trade_date", "stock_code", "raw"]]


def compute_halpha_12m(panel: pd.DataFrame, month_window_n: int = 12) -> pd.DataFrame:
    out = panel[["trade_date", "stock_code", "close_price", "market_ret_1d", "is_in_pool"]].copy()
    out = out.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    out["ret_1d"] = out.groupby("stock_code", sort=False)["close_price"].pct_change()
    out["ym"] = out["trade_date"].astype(str).str.slice(0, 6)

    # Build monthly compounded returns for stock and market
    ms = out.groupby(["stock_code", "ym"], sort=True)["ret_1d"].apply(lambda s: (1.0 + s.fillna(0.0)).prod() - 1.0).reset_index(name="ret_m")
    mm = out.groupby("ym", sort=True)["market_ret_1d"].apply(lambda s: (1.0 + s.fillna(0.0)).prod() - 1.0).reset_index(name="mkt_ret_m")
    m = ms.merge(mm, on="ym", how="left").sort_values(["stock_code", "ym"]).reset_index(drop=True)

    def _alpha_roll(g: pd.DataFrame) -> pd.Series:
        y = g["ret_m"].to_numpy(dtype=float)
        x = g["mkt_ret_m"].to_numpy(dtype=float)
        a = np.full_like(y, np.nan, dtype=float)
        for i in range(month_window_n - 1, len(g)):
            yy = y[i - month_window_n + 1 : i + 1]
            xx = x[i - month_window_n + 1 : i + 1]
            ok = np.isfinite(yy) & np.isfinite(xx)
            if ok.sum() < month_window_n:
                continue
            xx2 = xx[ok]
            yy2 = yy[ok]
            x_mean = xx2.mean()
            y_mean = yy2.mean()
            cov = ((xx2 - x_mean) * (yy2 - y_mean)).mean()
            var = ((xx2 - x_mean) ** 2).mean()
            if abs(var) <= 1e-12:
                continue
            beta = cov / var
            alpha = y_mean - beta * x_mean
            a[i] = alpha
        return pd.Series(a, index=g.index)

    m["alpha_m"] = m.groupby("stock_code", sort=False, group_keys=False).apply(_alpha_roll)
    month_alpha = m[["stock_code", "ym", "alpha_m"]].copy()

    out = out.merge(month_alpha, on=["stock_code", "ym"], how="left")
    out["raw"] = out["alpha_m"]
    out = out[out["is_in_pool"] == 1].copy()
    return out[["trade_date", "stock_code", "raw"]]
