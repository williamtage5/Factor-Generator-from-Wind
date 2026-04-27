from __future__ import annotations

from factor_generation.common import compute_return_nm

FACTOR_NAME = "return_1m"


def compute(panel):
    return compute_return_nm(panel, "1m")
