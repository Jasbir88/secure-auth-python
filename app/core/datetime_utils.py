# app/core/datetime_utils.py
"""Datetime utilities for Python 3.12+ compatibility."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


def utc_now_naive() -> datetime:
    """Return current UTC time as naive datetime (for DB compatibility)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
