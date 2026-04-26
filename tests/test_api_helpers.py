"""Unit tests for pure (static / classmethod) helpers on SharetribeFlexAPI."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from lth_api import SharetribeFlexAPI


# ---------- _mask_phone ----------


def test_mask_phone_australian_mobile():
    assert SharetribeFlexAPI._mask_phone("0412345678") == "0412****78"


def test_mask_phone_strips_formatting():
    # First 4 + middle asterisks + last 2 of digit-only "61412345678"
    assert SharetribeFlexAPI._mask_phone("+61 412 345 678") == "6141*****78"


def test_mask_phone_returns_none_for_empty():
    assert SharetribeFlexAPI._mask_phone(None) is None
    assert SharetribeFlexAPI._mask_phone("") is None


def test_mask_phone_short_numbers_fully_masked():
    masked = SharetribeFlexAPI._mask_phone("123")
    assert masked == "***"


# ---------- _format_money ----------


def test_format_money_converts_cents_to_dollars():
    assert SharetribeFlexAPI._format_money({"amount": 15000}) == 150.0


def test_format_money_handles_zero():
    assert SharetribeFlexAPI._format_money({"amount": 0}) == 0.0


def test_format_money_returns_none_when_missing():
    assert SharetribeFlexAPI._format_money(None) is None
    assert SharetribeFlexAPI._format_money({}) is None


# ---------- _format_licence_expiry ----------


def test_format_licence_expiry_formats_iso_and_display():
    iso, display = SharetribeFlexAPI._format_licence_expiry(
        {"day": 5, "month": 3, "year": 2026}
    )
    assert iso == "2026-03-05"
    assert display == "05/03/2026"


def test_format_licence_expiry_returns_none_when_incomplete():
    assert SharetribeFlexAPI._format_licence_expiry(None) == (None, None)
    assert SharetribeFlexAPI._format_licence_expiry({"day": 1}) == (None, None)
    assert SharetribeFlexAPI._format_licence_expiry(
        {"day": "x", "month": 1, "year": 2026}
    ) == (None, None)


# ---------- _extract_uuid ----------


def test_extract_uuid_from_dict():
    uuid = SharetribeFlexAPI._extract_uuid({"uuid": "abc-123"})
    assert uuid == "abc-123"


def test_extract_uuid_from_string():
    assert SharetribeFlexAPI._extract_uuid("abc-123") == "abc-123"


def test_extract_uuid_returns_none_for_missing():
    assert SharetribeFlexAPI._extract_uuid(None) is None
    assert SharetribeFlexAPI._extract_uuid({}) is None
    assert SharetribeFlexAPI._extract_uuid("") is None


# ---------- _categorize ----------


NOW = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def test_categorize_upcoming():
    category, reason = SharetribeFlexAPI._categorize(_dt(2024, 7, 1), _dt(2024, 7, 3), NOW)
    assert category == "upcoming"
    assert "now" in reason


def test_categorize_in_progress():
    category, _ = SharetribeFlexAPI._categorize(_dt(2024, 6, 14), _dt(2024, 6, 16), NOW)
    assert category == "in_progress"


def test_categorize_past():
    category, _ = SharetribeFlexAPI._categorize(_dt(2024, 5, 1), _dt(2024, 5, 3), NOW)
    assert category == "past"


@pytest.mark.parametrize(
    "start,end,expected_missing",
    [
        (None, _dt(2024, 6, 16), "booking_start"),
        (_dt(2024, 6, 14), None, "booking_end"),
        (None, None, "booking_start"),
    ],
)
def test_categorize_unknown_when_dates_missing(start, end, expected_missing):
    category, reason = SharetribeFlexAPI._categorize(start, end, NOW)
    assert category == "unknown"
    assert expected_missing in reason
