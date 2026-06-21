"""Pure decision logic for native auto-review.

Home-Assistant-free on purpose (stdlib + ``.util`` only) so the unit-test
harness can load it via ``importlib`` without installing Home Assistant. The
coordinator does the IO (calling ``api.leave_review`` and persisting state);
everything here is a pure function over plain dicts.

Design note — why this is coarse:
Sharetribe transitions are template-specific and not stable across processes
(see the project SKILL.md). Rather than try to detect the exact "provider can
review now" state, we attempt the review on any *past* booking within a bounded
window and let the transition endpoint be the source of truth: ``leave_review``
tries ``review-1`` then ``review-2`` and raises ``APIError`` if neither is
allowed yet. A failed attempt is simply retried on the next poll until the
window opens or the booking ages out. State is persisted, so this survives
Home Assistant restarts (unlike the old delay-based example automation).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .const import PROVIDER_REVIEW_DONE_TRANSITIONS
from .util import parse_iso_datetime

# Bounded attempt window after a booking ends: wide enough for Sharetribe to
# open the provider review window, narrow enough to stop hammering once the
# review period has clearly expired.
AUTO_REVIEW_MAX_AGE: timedelta = timedelta(days=14)

# Give up after this many failed attempts on one booking (belt-and-braces with
# the age cap, in case the API keeps rejecting).
MAX_AUTO_REVIEW_ATTEMPTS: int = 8


def is_reviewable(
    booking: dict[str, Any],
    now: datetime,
    *,
    max_age: timedelta = AUTO_REVIEW_MAX_AGE,
) -> bool:
    """Return True if an auto-review should be *attempted* for this booking now.

    Coarse by design (see module docstring): the booking must be ``past`` and
    its end must fall within ``[now - max_age, now]``. Whether the review can
    actually be posted is decided by the API when the attempt is made.
    """
    if booking.get("category") != "past":
        return False
    # Skip bookings the provider has already reviewed or whose review window has
    # lapsed — attempting those just wastes API calls.
    if booking.get("last_transition") in PROVIDER_REVIEW_DONE_TRANSITIONS:
        return False
    end = parse_iso_datetime(booking.get("booking_end"))
    if end is None:
        return False
    return end <= now <= end + max_age


def select_auto_reviews(
    bookings: list[dict[str, Any]],
    transaction_states: dict[str, dict[str, Any]],
    *,
    enabled: bool,
    now: datetime,
    reviewed_txn_ids: frozenset[str] = frozenset(),
    max_attempts: int = MAX_AUTO_REVIEW_ATTEMPTS,
    max_age: timedelta = AUTO_REVIEW_MAX_AGE,
) -> list[str]:
    """Return transaction ids that should have an auto-review attempted now.

    A transaction is selected when ALL hold:
    - ``enabled`` is True (the opt-in option);
    - it has a transaction id and is not already known-reviewed
      (``reviewed_txn_ids`` from the API, or ``auto_reviewed`` in the store);
    - it has not exhausted ``max_attempts`` prior auto-review attempts;
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
        if state.get("auto_review_attempts", 0) >= max_attempts:
            continue
        if not is_reviewable(booking, now, max_age=max_age):
            continue

        selected.append(txn_id)

    return selected
