"""Tests for the pure auto-review selection logic (auto_review.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from lth_auto_review import (
    AUTO_REVIEW_RETRY_MAX,
    auto_review_failure_state,
    auto_review_retry_delay,
    auto_review_retry_due,
    is_reviewable,
    select_auto_reviews,
    summarize_auto_reviews,
)

NOW = datetime(2026, 6, 22, 12, 0, tzinfo=UTC)


def _booking(txn_id: str, category: str, end_offset_days: float) -> dict:
    end = NOW + timedelta(days=end_offset_days)
    return {
        "transaction_id": txn_id,
        "category": category,
        "booking_end": end.isoformat(),
    }


# --- is_reviewable -----------------------------------------------------------


def test_is_reviewable_recent_past():
    assert is_reviewable(_booking("t", "past", -1), NOW) is True


def test_not_reviewable_upcoming():
    assert is_reviewable(_booking("t", "upcoming", 2), NOW) is False


def test_not_reviewable_in_progress():
    assert is_reviewable(_booking("t", "in_progress", 0), NOW) is False


def test_not_reviewable_too_old():
    assert is_reviewable(_booking("t", "past", -30), NOW) is False


def test_not_reviewable_missing_end():
    booking = {"transaction_id": "t", "category": "past", "booking_end": None}
    assert is_reviewable(booking, NOW) is False


def test_not_reviewable_when_provider_already_reviewed():
    booking = _booking("t", "past", -1)
    booking["last_transition"] = "transition/review-2-by-provider"
    assert is_reviewable(booking, NOW) is False


def test_not_reviewable_when_review_window_expired():
    booking = _booking("t", "past", -1)
    booking["last_transition"] = "transition/expire-provider-review-period"
    assert is_reviewable(booking, NOW) is False


def test_not_reviewable_when_aggregate_review_period_expired():
    booking = _booking("t", "past", -1)
    booking["last_transition"] = "transition/expire-review-period"
    assert is_reviewable(booking, NOW) is False


def test_not_reviewable_when_customer_reviewed_second():
    booking = _booking("t", "past", -1)
    booking["last_transition"] = "transition/review-2-by-customer"
    assert is_reviewable(booking, NOW) is False


def test_customer_first_still_allows_provider_review():
    booking = _booking("t", "past", -1)
    booking["last_transition"] = "transition/review-1-by-customer"
    assert is_reviewable(booking, NOW) is True


def test_force_selection_can_bypass_retry_backoff():
    booking = _booking("t", "past", -1)
    states = {"t": {"auto_review_next_attempt_at": (NOW + timedelta(days=1)).isoformat()}}
    assert select_auto_reviews([booking], states, enabled=True, now=NOW) == []
    assert select_auto_reviews([booking], states, enabled=True, now=NOW, ignore_backoff=True) == [
        "t"
    ]


def test_failure_summary_contains_only_sanitized_reason_and_next_attempt():
    state = auto_review_failure_state({}, NOW, "APIError")
    summary = summarize_auto_reviews({"t": state}, enabled=True, rating=5)
    assert summary["last_failure"] == "APIError"
    assert summary["last_failure_at"] == NOW.isoformat()
    assert summary["next_attempt_at"] == state["auto_review_next_attempt_at"]


def test_not_reviewable_when_provider_review_is_in_transition_history():
    booking = _booking("t", "past", -1)
    booking["last_transition"] = "transition/archive"
    booking["provider_review_done"] = True
    assert is_reviewable(booking, NOW) is False


# --- select_auto_reviews -----------------------------------------------------


def test_disabled_selects_nothing():
    bookings = [_booking("t1", "past", -1)]
    assert select_auto_reviews(bookings, {}, enabled=False, now=NOW) == []


def test_selects_eligible_past_booking():
    bookings = [_booking("t1", "past", -1)]
    assert select_auto_reviews(bookings, {}, enabled=True, now=NOW) == ["t1"]


def test_skips_already_auto_reviewed():
    bookings = [_booking("t1", "past", -1)]
    states = {"t1": {"auto_reviewed": True}}
    assert select_auto_reviews(bookings, states, enabled=True, now=NOW) == []


def test_skips_already_reviewed_via_api():
    bookings = [_booking("t1", "past", -1)]
    result = select_auto_reviews(
        bookings, {}, enabled=True, now=NOW, reviewed_txn_ids=frozenset({"t1"})
    )
    assert result == []


def test_legacy_exhausted_attempt_state_is_recovered_on_upgrade():
    bookings = [_booking("t1", "past", -1)]
    states = {"t1": {"auto_review_attempts": 8}}
    assert select_auto_reviews(bookings, states, enabled=True, now=NOW) == ["t1"]


def test_skips_until_persisted_retry_is_due():
    bookings = [_booking("t1", "past", -1)]
    states = {
        "t1": {
            "auto_review_attempts": 2,
            "auto_review_next_attempt_at": (NOW + timedelta(minutes=20)).isoformat(),
        }
    }
    assert select_auto_reviews(bookings, states, enabled=True, now=NOW) == []
    assert select_auto_reviews(bookings, states, enabled=True, now=NOW + timedelta(minutes=20)) == [
        "t1"
    ]


def test_invalid_retry_timestamp_fails_open_for_recovery():
    assert auto_review_retry_due({"auto_review_next_attempt_at": "not-a-date"}, NOW) is True


def test_failure_state_persists_exponential_retry_schedule():
    first = auto_review_failure_state({}, NOW)
    assert first["auto_review_attempts"] == 1
    assert first["auto_review_next_attempt_at"] == (NOW + timedelta(minutes=30)).isoformat()

    second = auto_review_failure_state(first, NOW)
    assert second["auto_review_attempts"] == 2
    assert second["auto_review_next_attempt_at"] == (NOW + timedelta(hours=1)).isoformat()

    recovered = auto_review_failure_state({"auto_review_attempts": "bad"}, NOW)
    assert recovered["auto_review_attempts"] == 1


def test_retry_delay_is_capped():
    assert auto_review_retry_delay(100) == AUTO_REVIEW_RETRY_MAX


def test_skips_upcoming_unknown_keeps_past():
    bookings = [
        _booking("up", "upcoming", 3),
        _booking("unk", "unknown", -1),
        _booking("past", "past", -1),
    ]
    assert select_auto_reviews(bookings, {}, enabled=True, now=NOW) == ["past"]


def test_mixed_realistic_selection():
    bookings = [
        _booking("past_fresh", "past", -2),
        _booking("past_old", "past", -40),
        _booking("upcoming", "upcoming", 5),
    ]
    states = {"past_fresh": {"auto_review_attempts": 1}}  # under the cap
    assert select_auto_reviews(bookings, states, enabled=True, now=NOW) == ["past_fresh"]


# --- summarize_auto_reviews --------------------------------------------------


def test_summary_disabled_empty():
    s = summarize_auto_reviews({}, enabled=False, rating=5)
    assert s["enabled"] is False
    assert s["rating"] == 5
    assert s["auto_reviewed_total"] == 0
    assert s["last_auto_review_at"] is None
    assert s["last_auto_review_transaction"] is None
    assert s["pending_retries"] == 0


def test_summary_counts_and_latest():
    states = {
        "t1": {"auto_reviewed": True, "auto_reviewed_at": "2026-06-20T00:00:00Z"},
        "t2": {"auto_reviewed": True, "auto_reviewed_at": "2026-06-23T00:00:00Z"},
        "t3": {"auto_review_attempts": 3},  # failed, still retrying
        "t4": {"message_sent": True},  # unrelated state
    }
    s = summarize_auto_reviews(states, enabled=True, rating=4)
    assert s["enabled"] is True
    assert s["auto_reviewed_total"] == 2
    assert s["last_auto_review_at"] == "2026-06-23T00:00:00Z"
    assert s["last_auto_review_transaction"] == "t2"
    assert s["pending_retries"] == 1
