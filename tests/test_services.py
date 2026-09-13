"""Service registration and safety regressions without a full HA install."""

from __future__ import annotations

import importlib.util
import sys
from enum import Enum
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
import voluptuous as vol

COMPONENT = Path(__file__).resolve().parent.parent / "custom_components" / "localtrailerhire"


class FakeHomeAssistantError(Exception):
    """Home Assistant action failure."""


class FakeServiceValidationError(FakeHomeAssistantError):
    """Home Assistant action-input failure."""


class FakeSupportsResponse(Enum):
    """Response modes used by service registration."""

    NONE = "none"
    OPTIONAL = "optional"
    ONLY = "only"


def _load_services() -> ModuleType:
    """Load services.py against focused Home Assistant protocol stubs."""
    homeassistant = ModuleType("homeassistant")
    core = ModuleType("homeassistant.core")
    core.HomeAssistant = object
    core.ServiceCall = object
    core.SupportsResponse = FakeSupportsResponse
    exceptions = ModuleType("homeassistant.exceptions")
    exceptions.HomeAssistantError = FakeHomeAssistantError
    exceptions.ServiceValidationError = FakeServiceValidationError
    helpers = ModuleType("homeassistant.helpers")
    config_validation = ModuleType("homeassistant.helpers.config_validation")
    config_validation.string = str
    config_validation.positive_int = vol.All(vol.Coerce(int), vol.Range(min=1))
    helpers.config_validation = config_validation

    replacements = {
        "homeassistant": homeassistant,
        "homeassistant.core": core,
        "homeassistant.exceptions": exceptions,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.config_validation": config_validation,
    }
    originals = {name: sys.modules.get(name) for name in replacements}
    name = "lth_pkg.services"
    original_service_module = sys.modules.get(name)
    try:
        sys.modules.update(replacements)
        spec = importlib.util.spec_from_file_location(name, COMPONENT / "services.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for module_name, original in originals.items():
            if original is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original
        if original_service_module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original_service_module


SERVICES = _load_services()


class FakeRegistry:
    """Capture Home Assistant action registrations."""

    def __init__(self) -> None:
        self.registered: dict[str, dict[str, Any]] = {}

    def has_service(self, _domain: str, service: str) -> bool:
        return service in self.registered

    def async_register(
        self,
        _domain: str,
        service: str,
        handler: Any,
        *,
        schema: vol.Schema,
        supports_response: FakeSupportsResponse,
    ) -> None:
        self.registered[service] = {
            "handler": handler,
            "schema": schema,
            "supports_response": supports_response,
        }


def _hass() -> SimpleNamespace:
    return SimpleNamespace(
        data={}, services=FakeRegistry(), bus=SimpleNamespace(async_fire=lambda *_: None)
    )


def _loaded_hass() -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace]:
    """Return one loaded fake runtime with no network-capable objects."""
    coordinator = SimpleNamespace(
        customer_history={"customer-1": {"transactions": {}}},
        message_history={
            "11111111-2222-3333-4444-555555555555": {
                "messages": {"message-1": {"content": "hello"}}
            }
        },
        mark_message_sent=AsyncMock(),
        async_request_refresh=AsyncMock(),
        fire_confirmed_events_since=AsyncMock(),
        clear_customer_history=AsyncMock(),
        sync_message_history=AsyncMock(return_value={"complete": True}),
        clear_message_history=AsyncMock(),
        auto_review_dry_run=lambda transaction_id: {"transaction_id": transaction_id},
        retry_auto_reviews_now=AsyncMock(return_value={"posted": 1}),
    )
    api = SimpleNamespace(
        send_message=AsyncMock(),
        transition_transaction=AsyncMock(),
        leave_review=AsyncMock(return_value={"transition": "transition/review-1-by-provider"}),
    )
    events: list[tuple[Any, ...]] = []
    hass = _hass()
    hass.bus = SimpleNamespace(async_fire=lambda *args: events.append(args))
    hass.events = events
    hass.data = {
        SERVICES.DOMAIN: {
            "entry-1": {"api": api, "coordinator": coordinator},
        }
    }
    return hass, api, coordinator


def test_registers_every_action_once() -> None:
    """Integration-wide actions are stable and idempotent."""
    hass = _hass()

    SERVICES.async_register_services(hass)
    SERVICES.async_register_services(hass)

    assert set(hass.services.registered) == set(SERVICES.REGISTERED_SERVICES)


def test_retry_schema_requires_one_explicit_transaction() -> None:
    """Retry-all cannot bypass the auto-review opt-in setting."""
    hass = _hass()
    SERVICES.async_register_services(hass)
    schema = hass.services.registered["auto_review_retry_now"]["schema"]

    with pytest.raises(vol.Invalid):
        schema({})

    transaction_id = "11111111-2222-3333-4444-555555555555"
    assert schema({"transaction_id": transaction_id})["transaction_id"] == transaction_id


def test_transaction_id_rejects_uuid_shaped_non_hex_value() -> None:
    """UUID punctuation alone must not be enough to reach Sharetribe."""
    call = SimpleNamespace(data={"transaction_id": "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz"})

    with pytest.raises(FakeServiceValidationError, match="valid UUID"):
        SERVICES._transaction_id(call)


@pytest.mark.asyncio
async def test_loaded_entry_error_is_user_facing() -> None:
    """Registered actions explain when their config entry is not loaded."""
    hass = _hass()
    SERVICES.async_register_services(hass)
    handler = hass.services.registered["auto_review_dry_run"]["handler"]

    with pytest.raises(FakeServiceValidationError, match="entry is loaded"):
        await handler(SimpleNamespace(data={}))


@pytest.mark.asyncio
async def test_message_export_counts_only_valid_messages_in_malformed_storage() -> None:
    """A damaged archive record must not make the export action crash."""
    hass = _hass()
    coordinator = SimpleNamespace(
        message_history={
            "broken": None,
            "mixed": {
                "messages": {
                    "valid": {"id": "valid", "content": "Example"},
                    "invalid": None,
                }
            },
        }
    )
    hass.data = {
        SERVICES.DOMAIN: {
            "entry-1": {"api": object(), "coordinator": coordinator},
        }
    }
    SERVICES.async_register_services(hass)
    handler = hass.services.registered["export_message_history"]["handler"]

    response = await handler(SimpleNamespace(data={"format": "json"}))

    assert response["conversation_count"] == 2
    assert response["message_count"] == 1


@pytest.mark.asyncio
async def test_write_handlers_use_the_loaded_runtime_and_refresh() -> None:
    """Service extraction preserves the guarded message/review call paths."""
    hass, api, coordinator = _loaded_hass()
    SERVICES.async_register_services(hass)
    transaction_id = "11111111-2222-3333-4444-555555555555"

    await hass.services.registered["send_message"]["handler"](
        SimpleNamespace(data={"transaction_id": transaction_id, "message": " Thanks "})
    )
    await hass.services.registered["leave_review"]["handler"](
        SimpleNamespace(data={"transaction_id": transaction_id})
    )

    api.send_message.assert_awaited_once_with(transaction_id, "Thanks")
    coordinator.mark_message_sent.assert_awaited_once_with(transaction_id)
    api.leave_review.assert_awaited_once()
    coordinator.async_request_refresh.assert_awaited_once()
    assert len(hass.events) == 2


@pytest.mark.asyncio
async def test_response_handlers_return_archives_and_dry_run() -> None:
    """Read-only service responses keep their documented result shapes."""
    hass, _api, _coordinator = _loaded_hass()
    SERVICES.async_register_services(hass)

    customers = await hass.services.registered["export_customer_history"]["handler"](
        SimpleNamespace(data={"format": "json"})
    )
    messages = await hass.services.registered["export_message_history"]["handler"](
        SimpleNamespace(data={"format": "json"})
    )
    dry_run = await hass.services.registered["auto_review_dry_run"]["handler"](
        SimpleNamespace(data={"transaction_id": "one-booking"})
    )

    assert customers["customer_count"] == 1
    assert messages["conversation_count"] == 1
    assert messages["message_count"] == 1
    assert dry_run == {"transaction_id": "one-booking"}


@pytest.mark.asyncio
async def test_retry_handler_forwards_one_canonical_uuid() -> None:
    """Manual retry cannot become a bulk operation after registration."""
    hass, _api, coordinator = _loaded_hass()
    SERVICES.async_register_services(hass)
    transaction_id = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"

    result = await hass.services.registered["auto_review_retry_now"]["handler"](
        SimpleNamespace(data={"transaction_id": transaction_id})
    )

    coordinator.retry_auto_reviews_now.assert_awaited_once_with(transaction_id.lower())
    assert result == {"posted": 1}
