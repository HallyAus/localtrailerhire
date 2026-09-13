"""Unit tests for the SharetribeFlexAPI.leave_review fallback logic."""

from __future__ import annotations

from typing import Any

import pytest
from lth_api import (
    APIError,
    ProcessTransitionsUnavailableError,
    ProviderReviewNotOfferedError,
    SharetribeFlexAPI,
)


class _FakeAPI:
    """Stand-in that records calls to transition_transaction and replays scripted results."""

    def __init__(
        self,
        scripted: list[Any],
        *,
        offered: tuple[str, ...] | Exception = ("transition/review-1-by-provider",),
    ) -> None:
        self._scripted = list(scripted)
        self._offered = offered
        self.calls: list[dict[str, Any]] = []
        self.lookup_calls: list[str] = []

    async def get_available_process_transitions(self, transaction_id: str) -> tuple[str, ...]:
        self.lookup_calls.append(transaction_id)
        if isinstance(self._offered, Exception):
            raise self._offered
        return self._offered

    async def transition_transaction(
        self,
        transaction_id: str,
        transition: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {"transaction_id": transaction_id, "transition": transition, "params": params}
        )
        outcome = self._scripted.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def _run_leave_review(fake: _FakeAPI, **kwargs: Any) -> dict[str, Any]:
    """Bind the real leave_review method to the fake and invoke it."""
    return await SharetribeFlexAPI.leave_review(
        fake,  # type: ignore[arg-type]
        **kwargs,
    )


@pytest.mark.asyncio
async def test_leave_review_uses_review_1_first_on_success():
    fake = _FakeAPI([{"success": True, "status_code": 200}])
    result = await _run_leave_review(
        fake,
        transaction_id="abc",
        rating=5,
        content="Great hirer!",
    )

    assert result["success"] is True
    assert result["transition"] == "transition/review-1-by-provider"
    assert fake.lookup_calls == ["abc"]
    assert len(fake.calls) == 1
    assert fake.calls[0]["transition"] == "transition/review-1-by-provider"
    assert fake.calls[0]["params"] == {"reviewRating": 5, "reviewContent": "Great hirer!"}


@pytest.mark.asyncio
async def test_leave_review_uses_review_2_when_it_is_the_offered_transition():
    fake = _FakeAPI(
        [{"success": True, "status_code": 200}],
        offered=("transition/review-2-by-provider",),
    )
    result = await _run_leave_review(
        fake,
        transaction_id="abc",
        rating=4,
        content="Solid customer.",
    )

    assert result["success"] is True
    assert result["transition"] == "transition/review-2-by-provider"
    assert [c["transition"] for c in fake.calls] == ["transition/review-2-by-provider"]


@pytest.mark.asyncio
async def test_leave_review_propagates_failure_without_guessing_another_transition():
    fake = _FakeAPI(
        [APIError("offered transition failed")],
        offered=(
            "transition/review-1-by-provider",
            "transition/review-2-by-provider",
        ),
    )
    with pytest.raises(APIError, match="offered transition failed"):
        await _run_leave_review(fake, transaction_id="abc", rating=5, content="hi")
    assert [call["transition"] for call in fake.calls] == ["transition/review-1-by-provider"]


@pytest.mark.asyncio
async def test_leave_review_honours_explicit_transition():
    fake = _FakeAPI(
        [{"success": True, "status_code": 200}],
        offered=("transition/review-2-by-provider",),
    )
    await _run_leave_review(
        fake,
        transaction_id="abc",
        rating=5,
        content="hi",
        transition="transition/review-2-by-provider",
    )
    assert [c["transition"] for c in fake.calls] == ["transition/review-2-by-provider"]


@pytest.mark.asyncio
async def test_leave_review_does_not_post_when_provider_transition_not_offered():
    fake = _FakeAPI(
        [],
        offered=(
            "transition/expire-review-period",
            "transition/review-1-by-customer",
        ),
    )

    with pytest.raises(ProviderReviewNotOfferedError, match="not currently offering"):
        await _run_leave_review(fake, transaction_id="abc", rating=5, content="hi")

    assert fake.lookup_calls == ["abc"]
    assert fake.calls == []


@pytest.mark.asyncio
async def test_leave_review_does_not_post_when_transition_lookup_fails():
    fake = _FakeAPI(
        [],
        offered=ProcessTransitionsUnavailableError("lookup unavailable"),
    )

    with pytest.raises(ProcessTransitionsUnavailableError, match="lookup unavailable"):
        await _run_leave_review(fake, transaction_id="abc", rating=5, content="hi")

    assert fake.calls == []


@pytest.mark.asyncio
async def test_leave_review_rejects_non_provider_explicit_transition_before_lookup():
    fake = _FakeAPI([])

    with pytest.raises(APIError, match="Unsupported provider review transition"):
        await _run_leave_review(
            fake,
            transaction_id="abc",
            rating=5,
            content="hi",
            transition="transition/cancel-by-customer",
        )

    assert fake.lookup_calls == []
    assert fake.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_rating", [0, 6, -1, 100])
async def test_leave_review_rejects_out_of_range_rating(bad_rating: int):
    fake = _FakeAPI([])
    with pytest.raises(APIError, match="rating"):
        await _run_leave_review(fake, transaction_id="abc", rating=bad_rating, content="hi")
    assert fake.calls == []


@pytest.mark.asyncio
async def test_leave_review_rejects_empty_content():
    fake = _FakeAPI([])
    with pytest.raises(APIError, match="content"):
        await _run_leave_review(fake, transaction_id="abc", rating=5, content="   ")
    assert fake.calls == []
