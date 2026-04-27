from __future__ import annotations

from datetime import datetime

try:
    from ..config import AppConfig
except ImportError:
    from config import AppConfig  # type: ignore


def validate_yyyymmdd(date_str: str, name: str) -> None:
    try:
        datetime.strptime(date_str, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"{name} must be YYYYMMDD, got: {date_str}") from exc


def validate_config() -> None:
    validate_yyyymmdd(AppConfig.START_DATE, "START_DATE")
    validate_yyyymmdd(AppConfig.END_DATE, "END_DATE")
    if AppConfig.START_DATE > AppConfig.END_DATE:
        raise ValueError(
            f"START_DATE must be <= END_DATE, got {AppConfig.START_DATE} > {AppConfig.END_DATE}"
        )
    if AppConfig.UNIVERSE_SOURCE != "index":
        raise ValueError(
            f"Only UNIVERSE_SOURCE=index is supported for now, got {AppConfig.UNIVERSE_SOURCE}"
        )
    if AppConfig.UNIVERSE_MODE != "daily_dynamic":
        raise ValueError(
            f"Only UNIVERSE_MODE=daily_dynamic is supported for now, got {AppConfig.UNIVERSE_MODE}"
        )
    if not AppConfig.UNIVERSE_CODE:
        raise ValueError("UNIVERSE_CODE must not be empty.")

