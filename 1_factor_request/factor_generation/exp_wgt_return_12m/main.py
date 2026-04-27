from __future__ import annotations

from factor_generation.common import compute_exp_wgt_return_nm

FACTOR_NAME = "exp_wgt_return_12m"


def compute(panel):
    return compute_exp_wgt_return_nm(panel, "12m", halflife=20.0)
