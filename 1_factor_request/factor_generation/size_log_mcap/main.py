from __future__ import annotations

import numpy as np
import pandas as pd

from .config import FACTOR_NAME


def compute(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel[["trade_date", "stock_code", "total_market_cap"]].copy()
    out["raw"] = np.log(np.clip(pd.to_numeric(out["total_market_cap"], errors="coerce"), 1.0, None))
    return out[["trade_date", "stock_code", "raw"]]
