from __future__ import annotations

import pandas as pd

from .config import FACTOR_NAME


def compute(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel[["trade_date", "stock_code", "revenue_yoy"]].copy()
    out = out.rename(columns={"revenue_yoy": "raw"})
    return out
