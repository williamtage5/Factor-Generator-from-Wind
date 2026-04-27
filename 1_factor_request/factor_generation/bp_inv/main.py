from __future__ import annotations

import numpy as np
import pandas as pd

from .config import FACTOR_NAME


def compute(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel[["trade_date", "stock_code", "pb_lf"]].copy()
    pb = pd.to_numeric(out["pb_lf"], errors="coerce")
    out["raw"] = np.where(pb.abs() > 1e-12, 1.0 / pb, 0.0)
    return out[["trade_date", "stock_code", "raw"]]
