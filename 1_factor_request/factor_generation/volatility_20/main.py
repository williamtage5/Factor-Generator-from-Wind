from __future__ import annotations

import pandas as pd

from .config import FACTOR_NAME, WINDOW


def compute(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel[["trade_date", "stock_code", "close_price"]].copy()
    out = out.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    out["ret_1d"] = out.groupby("stock_code", sort=False)["close_price"].pct_change()
    out["raw"] = out.groupby("stock_code", sort=False)["ret_1d"].transform(
        lambda x: x.rolling(WINDOW, min_periods=WINDOW).std()
    )
    return out[["trade_date", "stock_code", "raw"]]
