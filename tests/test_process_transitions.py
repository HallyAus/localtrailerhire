"""Safe, isolated tests for Sharetribe offered-transition discovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from lth_api import ProcessTransitionsUnavailableError, SharetribeFlexAPI


class _Response:
    def __init__(self, body: Any, status: int = 200) -> None:
        self.status = status
        self._body = body
        self.headers = {"Content-Type": "application/json"}

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def json(self) -> Any:
        return self._body


class _Session:
    def __init__(self, responses: list[_Response]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        self.calls.append((method, url, kwargs))
        return self._responses.pop(0)


def _api(responses: list[_Response]) -> SharetribeFlexAPI:
    api = SharetribeFlexAPI(session=_Session(responses), client_id="public-client-id")
    api._access_token = "test-token"
    api._token_expiry = datetime.now(UTC) + timedelta(hours=1)
    return api


def test_parse_process_transitions_accepts_live_id_shape():
    payload = {
        "data": [
            {"id": "transition/expire-review-period", "type": "processTransition"},
            {"id": "transition/review-1-by-customer", "type": "processTransition"},
            {"id": "transition/review-1-by-provider", "type": "processTransition"},
        ]
    }

    assert SharetribeFlexAPI.parse_process_transitions(payload) == (
        "transition/expire-review-period",
        "transition/review-1-by-customer",
        "transition/review-1-by-provider",
    )


def test_parse_process_transitions_accepts_attribute_shapes_and_deduplicates():
    payload = {
        "data": [
            {"attributes": {"transition": "review-2-by-provider"}},
            {"attributes": {"name": "transition/review-2-by-provider"}},
            {"id": {"name": "transition/review-1-by-customer"}},
        ]
    }

    assert SharetribeFlexAPI.parse_process_transitions(payload) == (
        "transition/review-2-by-provider",
        "transition/review-1-by-customer",
    )


def test_parse_process_transitions_ignores_unknown_json_api_ids():
    payload = {
        "data": [
            {"id": {"uuid": "customer-id"}},
            {"id": "25c25801-eaf1-4750-931b-55046633a13c"},
            "bad",
            None,
        ]
    }
    assert SharetribeFlexAPI.parse_process_transitions(payload) == ()


def test_parse_process_transitions_prefers_attributes_over_opaque_string_id():
    payload = {
        "data": [
            {
                "id": "25c25801-eaf1-4750-931b-55046633a13c",
                "attributes": {"transition": "review-1-by-provider"},
            }
        ]
    }

    assert SharetribeFlexAPI.parse_process_transitions(payload) == (
        "transition/review-1-by-provider",
    )


@pytest.mark.asyncio
async def test_get_available_process_transitions_uses_transaction_id_only():
    api = _api([_Response({"data": [{"id": "transition/review-1-by-provider"}]})])

    result = await api.get_available_process_transitions("txn-123")

    assert result == ("transition/review-1-by-provider",)
    method, url, kwargs = api._session.calls[0]
    assert method == "GET"
    assert url.endswith("/process_transitions/query")
    assert kwargs["params"] == {"transactionId": "txn-123"}


@pytest.mark.asyncio
async def test_lookup_compatibility_path_keeps_transaction_scope():
    api = _api(
        [
            _Response({}, status=400),
            _Response({"data": {"attributes": {"processName": "default-booking"}}}),
            _Response({"data": [{"attributes": {"name": "review-2-by-provider"}}]}),
        ]
    )

    result = await api.get_available_process_transitions("txn-123")

    assert result == ("transition/review-2-by-provider",)
    assert api._session.calls[1][2]["params"] == {"id": "txn-123"}
    assert api._session.calls[2][2]["params"] == {
        "transactionId": "txn-123",
        "processName": "default-booking",
    }


@pytest.mark.asyncio
async def test_unrecognised_lookup_payload_fails_closed():
    api = _api([_Response({"data": [{"id": {"uuid": "not-a-transition"}}]})])

    with pytest.raises(ProcessTransitionsUnavailableError, match="no recognised"):
        await api.get_available_process_transitions("txn-123")

    assert len(api._session.calls) == 1


@pytest.mark.asyncio
async def test_failed_primary_and_compatibility_lookup_fails_closed():
    api = _api(
        [
            _Response({}, status=400),
            _Response({"data": {"attributes": {"processName": "default-booking"}}}),
            _Response({}, status=400),
        ]
    )

    with pytest.raises(ProcessTransitionsUnavailableError, match="Unable to verify"):
        await api.get_available_process_transitions("txn-123")

    assert len(api._session.calls) == 3
