"""Tests for the booking → CalendarEvent conversion logic.

Only the pure conversion is covered here: instantiating ``CalendarEntity``
requires the homeassistant package, which we deliberately avoid in unit
tests. The conversion lives in a static method that uses ``parse_iso_datetime``
plus simple field access, so we replicate it locally and assert against the
same booking dicts the integration produces.
"""

from __future__ import annotations

from datetime import datetime, timezone

from lth_util import parse_iso_datetime


def _booking_to_event(booking: dict) -> tuple[datetime, datetime, str, str | None] | None:
    """Mirror of LocalTrailerHireCalendar._booking_to_event used for testing."""
    start = parse_iso_datetime(booking.get("booking_start"))
    end = parse_iso_datetime(booking.get("booking_end"))
    if start is None or end is None:
        return None

    listing = booking.get("listing_title") or "Trailer"
    customer = (
        booking.get("customer_display_name")
        or booking.get("customer_first_name")
        or "Customer"
    )

    description_parts: list[str] = []
    if txn_id := booking.get("transaction_id"):
        description_parts.append(f"Transaction: {txn_id}")
    if last_transition := booking.get("last_transition"):
        description_parts.append(f"State: {last_transition}")
    if (payout := booking.get("payout_total_aud")) is not None:
        description_parts.append(f"Payout: ${payout:.2f} AUD")
    if pickup := booking.get("pickup_suburb"):
        description_parts.append(f"Pickup: {pickup}")

    return start, end, f"{listing} — {customer}", ("\n".join(description_parts) or None)


def test_returns_none_when_dates_missing():
    assert _booking_to_event({"booking_start": None, "booking_end": None}) is None
    assert _booking_to_event({"booking_start": "2024-01-15T10:00:00Z"}) is None


def test_summary_combines_listing_and_customer():
    result = _booking_to_event(
        {
            "booking_start": "2024-01-15T10:00:00Z",
            "booking_end": "2024-01-17T10:00:00Z",
            "listing_title": "6x4 Cage Trailer",
            "customer_first_name": "Jane",
        }
    )
    assert result is not None
    _, _, summary, _ = result
    assert summary == "6x4 Cage Trailer — Jane"


def test_summary_falls_back_when_fields_missing():
    result = _booking_to_event(
        {
            "booking_start": "2024-01-15T10:00:00Z",
            "booking_end": "2024-01-17T10:00:00Z",
        }
    )
    assert result is not None
    _, _, summary, _ = result
    assert summary == "Trailer — Customer"


def test_description_includes_payout_and_state():
    result = _booking_to_event(
        {
            "booking_start": "2024-01-15T10:00:00Z",
            "booking_end": "2024-01-17T10:00:00Z",
            "transaction_id": "abc-123",
            "last_transition": "transition/confirm-payment",
            "payout_total_aud": 150.0,
            "pickup_suburb": "Sydney",
        }
    )
    assert result is not None
    _, _, _, description = result
    assert description is not None
    assert "Transaction: abc-123" in description
    assert "transition/confirm-payment" in description
    assert "$150.00 AUD" in description
    assert "Pickup: Sydney" in description


def test_dates_are_utc_aware():
    result = _booking_to_event(
        {
            "booking_start": "2024-01-15T10:00:00Z",
            "booking_end": "2024-01-17T10:00:00Z",
        }
    )
    assert result is not None
    start, end, _, _ = result
    assert start == datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
    assert end == datetime(2024, 1, 17, 10, 0, tzinfo=timezone.utc)
