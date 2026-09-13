"""Pure helpers for the optional persistent message archive."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from .util import parse_iso_datetime


def merge_messages(
    archive: dict[str, Any],
    transaction_id: str,
    messages: list[dict[str, Any]],
    *,
    sync_complete: bool | None = None,
    sync_error: bool = False,
    backfill_anchor_id: str | None = None,
    synced_at: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Merge stable message snapshots and durable sync state.

    ``last_synced_at`` advances only when message content or sync status changes.
    A repeated successful poll therefore returns the original archive and
    ``False``, allowing callers to avoid a Home Assistant storage write.

    ``sync_error`` deliberately stores only the failed state, never exception
    text that could contain customer or API response data.
    """
    if not transaction_id:
        return archive, False

    updated = {key: dict(value) for key, value in archive.items() if isinstance(value, dict)}
    record = dict(updated.get(transaction_id) or {})
    raw_existing = record.get("messages") or {}
    existing = dict(raw_existing) if isinstance(raw_existing, dict) else {}
    for message in messages:
        if not isinstance(message, dict):
            continue
        message_id = message.get("id")
        if not message_id:
            continue
        snapshot = {
            key: message.get(key)
            for key in ("id", "content", "created_at", "deleted", "sender_id")
            if message.get(key) is not None
        }
        previous = existing.get(str(message_id))
        stable_snapshot = dict(previous) if isinstance(previous, dict) else {}
        stable_snapshot.update(snapshot)
        existing[str(message_id)] = stable_snapshot

    candidate = dict(record)
    candidate["messages"] = existing
    candidate["message_count"] = len(existing)
    if sync_error:
        candidate["sync_status"] = "failed"
    elif sync_complete is not None:
        candidate["sync_status"] = "complete" if sync_complete else "partial"
        if sync_complete:
            candidate.pop("backfill_anchor_id", None)
        elif backfill_anchor_id:
            candidate["backfill_anchor_id"] = backfill_anchor_id

    # Compare without the volatile timestamp. Timestamps are useful context but
    # must not independently turn every poll into a persistent write.
    comparable_record = {key: value for key, value in record.items() if key != "last_synced_at"}
    comparable_candidate = {
        key: value for key, value in candidate.items() if key != "last_synced_at"
    }
    material_changed = comparable_candidate != comparable_record
    if not material_changed:
        return archive, False

    candidate["last_synced_at"] = synced_at or datetime.now(UTC).isoformat()
    updated[transaction_id] = candidate
    return updated, True


def select_sync_batch(
    transaction_ids: list[str],
    batch_size: int,
    cursor: int,
    *,
    excluded_transaction_ids: set[str] | frozenset[str] = frozenset(),
) -> tuple[list[str], int]:
    """Select a rotating batch without repeating conversations scanned this poll."""
    available = list(
        dict.fromkeys(
            transaction_id
            for transaction_id in transaction_ids
            if transaction_id and transaction_id not in excluded_transaction_ids
        )
    )
    if not available:
        return [], 0

    bounded_size = min(max(0, batch_size), len(available))
    normalized_cursor = max(0, cursor) % len(available)
    selected = available[normalized_cursor : normalized_cursor + bounded_size]
    if len(selected) < bounded_size:
        selected += available[: bounded_size - len(selected)]
    return selected, (normalized_cursor + len(selected)) % len(available)


def count_archived_messages(archive: Any) -> int:
    """Count valid stored messages without trusting persisted record shapes."""
    if not isinstance(archive, dict):
        return 0
    count = 0
    for record in archive.values():
        if not isinstance(record, dict):
            continue
        messages = record.get("messages")
        if isinstance(messages, dict):
            count += sum(1 for message in messages.values() if isinstance(message, dict))
    return count


def summarize_sync_batch(
    *,
    total_conversations: int,
    selected_transaction_ids: list[str],
    completed_transaction_ids: set[str],
    partial_transaction_ids: set[str],
    failed_transaction_ids: set[str],
    new_messages: int,
) -> dict[str, Any]:
    """Build an honest response for one bounded message-sync batch.

    A conversation is successful when it completed or made partial progress.
    The whole sync is complete only when this batch covers every conversation,
    every request succeeded, and every pagination boundary was reached.
    """
    selected = list(dict.fromkeys(selected_transaction_ids))
    selected_set = set(selected)
    failed = failed_transaction_ids & selected_set
    completed = (completed_transaction_ids & selected_set) - failed
    partial = (partial_transaction_ids & selected_set) - completed - failed
    succeeded = (completed | partial) - failed
    fully_complete = (
        len(selected) >= total_conversations
        and not failed
        and not partial
        and len(completed) >= total_conversations
    )
    remaining = max(0, total_conversations - len(completed))
    return {
        "attempted": len(selected),
        "succeeded": len(succeeded),
        "failed": len(failed),
        "new_messages": new_messages,
        "conversations_at_boundary": len(completed),
        "partial": len(partial),
        "remaining": remaining,
        "complete": fully_complete,
        "failed_transaction_ids": sorted(failed),
        "partial_transaction_ids": sorted(partial),
    }


def prune_message_archive(
    archive: dict[str, Any], retention: str, now: datetime | None = None
) -> dict[str, Any]:
    """Apply the configured retention window to individual messages."""
    if retention == "forever":
        return archive
    cutoff = (now or datetime.now(UTC)) - timedelta(days=90 if retention == "90_days" else 365)
    result: dict[str, Any] = {}
    for txn_id, raw_record in archive.items():
        if not isinstance(raw_record, dict):
            continue
        record = dict(raw_record)
        raw_messages = record.get("messages") or {}
        messages = {
            msg_id: msg
            for msg_id, msg in (raw_messages.items() if isinstance(raw_messages, dict) else ())
            if isinstance(msg, dict)
            and (parse_iso_datetime(msg.get("created_at")) or cutoff) >= cutoff
        }
        if messages or record.get("sync_status") in {"complete", "partial", "failed"}:
            record["messages"] = messages
            record["message_count"] = len(messages)
            result[txn_id] = record
    return result


def export_message_archive(archive: Any, output_format: str) -> str:
    """Serialize archived messages to JSON or CSV."""
    archive = archive if isinstance(archive, dict) else {}
    if output_format == "json":
        return json.dumps(archive, ensure_ascii=False, indent=2, sort_keys=True)
    output = io.StringIO()
    fields = ("transaction_id", "message_id", "created_at", "sender_id", "deleted", "content")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for txn_id, record in sorted(archive.items()):
        if not isinstance(record, dict):
            continue
        raw_messages = record.get("messages") or {}
        if not isinstance(raw_messages, dict):
            continue
        for msg_id, msg in sorted(raw_messages.items()):
            if not isinstance(msg, dict):
                continue
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
