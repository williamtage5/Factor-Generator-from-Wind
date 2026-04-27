from __future__ import annotations

import pandas as pd

from .config import FACTOR_NAME, WINDOW


def compute(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel[["trade_date", "stock_code", "close_price"]].copy()
    out = out.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    out["raw"] = out.groupby("stock_code", sort=False)["close_price"].pct_change(WINDOW)
    return out[["trade_date", "stock_code", "raw"]]
