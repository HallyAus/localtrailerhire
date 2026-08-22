"""Tests for optional persistent message history helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from lth_message_archive import export_message_archive, merge_messages, prune_message_archive


def test_merge_deduplicates_stable_message_ids():
    message = {
        "id": "message-1",
        "content": "Hello",
        "created_at": "2026-08-01T00:00:00Z",
        "sender_id": "customer-1",
        "deleted": False,
    }
    first, changed = merge_messages({}, "transaction-1", [message])
    second, _changed = merge_messages(first, "transaction-1", [message])
    assert changed is True
    assert second["transaction-1"]["message_count"] == 1


def test_message_retention_and_exports():
    archive, _changed = merge_messages(
        {},
        "transaction-1",
        [
            {
                "id": "message-1",
                "content": "Hello",
                "created_at": "2026-01-01T00:00:00Z",
                "sender_id": "customer-1",
            }
        ],
    )
    assert "Hello" in export_message_archive(archive, "json")
    assert "transaction_id,message_id" in export_message_archive(archive, "csv")
    assert prune_message_archive(archive, "90_days", datetime(2026, 8, 1, tzinfo=UTC)) == {}
