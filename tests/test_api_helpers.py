"""Unit tests for pure (static / classmethod) helpers on SharetribeFlexAPI."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from lth_api import SharetribeFlexAPI

NOW = datetime(2024, 6, 15, 12, 0, tzinfo=UTC)

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


def test_extract_line_items_preserves_reconciliation_fields():
    result = SharetribeFlexAPI._extract_line_items(
        [
            {
                "code": "line-item/units",
                "unitPrice": {"amount": 5500, "currency": "AUD"},
                "lineTotal": {"amount": 11000, "currency": "AUD"},
                "quantity": 2,
                "reversal": False,
                "includeFor": ["customer", "provider"],
            }
        ]
    )
    assert result == [
        {
            "code": "line-item/units",
            "unit_price": 55.0,
            "line_total": 110.0,
            "currency": "AUD",
            "quantity": 2,
            "reversal": False,
            "include_for": ["customer", "provider"],
        }
    ]


def test_build_customer_object_uses_transaction_names_and_masks_sensitive_data():
    api = SharetribeFlexAPI(session=None, client_id="test")
    result = api._build_customer_object(
        {
            "displayName": "Customer A",
            "abbreviatedName": "CA",
            "publicData": {
                "numCustomerHires": 4,
                "customerReviewStats": {
                    "avgCustomerReviewRating": 4.8,
                    "numCustomerReviews": 3,
                    "updatedAt": "2026-06-01T00:00:00Z",
                },
            },
        },
        {
            "firstName": "Customer",
            "lastName": "Example",
            "phoneNumber": "0412345678",
            "residentialAddress": "Example address",
            "suburb": "Example suburb",
            "driversLicenceNumber": "REDACTED",
        },
        False,
        customer_id="customer-1",
        customer_attrs={"createdAt": "2025-01-01T00:00:00Z", "state": "active"},
    )

    assert result["id"] == "customer-1"
    assert result["first_name"] == "Customer"
    assert result["last_name"] == "Example"
    assert result["phone"] == "0412****78"
    assert result["num_hires"] == 4
    assert result["review_stats"]["average_rating"] == 4.8
    assert result["address"] == {
        "building": None,
        "suburb": "Example suburb",
        "full": "Example address",
    }
    assert "licence" not in result


def test_build_customer_object_includes_licence_only_when_opted_in():
    api = SharetribeFlexAPI(session=None, client_id="test")
    result = api._build_customer_object(
        {},
        {
            "phoneNumber": "0412345678",
            "driversLicenceNumber": "EXAMPLE",
            "driversLicenceIssuedBy": "NSW",
            "driversLicenceExpiryDate": {"day": 5, "month": 3, "year": 2027},
        },
        True,
    )

    assert result["phone"] == "0412345678"
    assert result["licence"] == {
        "number": "EXAMPLE",
        "state": "NSW",
        "expiry_iso": "2027-03-05",
        "expiry_display": "05/03/2027",
    }


# ---------- _format_licence_expiry ----------


def test_format_licence_expiry_formats_iso_and_display():
    iso, display = SharetribeFlexAPI._format_licence_expiry({"day": 5, "month": 3, "year": 2026})
    assert iso == "2026-03-05"
    assert display == "05/03/2026"


def test_format_licence_expiry_returns_none_when_incomplete():
    assert SharetribeFlexAPI._format_licence_expiry(None) == (None, None)
    assert SharetribeFlexAPI._format_licence_expiry({"day": 1}) == (None, None)
    assert SharetribeFlexAPI._format_licence_expiry({"day": "x", "month": 1, "year": 2026}) == (
        None,
        None,
    )


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


# ---------- provider-review transition history ----------


def test_parse_transaction_marks_provider_review_done_from_history():
    transaction = {
        "id": {"uuid": "txn-1"},
        "attributes": {
            "lastTransition": "transition/payout-after-provider-review",
            "transitions": [
                {"transition": "transition/complete"},
                {"transition": "transition/review-1-by-provider"},
                {"transition": "transition/payout-after-provider-review"},
            ],
        },
        "relationships": {},
    }

    api = object.__new__(SharetribeFlexAPI)
    booking, _debug = api._extract_booking_data(
        transaction,
        bookings_map={},
        customers_map={},
        listings_map={},
        now=NOW,
        include_sensitive=False,
    )

    assert booking is not None
    assert booking["provider_review_done"] is True


def test_parse_transaction_leaves_provider_review_open_without_history_match():
    transaction = {
        "id": {"uuid": "txn-1"},
        "attributes": {
            "lastTransition": "transition/complete",
            "transitions": [{"transition": "transition/complete"}],
        },
        "relationships": {},
    }

    api = object.__new__(SharetribeFlexAPI)
    booking, _debug = api._extract_booking_data(
        transaction,
        bookings_map={},
        customers_map={},
        listings_map={},
        now=NOW,
        include_sensitive=False,
    )

    assert booking is not None
    assert booking["provider_review_done"] is False


# ---------- _categorize ----------


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


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


def test_extract_booking_data_keeps_customer_and_transaction_reference_fields():
    api = SharetribeFlexAPI(session=None, client_id="test")
    txn = {
        "id": {"uuid": "txn-1"},
        "attributes": {
            "createdAt": "2026-01-01T00:00:00Z",
            "state": "state/accepted",
            "processName": "default-booking",
            "processVersion": 3,
            "lastTransition": "transition/accept",
            "lastTransitionedAt": "2026-01-02T00:00:00Z",
            "transitions": [{"transition": "transition/accept"}],
            "payinTotal": {"amount": 12000, "currency": "AUD"},
            "payoutTotal": {"amount": 10000, "currency": "AUD"},
            "lineItems": [
                {
                    "code": "line-item/units",
                    "lineTotal": {"amount": 12000, "currency": "AUD"},
                    "quantity": 1,
                }
            ],
            "protectedData": {
                "firstName": "Customer",
                "lastName": "Example",
                "phoneNumber": "0412345678",
                "residentialAddress": "Example address",
                "bookingType": "standard",
                "promoCode": "EXAMPLE",
            },
        },
        "relationships": {
            "booking": {"data": {"id": {"uuid": "booking-1"}}},
            "customer": {"data": {"id": {"uuid": "customer-1"}}},
            "listing": {"data": {"id": {"uuid": "listing-1"}}},
        },
    }
    bookings = {
        "booking-1": {
            "attributes": {
                "start": "2026-02-01T00:00:00Z",
                "end": "2026-02-02T00:00:00Z",
                "displayStart": "2026-02-01T10:00:00Z",
                "displayEnd": "2026-02-02T10:00:00Z",
                "state": "accepted",
                "seats": 1,
            }
        }
    }
    customers = {
        "customer-1": {
            "attributes": {
                "createdAt": "2025-01-01T00:00:00Z",
                "state": "active",
                "profile": {
                    "displayName": "Customer E",
                    "publicData": {"numCustomerHires": 2},
                },
            }
        }
    }
    listings = {"listing-1": {"attributes": {"title": "Example Trailer"}}}

    booking, _debug = api._extract_booking_data(
        txn,
        bookings,
        customers,
        listings,
        datetime(2026, 1, 15, tzinfo=UTC),
    )

    assert booking is not None
    assert booking["customer_id"] == "customer-1"
    assert booking["booking_id"] == "booking-1"
    assert booking["customer_first_name"] == "Customer"
    assert booking["customer_last_name"] == "Example"
    assert booking["customer"]["phone"] == "0412****78"
    assert booking["booking_display_start"] == "2026-02-01T10:00:00Z"
    assert booking["booking_seats"] == 1
    assert booking["process_name"] == "default-booking"
    assert booking["transaction_state"] == "state/accepted"
    assert booking["payin_currency"] == "AUD"
    assert booking["line_items"][0]["line_total"] == 120.0
    assert booking["booking_details"]["promo_code"] == "EXAMPLE"
