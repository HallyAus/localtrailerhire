"""Pure decision logic for native auto-review.

Home-Assistant-free on purpose (stdlib + ``.util`` only) so the unit-test
harness can load it via ``importlib`` without installing Home Assistant. The
coordinator does the IO (calling ``api.leave_review`` and persisting state);
everything here is a pure function over plain dicts.

Sharetribe transitions are template-specific and not stable across processes.
This module performs a conservative local pre-filter; ``api.leave_review`` then
queries Sharetribe's currently offered process transitions and fails closed
unless a provider-review transition is explicitly offered. Failed attempts use
a persisted exponential backoff. State survives Home Assistant restarts.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .const import PROVIDER_REVIEW_DONE_TRANSITIONS, PROVIDER_REVIEW_TRANSITIONS
from .util import parse_iso_datetime

# Backwards-compatible optional query bound. It is no longer the default
# eligibility authority; Sharetribe's currently offered transitions are.
AUTO_REVIEW_MAX_AGE: timedelta = timedelta(days=14)

_NON_REVIEWABLE_MARKERS = (
    "abort",
    "cancel",
    "declin",
    "enquire",
    "expire-payment",
    "expired",
)

# A transaction may become date-past before its Sharetribe process opens the
# review transition. Back off failures instead of exhausting a small retry
# count during that gap. The cap still gives several attempts per day while
# keeping API traffic bounded across the full review window.
AUTO_REVIEW_RETRY_BASE: timedelta = timedelta(minutes=30)
AUTO_REVIEW_RETRY_MAX: timedelta = timedelta(hours=12)


def auto_review_retry_delay(attempts: int) -> timedelta:
    """Return the delay after ``attempts`` consecutive failed review posts."""
    exponent = min(max(0, attempts - 1), 5)
    delay = AUTO_REVIEW_RETRY_BASE * (2**exponent)
    return min(delay, AUTO_REVIEW_RETRY_MAX)


def auto_review_retry_due(state: dict[str, Any], now: datetime) -> bool:
    """Return whether a persisted failed review may be attempted again."""
    retry_at = parse_iso_datetime(state.get("auto_review_next_attempt_at"))
    # Missing/invalid timestamps include v1.3/v1.4 states that exhausted the
    # old eight-attempt cap. Treat those as due so upgrades recover them.
    return retry_at is None or now >= retry_at


def auto_review_failure_state(
    state: dict[str, Any], now: datetime, failure_reason: str | None = None
) -> dict[str, Any]:
    """Return persisted retry metadata after one failed review attempt."""
    try:
        previous_attempts = int(state.get("auto_review_attempts", 0))
    except (TypeError, ValueError):
        previous_attempts = 0
    attempts = max(0, previous_attempts) + 1
    update = {
        "auto_review_attempts": attempts,
        "auto_review_last_attempt_at": now.isoformat(),
        "auto_review_next_attempt_at": (now + auto_review_retry_delay(attempts)).isoformat(),
    }
    if failure_reason:
        update["auto_review_last_failure"] = failure_reason
    return update


def is_reviewable(
    booking: dict[str, Any],
    now: datetime,
    *,
    max_age: timedelta | None = None,
) -> bool:
    """Return True if an auto-review should be *attempted* for this booking now.

    This is a local pre-filter only. The booking must be past, not cancelled or
    otherwise terminal, and not already provider-reviewed. Sharetribe's offered
    transitions are the final authority in ``api.leave_review``. ``max_age`` is
    retained as an optional caller-supplied query bound, not an eligibility rule.
    """
    if booking.get("category") != "past":
        return False
    # Skip bookings the provider has already reviewed or whose review window has
    # lapsed — attempting those just wastes API calls.
    if booking.get("provider_review_done") or (
        booking.get("last_transition") in PROVIDER_REVIEW_DONE_TRANSITIONS
    ):
        return False
    lifecycle_values = (
        booking.get("last_transition"),
        booking.get("transaction_state"),
        booking.get("process_name"),
    )
    if any(
        marker in value.lower()
        for value in lifecycle_values
        if isinstance(value, str)
        for marker in _NON_REVIEWABLE_MARKERS
    ):
        return False

    offered = booking.get("offered_transitions")
    if offered is not None:
        return isinstance(offered, (list, tuple, set, frozenset)) and any(
            transition in PROVIDER_REVIEW_TRANSITIONS for transition in offered
        )

    end = parse_iso_datetime(booking.get("booking_end"))
    if end is None:
        return False
    return end <= now and (max_age is None or now <= end + max_age)


def select_auto_reviews(
    bookings: list[dict[str, Any]],
    transaction_states: dict[str, dict[str, Any]],
    *,
    enabled: bool,
    now: datetime,
    reviewed_txn_ids: frozenset[str] = frozenset(),
    max_age: timedelta | None = None,
    ignore_backoff: bool = False,
) -> list[str]:
    """Return transaction ids that should have an auto-review attempted now.

    A transaction is selected when ALL hold:
    - ``enabled`` is True (the opt-in option);
    - it has a transaction id and is not already known-reviewed
      (``reviewed_txn_ids`` from the API, or ``auto_reviewed`` in the store);
    - any persisted retry backoff has elapsed;
    - ``is_reviewable`` (past + within the age window).
    """
    if not enabled:
        return []

    selected: list[str] = []
    for booking in bookings:
        txn_id = booking.get("transaction_id")
        if not txn_id or txn_id in reviewed_txn_ids:
            continue

        state = transaction_states.get(txn_id) or {}
        if state.get("auto_reviewed"):
            continue
        if not ignore_backoff and not auto_review_retry_due(state, now):
            continue
        if not is_reviewable(booking, now, max_age=max_age):
            continue

        selected.append(txn_id)

    return selected


def summarize_auto_reviews(
    transaction_states: dict[str, dict[str, Any]],
    *,
    enabled: bool,
    rating: int,
) -> dict[str, Any]:
    """Build an at-a-glance auto-review status from the persisted store.

    Returns whether auto-review is armed, the configured rating, how many
    transactions have been auto-reviewed, the latest auto-review timestamp +
    transaction, and how many bookings have failed attempts still pending retry.
    """
    last_at: str | None = None
    last_txn: str | None = None
    reviewed_total = 0
    pending_retries = 0
    next_attempt_at: str | None = None
    last_failure: str | None = None
    last_failure_at: str | None = None

    for txn_id, state in transaction_states.items():
        if state.get("auto_reviewed"):
            reviewed_total += 1
            at = state.get("auto_reviewed_at")
            if at and (last_at is None or at > last_at):
                last_at = at
                last_txn = txn_id
        elif state.get("auto_review_attempts", 0) > 0:
            pending_retries += 1
            retry_at = state.get("auto_review_next_attempt_at")
            if retry_at and (next_attempt_at is None or retry_at < next_attempt_at):
                next_attempt_at = retry_at
            failed_at = state.get("auto_review_last_attempt_at")
            if failed_at and (last_failure_at is None or failed_at > last_failure_at):
                last_failure_at = failed_at
                last_failure = state.get("auto_review_last_failure")

    return {
        "enabled": enabled,
        "rating": rating,
        "auto_reviewed_total": reviewed_total,
        "last_auto_review_at": last_at,
        "last_auto_review_transaction": last_txn,
        "pending_retries": pending_retries,
        "next_attempt_at": next_attempt_at,
        "last_failure_at": last_failure_at,
        "last_failure": last_failure,
    }
