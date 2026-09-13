"""Tests for optional persistent message history helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from lth_message_archive import (
    count_archived_messages,
    export_message_archive,
    merge_messages,
    prune_message_archive,
    select_sync_batch,
    summarize_sync_batch,
)


def test_merge_deduplicates_stable_message_ids():
    message = {
        "id": "message-1",
        "content": "Hello",
        "created_at": "2026-08-01T00:00:00Z",
        "sender_id": "customer-1",
        "deleted": False,
    }
    first, changed = merge_messages({}, "transaction-1", [message])
    second, second_changed = merge_messages(first, "transaction-1", [message])
    assert changed is True
    assert second_changed is False
    assert second == first
    assert second["transaction-1"]["message_count"] == 1


def test_sync_timestamp_changes_only_with_material_data_or_status() -> None:
    first, changed = merge_messages(
        {},
        "transaction-1",
        [],
        sync_complete=False,
        synced_at="2026-08-01T00:00:00Z",
    )
    repeated, repeated_changed = merge_messages(
        first,
        "transaction-1",
        [],
        sync_complete=False,
        synced_at="2026-08-02T00:00:00Z",
    )
    complete, complete_changed = merge_messages(
        repeated,
        "transaction-1",
        [],
        sync_complete=True,
        synced_at="2026-08-03T00:00:00Z",
    )

    assert changed is True
    assert repeated_changed is False
    assert repeated == first
    assert repeated["transaction-1"]["last_synced_at"] == "2026-08-01T00:00:00Z"
    assert complete_changed is True
    assert complete["transaction-1"]["sync_status"] == "complete"
    assert complete["transaction-1"]["last_synced_at"] == "2026-08-03T00:00:00Z"


def test_partial_backfill_anchor_is_persisted_then_removed_on_completion() -> None:
    partial, changed = merge_messages(
        {},
        "transaction-1",
        [{"id": "message-1"}],
        sync_complete=False,
        backfill_anchor_id="message-1",
    )
    complete, completed_changed = merge_messages(
        partial,
        "transaction-1",
        [],
        sync_complete=True,
    )

    assert changed is True
    assert partial["transaction-1"]["backfill_anchor_id"] == "message-1"
    assert completed_changed is True
    assert "backfill_anchor_id" not in complete["transaction-1"]


def test_failed_sync_is_distinct_from_partial_and_does_not_store_error_text() -> None:
    archive, changed = merge_messages(
        {},
        "transaction-1",
        [],
        sync_error=True,
        synced_at="2026-08-01T00:00:00Z",
    )

    assert changed is True
    assert archive["transaction-1"]["sync_status"] == "failed"
    assert "error" not in archive["transaction-1"]


def test_merge_ignores_invalid_messages_and_preserves_omitted_existing_fields() -> None:
    first, _changed = merge_messages(
        {},
        "transaction-1",
        [{"id": "message-1", "content": "Hello", "sender_id": "customer-1"}],
        synced_at="2026-08-01T00:00:00Z",
    )
    second, changed = merge_messages(
        first,
        "transaction-1",
        [None, {"id": "message-1", "deleted": True}],  # type: ignore[list-item]
        synced_at="2026-08-02T00:00:00Z",
    )

    assert changed is True
    message = second["transaction-1"]["messages"]["message-1"]
    assert message["content"] == "Hello"
    assert message["sender_id"] == "customer-1"
    assert message["deleted"] is True


def test_merge_rejects_empty_transaction_id_without_mutating_archive() -> None:
    original = {"transaction-1": {"messages": {}, "message_count": 0}}
    merged, changed = merge_messages(original, "", [{"id": "message-1"}])

    assert changed is False
    assert merged is original


def test_sync_summary_reports_failures_and_partial_boundaries_accurately() -> None:
    summary = summarize_sync_batch(
        total_conversations=4,
        selected_transaction_ids=["complete", "partial", "failed"],
        completed_transaction_ids={"complete"},
        partial_transaction_ids={"partial"},
        failed_transaction_ids={"failed"},
        new_messages=2,
    )

    assert summary == {
        "attempted": 3,
        "succeeded": 2,
        "failed": 1,
        "new_messages": 2,
        "conversations_at_boundary": 1,
        "partial": 1,
        "remaining": 3,
        "complete": False,
        "failed_transaction_ids": ["failed"],
        "partial_transaction_ids": ["partial"],
    }


def test_sync_summary_is_complete_only_for_successful_full_boundary_sweep() -> None:
    summary = summarize_sync_batch(
        total_conversations=2,
        selected_transaction_ids=["one", "two"],
        completed_transaction_ids={"one", "two"},
        partial_transaction_ids=set(),
        failed_transaction_ids=set(),
        new_messages=0,
    )

    assert summary["complete"] is True
    assert summary["remaining"] == 0


def test_sync_batch_excludes_active_conversations_and_bounds_api_calls() -> None:
    selected, next_cursor = select_sync_batch(
        ["active-1", "history-1", "active-2", "history-2", "history-3"],
        5,
        0,
        excluded_transaction_ids={"active-1", "active-2"},
    )

    assert selected == ["history-1", "history-2", "history-3"]
    assert not set(selected) & {"active-1", "active-2"}
    assert len(selected) == 3
    assert next_cursor == 0


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


def test_prune_preserves_empty_conversation_sync_status() -> None:
    archive, _changed = merge_messages(
        {},
        "empty-transaction",
        [],
        sync_complete=True,
        synced_at="2026-01-01T00:00:00Z",
    )

    pruned = prune_message_archive(archive, "90_days", datetime(2026, 8, 1, tzinfo=UTC))

    assert pruned["empty-transaction"]["messages"] == {}
    assert pruned["empty-transaction"]["message_count"] == 0
    assert pruned["empty-transaction"]["sync_status"] == "complete"


def test_prune_and_csv_export_skip_malformed_archive_entries() -> None:
    malformed = {
        "invalid-record": None,
        "invalid-messages": {"messages": ["not", "an", "object"]},
        "mixed": {
            "messages": {
                "invalid-message": None,
                "message-1": {
                    "id": "message-1",
                    "created_at": "2026-08-01T00:00:00Z",
                    "content": "Hello",
                },
            }
        },
    }

    pruned = prune_message_archive(
        malformed,  # type: ignore[arg-type]
        "90_days",
        datetime(2026, 8, 2, tzinfo=UTC),
    )
    exported = export_message_archive(malformed, "csv")  # type: ignore[arg-type]

    assert list(pruned) == ["mixed"]
    assert list(pruned["mixed"]["messages"]) == ["message-1"]
    assert "message-1" in exported
    assert count_archived_messages(malformed) == 1  # type: ignore[arg-type]


def test_count_and_export_tolerate_malformed_archive_root() -> None:
    assert count_archived_messages(["not", "an", "object"]) == 0
    assert export_message_archive(["not", "an", "object"], "json") == "{}"
    assert export_message_archive(["not", "an", "object"], "csv").startswith(
        "transaction_id,message_id"
    )
