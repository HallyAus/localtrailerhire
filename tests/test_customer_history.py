"""Tests for privacy-aware customer history retention."""

from __future__ import annotations

from datetime import UTC, datetime

from lth_customer_history import (
    clear_customer_history,
    export_customer_history,
    merge_customer_history,
    prune_customer_history,
)


def _booking(*, include_sensitive: bool = True) -> dict:
    customer = {
        "id": "customer-1",
        "first_name": "Customer",
        "last_name": "Example",
        "display_name": "Customer E",
        "phone": "0412345678" if include_sensitive else "0412****78",
        "address": {"full": "Example address"},
        "licence": {"number": "EXAMPLE"},
        "num_hires": 2,
    }
    return {
        "transaction_id": "transaction-1",
        "customer_id": "customer-1",
        "customer": customer,
        "booking_id": "booking-1",
        "booking_start": "2026-08-01T00:00:00Z",
        "booking_end": "2026-08-02T00:00:00Z",
        "listing_id": "listing-1",
        "listing_title": "Example Trailer",
        "last_transition": "transition/accept",
        "booking_details": {
            "booking_type": "standard",
            "referrer_name": "Example Referrer",
        },
    }


def test_merge_retains_customer_and_transaction_by_stable_ids():
    history, changed = merge_customer_history({}, [_booking()], include_sensitive=True)

    assert changed is True
    assert list(history) == ["customer-1"]
    record = history["customer-1"]
    assert record["booking_count"] == 1
    assert record["customer"]["first_name"] == "Customer"
    assert record["customer"]["phone"] == "0412345678"
    assert record["transactions"]["transaction-1"]["listing_id"] == "listing-1"


def test_default_privacy_omits_sensitive_customer_and_referrer_fields():
    history, _changed = merge_customer_history({}, [_booking()], include_sensitive=False)

    customer = history["customer-1"]["customer"]
    assert "phone" not in customer
    assert "address" not in customer
    assert "licence" not in customer
    details = history["customer-1"]["transactions"]["transaction-1"]["booking_details"]
    assert "referrer_name" not in details
    assert details["booking_type"] == "standard"


def test_disabling_sensitive_data_scrubs_existing_archive():
    sensitive, _changed = merge_customer_history({}, [_booking()], include_sensitive=True)
    scrubbed, changed = merge_customer_history(sensitive, [], include_sensitive=False)

    assert changed is True
    customer = scrubbed["customer-1"]["customer"]
    assert "phone" not in customer
    assert "address" not in customer
    assert "licence" not in customer
    details = scrubbed["customer-1"]["transactions"]["transaction-1"]["booking_details"]
    assert "referrer_name" not in details


def test_repeated_poll_is_idempotent():
    first, _changed = merge_customer_history({}, [_booking()], include_sensitive=False)
    second, changed = merge_customer_history(first, [_booking()], include_sensitive=False)

    assert changed is False
    assert second == first


def test_retention_prunes_old_transactions_and_empty_customers():
    history, _changed = merge_customer_history({}, [_booking()], include_sensitive=False)
    pruned = prune_customer_history(history, "90_days", datetime(2027, 1, 1, tzinfo=UTC))
    assert pruned == {}


def test_sensitive_clear_and_csv_export():
    history, _changed = merge_customer_history({}, [_booking()], include_sensitive=True)
    scrubbed = clear_customer_history(history, "sensitive")
    assert "phone" not in scrubbed["customer-1"]["customer"]
    csv_text = export_customer_history(scrubbed, "csv")
    assert "customer_id,transaction_id" in csv_text
    assert "customer-1,transaction-1" in csv_text


def test_clear_all_customer_history():
    history, _changed = merge_customer_history({}, [_booking()], include_sensitive=False)
    assert clear_customer_history(history, "all") == {}
