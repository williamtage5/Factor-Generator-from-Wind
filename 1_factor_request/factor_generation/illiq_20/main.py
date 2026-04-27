from __future__ import annotations

import numpy as np
import pandas as pd

from .config import FACTOR_NAME, WINDOW


def compute(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel[["trade_date", "stock_code", "close_price", "amount"]].copy()
    out = out.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    out["ret_1d"] = out.groupby("stock_code", sort=False)["close_price"].pct_change()
    out["illiq_1d"] = np.abs(out["ret_1d"]) / (out["amount"].abs() + 1.0)
    out["raw"] = out.groupby("stock_code", sort=False)["illiq_1d"].transform(
        lambda x: x.rolling(WINDOW, min_periods=WINDOW).mean()
    )
    return out[["trade_date", "stock_code", "raw"]]
