from __future__ import annotations

from factor_generation.common import compute_halpha_12m

FACTOR_NAME = "halpha_12m"


def compute(panel):
    return compute_halpha_12m(panel, month_window_n=12)
