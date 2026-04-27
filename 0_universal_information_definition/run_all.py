from __future__ import annotations

try:
    from .stock_pool.main import main as run_stock_pool
except ImportError:
    from stock_pool.main import main as run_stock_pool  # type: ignore


if __name__ == "__main__":
    run_stock_pool()

