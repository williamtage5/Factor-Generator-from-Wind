from __future__ import annotations

import numpy as np
import pandas as pd

from .config import FACTOR_NAME


def compute(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel[["trade_date", "stock_code", "pe_ttm"]].copy()
    pe = pd.to_numeric(out["pe_ttm"], errors="coerce")
    out["raw"] = np.where(pe.abs() > 1e-12, 1.0 / pe, 0.0)
    return out[["trade_date", "stock_code", "raw"]]
