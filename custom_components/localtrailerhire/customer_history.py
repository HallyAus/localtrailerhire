"""Privacy-aware customer history retention helpers."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from .util import parse_iso_datetime

_SENSITIVE_CUSTOMER_FIELDS = frozenset({"phone", "address", "licence"})


def _customer_snapshot(customer: dict[str, Any], include_sensitive: bool) -> dict[str, Any]:
    """Copy useful customer fields, omitting empty and non-opted-in PII."""
    snapshot: dict[str, Any] = {}
    for key, value in customer.items():
        if value is None or (key in _SENSITIVE_CUSTOMER_FIELDS and not include_sensitive):
            continue
        if key == "review_stats" and isinstance(value, dict):
            value = {field: item for field, item in value.items() if item is not None}
            if not value:
                continue
        snapshot[key] = value
    return snapshot


def _transaction_snapshot(booking: dict[str, Any], include_sensitive: bool) -> dict[str, Any]:
    """Copy the bounded booking fields needed for later customer reference."""
    keys = (
        "transaction_id",
        "booking_id",
        "booking_start",
        "booking_end",
        "listing_id",
        "listing_title",
        "transaction_created_at",
        "transaction_state",
        "last_transition",
        "last_transitioned_at",
        "payin_total_aud",
        "payout_total_aud",
    )
    snapshot = {key: booking.get(key) for key in keys if booking.get(key) is not None}
    details = dict(booking.get("booking_details") or {})
    if not include_sensitive:
        details.pop("referrer_name", None)
    details = {key: value for key, value in details.items() if value is not None}
    if details:
        snapshot["booking_details"] = details
    return snapshot


def merge_customer_history(
    existing: dict[str, Any] | None,
    bookings: list[dict[str, Any]],
    *,
    include_sensitive: bool,
) -> tuple[dict[str, Any], bool]:
    """Merge booking snapshots into a customer-id keyed persistent archive.

    Disabling sensitive data also scrubs previously retained phone, address,
    licence and referrer values, so an options change cannot leave stale PII in
    Home Assistant storage.
    """
    history: dict[str, Any] = {}
    for customer_id, raw_record in (existing or {}).items():
        if not isinstance(raw_record, dict):
            continue
        record = dict(raw_record)
        record["customer"] = _customer_snapshot(
            dict(record.get("customer") or {}), include_sensitive
        )
        transactions = {}
        for transaction_id, raw_transaction in dict(record.get("transactions") or {}).items():
            if not isinstance(raw_transaction, dict):
                continue
            transaction = dict(raw_transaction)
            if not include_sensitive and isinstance(transaction.get("booking_details"), dict):
                details = dict(transaction["booking_details"])
                details.pop("referrer_name", None)
                transaction["booking_details"] = details
            transactions[transaction_id] = transaction
        record["transactions"] = transactions
        record["booking_count"] = len(transactions)
        history[str(customer_id)] = record

    for booking in bookings:
        customer = booking.get("customer") or {}
        customer_id = booking.get("customer_id") or customer.get("id")
        transaction_id = booking.get("transaction_id")
        if not customer_id or not transaction_id:
            continue

        record = history.setdefault(
            str(customer_id),
            {"customer": {}, "transactions": {}, "booking_count": 0},
        )
        current_customer = dict(record.get("customer") or {})
        current_customer.update(_customer_snapshot(customer, include_sensitive))
        record["customer"] = current_customer

        transactions = dict(record.get("transactions") or {})
        transactions[str(transaction_id)] = _transaction_snapshot(booking, include_sensitive)
        record["transactions"] = transactions
        record["booking_count"] = len(transactions)

    original = existing or {}
    return history, history != original


def prune_customer_history(
    history: dict[str, Any], retention: str, now: datetime | None = None
) -> dict[str, Any]:
    """Drop transaction snapshots older than the selected retention period."""
    if retention == "forever":
        return history
    cutoff = (now or datetime.now(UTC)) - timedelta(days=90 if retention == "90_days" else 365)
    pruned: dict[str, Any] = {}
    for customer_id, raw_record in history.items():
        record = dict(raw_record)
        transactions = {}
        for txn_id, raw_txn in dict(record.get("transactions") or {}).items():
            txn = dict(raw_txn)
            timestamp = parse_iso_datetime(
                txn.get("booking_end")
                or txn.get("last_transitioned_at")
                or txn.get("transaction_created_at")
            )
            if timestamp is None or timestamp >= cutoff:
                transactions[txn_id] = txn
        if transactions:
            record["transactions"] = transactions
            record["booking_count"] = len(transactions)
            pruned[customer_id] = record
    return pruned


def clear_customer_history(history: dict[str, Any], scope: str) -> dict[str, Any]:
    """Clear all history or scrub just sensitive fields."""
    if scope == "all":
        return {}
    scrubbed, _changed = merge_customer_history(history, [], include_sensitive=False)
    return scrubbed


def export_customer_history(history: dict[str, Any], output_format: str) -> str:
    """Serialize the archive as readable JSON or one CSV row per booking."""
    if output_format == "json":
        return json.dumps(history, ensure_ascii=False, indent=2, sort_keys=True)

    output = io.StringIO()
    fields = (
        "customer_id",
        "transaction_id",
        "first_name",
        "last_name",
        "display_name",
        "phone",
        "booking_start",
        "booking_end",
        "listing_title",
        "last_transition",
        "payin_total_aud",
        "payout_total_aud",
    )
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for customer_id, record in sorted(history.items()):
        customer = dict(record.get("customer") or {})
        for transaction_id, txn in sorted(dict(record.get("transactions") or {}).items()):
            writer.writerow(
                {
                    "customer_id": customer_id,
                    "transaction_id": transaction_id,
                    "first_name": customer.get("first_name"),
                    "last_name": customer.get("last_name"),
                    "display_name": customer.get("display_name"),
                    "phone": customer.get("phone"),
                    "booking_start": txn.get("booking_start"),
                    "booking_end": txn.get("booking_end"),
                    "listing_title": txn.get("listing_title"),
                    "last_transition": txn.get("last_transition"),
                    "payin_total_aud": txn.get("payin_total_aud"),
                    "payout_total_aud": txn.get("payout_total_aud"),
                }
            )
    return output.getvalue()
