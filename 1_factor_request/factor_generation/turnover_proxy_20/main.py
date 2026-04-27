from __future__ import annotations

import numpy as np
import pandas as pd

from .config import FACTOR_NAME, WINDOW


def compute(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel[["trade_date", "stock_code", "amount", "total_market_cap"]].copy()
    out = out.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    out["turnover_proxy_1d"] = np.where(
        out["total_market_cap"].abs() > 1e-12,
        out["amount"] / out["total_market_cap"],
        0.0,
    )
    out["raw"] = out.groupby("stock_code", sort=False)["turnover_proxy_1d"].transform(
        lambda x: x.rolling(WINDOW, min_periods=WINDOW).mean()
    )
    return out[["trade_date", "stock_code", "raw"]]
