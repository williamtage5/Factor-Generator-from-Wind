from __future__ import annotations

import pandas as pd

from .config import FACTOR_NAME


def compute(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel[["trade_date", "stock_code", "roe"]].copy()
    out = out.rename(columns={"roe": "raw"})
    return out
