"""Tests for the pure auto-review selection logic (auto_review.py)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lth_auto_review import (
    MAX_AUTO_REVIEW_ATTEMPTS,
    is_reviewable,
    select_auto_reviews,
)

NOW = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)


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


def test_skips_when_attempts_exhausted():
    bookings = [_booking("t1", "past", -1)]
    states = {"t1": {"auto_review_attempts": MAX_AUTO_REVIEW_ATTEMPTS}}
    assert select_auto_reviews(bookings, states, enabled=True, now=NOW) == []


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
    assert select_auto_reviews(bookings, states, enabled=True, now=NOW) == [
        "past_fresh"
    ]
