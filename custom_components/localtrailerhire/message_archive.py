"""Pure helpers for the optional persistent message archive."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from .util import parse_iso_datetime


def merge_messages(
    archive: dict[str, Any], transaction_id: str, messages: list[dict[str, Any]]
) -> tuple[dict[str, Any], bool]:
    """Merge stable message snapshots without duplicating message ids."""
    updated = {key: dict(value) for key, value in archive.items() if isinstance(value, dict)}
    record = dict(updated.get(transaction_id) or {})
    existing = dict(record.get("messages") or {})
    for message in messages:
        message_id = message.get("id")
        if not message_id:
            continue
        existing[str(message_id)] = {
            key: message.get(key)
            for key in ("id", "content", "created_at", "deleted", "sender_id")
            if message.get(key) is not None
        }
    record["messages"] = existing
    record["message_count"] = len(existing)
    record["last_synced_at"] = datetime.now(UTC).isoformat()
    updated[transaction_id] = record
    return updated, updated != archive


def prune_message_archive(
    archive: dict[str, Any], retention: str, now: datetime | None = None
) -> dict[str, Any]:
    """Apply the configured retention window to individual messages."""
    if retention == "forever":
        return archive
    cutoff = (now or datetime.now(UTC)) - timedelta(days=90 if retention == "90_days" else 365)
    result: dict[str, Any] = {}
    for txn_id, raw_record in archive.items():
        record = dict(raw_record)
        messages = {
            msg_id: msg
            for msg_id, msg in dict(record.get("messages") or {}).items()
            if (parse_iso_datetime(msg.get("created_at")) or cutoff) >= cutoff
        }
        if messages:
            record["messages"] = messages
            record["message_count"] = len(messages)
            result[txn_id] = record
    return result


def export_message_archive(archive: dict[str, Any], output_format: str) -> str:
    """Serialize archived messages to JSON or CSV."""
    if output_format == "json":
        return json.dumps(archive, ensure_ascii=False, indent=2, sort_keys=True)
    output = io.StringIO()
    fields = ("transaction_id", "message_id", "created_at", "sender_id", "deleted", "content")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for txn_id, record in sorted(archive.items()):
        for msg_id, msg in sorted(dict(record.get("messages") or {}).items()):
            writer.writerow(
                {
                    "transaction_id": txn_id,
                    "message_id": msg_id,
                    "created_at": msg.get("created_at"),
                    "sender_id": msg.get("sender_id"),
                    "deleted": msg.get("deleted", False),
                    "content": msg.get("content"),
                }
            )
    return output.getvalue()
