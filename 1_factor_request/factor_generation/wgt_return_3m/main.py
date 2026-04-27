from __future__ import annotations

from factor_generation.common import compute_wgt_return_nm

FACTOR_NAME = "wgt_return_3m"


def compute(panel):
    return compute_wgt_return_nm(panel, "3m")
