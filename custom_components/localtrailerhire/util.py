"""Utility helpers for the Local Trailer Hire integration."""

from __future__ import annotations

from datetime import datetime, timezone


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse an ISO 8601 datetime string, returning a UTC-aware datetime.

    Accepts trailing ``Z`` (treated as ``+00:00``) and naive timestamps
    (assumed UTC). Returns ``None`` if the value is empty or unparseable.
    """
    if not value or not isinstance(value, str):
        return None

    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
