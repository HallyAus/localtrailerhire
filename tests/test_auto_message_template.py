"""Regression tests for the published booking-message automation example."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from jinja2 import Environment

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_TIMEZONE = ZoneInfo("Australia/Sydney")


def _as_timestamp(value: object, default: object = None) -> float | object:
    """Implement the Home Assistant timestamp helper for this offline fixture."""
    if not value:
        return default
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return default
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _timestamp_custom(value: float, fmt: str, local: bool = True) -> str:
    """Render an epoch using Home Assistant's local-time flag semantics."""
    tz = LOCAL_TIMEZONE if local else UTC
    return datetime.fromtimestamp(value, tz=tz).strftime(fmt)


def _render_message(data: dict[str, object]) -> str:
    """Load and render the example with deterministic HA-like time helpers."""
    automation = yaml.safe_load(
        (REPO_ROOT / "examples" / "auto_message.yaml").read_text(encoding="utf-8")
    )
    message = automation["actions"][0]["data"]["message"]
    environment = Environment()
    environment.globals["as_timestamp"] = _as_timestamp
    environment.filters["timestamp_custom"] = _timestamp_custom
    return environment.from_string(message).render(
        trigger={"event": {"data": data}}
    )


def test_booking_message_formats_utc_dates_in_sydney_time() -> None:
    """UTC instants crossing a date boundary display in local time, including DST."""
    winter = _render_message(
        {
            "booking_start": "2026-07-01T14:30:00Z",
            "booking_end": "2026-07-02T05:00:00Z",
        }
    )
    assert "Pickup: Thursday, 02 July at 12:30 AM" in winter
    assert "Return: Thursday, 02 July at 03:00 PM" in winter

    summer = _render_message(
        {
            "booking_start": "2026-01-01T13:30:00Z",
            "booking_end": "2026-01-02T02:00:00Z",
        }
    )
    assert "Pickup: Friday, 02 January at 12:30 AM" in summer
    assert "Return: Friday, 02 January at 01:00 PM" in summer


def test_booking_message_has_fallback_for_missing_or_invalid_times() -> None:
    """An incomplete event still produces a readable message without a crash."""
    message = _render_message(
        {"booking_start": "not-a-time", "booking_end": None}
    )
    assert "Pickup: time to be confirmed" in message
    assert "Return: time to be confirmed" in message
