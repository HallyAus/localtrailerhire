"""Tests for const-level conventions (frozensets, retryable statuses)."""

from __future__ import annotations

from lth_pkg.const import (
    CONFIRMED_TRANSITIONS,
    PAYOUT_TRANSITIONS,
    PROVIDER_REVIEW_DONE_TRANSITIONS,
    REQUEST_TRANSITIONS,
    RETRYABLE_STATUSES,
)


def test_transition_sets_are_frozensets():
    # CLAUDE.md: transition sets are frozensets for fast, immutable membership.
    assert isinstance(PAYOUT_TRANSITIONS, frozenset)
    assert isinstance(CONFIRMED_TRANSITIONS, frozenset)
    assert isinstance(REQUEST_TRANSITIONS, frozenset)


def test_payout_transitions_membership():
    assert "transition/complete" in PAYOUT_TRANSITIONS
    assert "transition/review-2-by-provider" in PAYOUT_TRANSITIONS


def test_provider_review_done_transitions_cover_terminal_marketplace_states():
    assert {
        "transition/review-2-by-customer",
        "transition/expire-review-period",
        "transition/expire-customer-review-period",
        "transition/expire-provider-review-period",
        "transition/payout-after-reviews",
    } <= PROVIDER_REVIEW_DONE_TRANSITIONS
    assert "transition/review-1-by-customer" not in PROVIDER_REVIEW_DONE_TRANSITIONS


def test_retryable_statuses():
    assert {429, 502, 503, 504} <= RETRYABLE_STATUSES
    assert 200 not in RETRYABLE_STATUSES
    assert 401 not in RETRYABLE_STATUSES
