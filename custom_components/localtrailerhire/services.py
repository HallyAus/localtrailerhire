"""Home Assistant service actions for Local Trailer Hire."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import APIError, AuthenticationError
from .const import (
    DEFAULT_REVIEW_CONTENT,
    DEFAULT_REVIEW_RATING,
    DOMAIN,
    EVENT_MESSAGE_SENT,
    EVENT_REVIEW_LEFT,
    PROVIDER_REVIEW_TRANSITIONS,
    SERVICE_ACCEPT_BOOKING,
    SERVICE_AUTO_REVIEW_DRY_RUN,
    SERVICE_AUTO_REVIEW_RETRY_NOW,
    SERVICE_CLEAR_CUSTOMER_HISTORY,
    SERVICE_CLEAR_MESSAGE_HISTORY,
    SERVICE_DECLINE_BOOKING,
    SERVICE_EXPORT_CUSTOMER_HISTORY,
    SERVICE_EXPORT_MESSAGE_HISTORY,
    SERVICE_FIRE_CONFIRMED_EVENTS,
    SERVICE_LEAVE_REVIEW,
    SERVICE_MARK_MESSAGE_SENT,
    SERVICE_REFRESH_NOW,
    SERVICE_SEND_MESSAGE,
    SERVICE_SYNC_MESSAGE_HISTORY,
    TRANSITION_ACCEPT,
    TRANSITION_DECLINE,
)
from .customer_history import export_customer_history
from .message_archive import count_archived_messages, export_message_archive

_LOGGER = logging.getLogger(__name__)

REGISTERED_SERVICES: tuple[str, ...] = (
    SERVICE_SEND_MESSAGE,
    SERVICE_REFRESH_NOW,
    SERVICE_MARK_MESSAGE_SENT,
    SERVICE_FIRE_CONFIRMED_EVENTS,
    SERVICE_ACCEPT_BOOKING,
    SERVICE_DECLINE_BOOKING,
    SERVICE_LEAVE_REVIEW,
    SERVICE_EXPORT_CUSTOMER_HISTORY,
    SERVICE_CLEAR_CUSTOMER_HISTORY,
    SERVICE_SYNC_MESSAGE_HISTORY,
    SERVICE_EXPORT_MESSAGE_HISTORY,
    SERVICE_CLEAR_MESSAGE_HISTORY,
    SERVICE_AUTO_REVIEW_DRY_RUN,
    SERVICE_AUTO_REVIEW_RETRY_NOW,
)

SERVICE_SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required("transaction_id"): cv.string,
        vol.Required("message"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)
SERVICE_TRANSACTION_SCHEMA = vol.Schema(
    {
        vol.Required("transaction_id"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)
SERVICE_FIRE_CONFIRMED_EVENTS_SCHEMA = vol.Schema(
    {
        vol.Optional("hours_back", default=24): cv.positive_int,
        vol.Optional("config_entry_id"): cv.string,
    }
)
SERVICE_ENTRY_SCHEMA = vol.Schema({vol.Optional("config_entry_id"): cv.string})
SERVICE_LEAVE_REVIEW_SCHEMA = vol.Schema(
    {
        vol.Required("transaction_id"): cv.string,
        vol.Optional("rating", default=DEFAULT_REVIEW_RATING): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=5)
        ),
        vol.Optional("review_content", default=DEFAULT_REVIEW_CONTENT): cv.string,
        vol.Optional("transition"): vol.In(PROVIDER_REVIEW_TRANSITIONS),
        vol.Optional("config_entry_id"): cv.string,
    }
)
SERVICE_EXPORT_SCHEMA = vol.Schema(
    {
        vol.Optional("format", default="json"): vol.In(("json", "csv")),
        vol.Optional("config_entry_id"): cv.string,
    }
)
SERVICE_CLEAR_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Optional("scope", default="all"): vol.In(("sensitive", "all")),
        vol.Optional("config_entry_id"): cv.string,
    }
)
SERVICE_SYNC_MESSAGES_SCHEMA = vol.Schema(
    {
        vol.Optional("batch_size", default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
        vol.Optional("config_entry_id"): cv.string,
    }
)
SERVICE_AUTO_REVIEW_DRY_RUN_SCHEMA = vol.Schema(
    {
        vol.Optional("transaction_id"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)
# A transaction id is deliberately mandatory here. A blank retry previously
# bypassed the opt-in setting and could post reviews to every coarse candidate.
SERVICE_AUTO_REVIEW_RETRY_SCHEMA = vol.Schema(
    {
        vol.Required("transaction_id"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)


def _entry_data(hass: HomeAssistant, config_entry_id: str | None) -> dict[str, Any]:
    """Return one loaded runtime, or raise a user-facing validation error."""
    entries = hass.data.get(DOMAIN, {})
    loaded = {
        entry_id: data
        for entry_id, data in entries.items()
        if isinstance(data, dict) and "api" in data and "coordinator" in data
    }
    if config_entry_id:
        if config_entry_id not in loaded:
            raise ServiceValidationError("The selected Local Trailer Hire entry is not loaded")
        return loaded[config_entry_id]
    if not loaded:
        raise ServiceValidationError("No Local Trailer Hire entry is loaded")
    if len(loaded) > 1:
        raise ServiceValidationError(
            "Multiple Local Trailer Hire entries are loaded; specify config_entry_id"
        )
    return next(iter(loaded.values()))


def _transaction_id(call: ServiceCall) -> str:
    """Validate and normalize a Sharetribe transaction UUID."""
    transaction_id = str(call.data.get("transaction_id") or "").strip()
    try:
        parsed = UUID(transaction_id)
    except (ValueError, AttributeError):
        raise ServiceValidationError("transaction_id must be a valid UUID") from None
    if str(parsed) != transaction_id.lower():
        raise ServiceValidationError("transaction_id must be a valid UUID")
    return str(parsed)


def _external_failure(action: str, err: Exception) -> HomeAssistantError:
    """Return an actionable error without exposing a remote response body."""
    if isinstance(err, AuthenticationError):
        return HomeAssistantError(
            "Authentication failed; reauthenticate the Local Trailer Hire entry"
        )
    return HomeAssistantError(
        f"{action} failed in Sharetribe ({type(err).__name__}); check integration diagnostics"
    )


def async_register_services(hass: HomeAssistant) -> None:
    """Register integration-wide actions during ``async_setup``."""

    async def send_message(call: ServiceCall) -> None:
        transaction_id = _transaction_id(call)
        message = str(call.data.get("message") or "").strip()
        if not message:
            raise ServiceValidationError("message cannot be empty")
        runtime = _entry_data(hass, call.data.get("config_entry_id"))
        try:
            await runtime["api"].send_message(transaction_id, message)
        except (APIError, AuthenticationError) as err:
            raise _external_failure("Sending the message", err) from err
        await runtime["coordinator"].mark_message_sent(transaction_id)
        hass.bus.async_fire(
            EVENT_MESSAGE_SENT,
            {"transaction_id": transaction_id, "timestamp": datetime.now(UTC).isoformat()},
        )

    async def refresh_now(call: ServiceCall) -> None:
        entry_id = call.data.get("config_entry_id")
        if entry_id:
            await _entry_data(hass, entry_id)["coordinator"].async_request_refresh()
            return
        runtimes = [
            value
            for value in hass.data.get(DOMAIN, {}).values()
            if isinstance(value, dict) and "coordinator" in value
        ]
        if not runtimes:
            raise ServiceValidationError("No Local Trailer Hire entry is loaded")
        for runtime in runtimes:
            await runtime["coordinator"].async_request_refresh()

    async def mark_message_sent(call: ServiceCall) -> None:
        runtime = _entry_data(hass, call.data.get("config_entry_id"))
        await runtime["coordinator"].mark_message_sent(_transaction_id(call))

    async def fire_confirmed_events(call: ServiceCall) -> None:
        runtime = _entry_data(hass, call.data.get("config_entry_id"))
        cutoff = datetime.now(UTC) - timedelta(hours=call.data.get("hours_back", 24))
        await runtime["coordinator"].fire_confirmed_events_since(cutoff, dry_run=False)

    async def transition(call: ServiceCall, transition_name: str) -> None:
        transaction_id = _transaction_id(call)
        runtime = _entry_data(hass, call.data.get("config_entry_id"))
        try:
            await runtime["api"].transition_transaction(transaction_id, transition_name)
        except (APIError, AuthenticationError) as err:
            raise _external_failure("Booking transition", err) from err
        await runtime["coordinator"].async_request_refresh()

    async def accept_booking(call: ServiceCall) -> None:
        await transition(call, TRANSITION_ACCEPT)

    async def decline_booking(call: ServiceCall) -> None:
        await transition(call, TRANSITION_DECLINE)

    async def leave_review(call: ServiceCall) -> None:
        transaction_id = _transaction_id(call)
        runtime = _entry_data(hass, call.data.get("config_entry_id"))
        try:
            result = await runtime["api"].leave_review(
                transaction_id,
                rating=call.data.get("rating", DEFAULT_REVIEW_RATING),
                content=call.data.get("review_content", DEFAULT_REVIEW_CONTENT),
                transition=call.data.get("transition"),
            )
        except (APIError, AuthenticationError) as err:
            raise _external_failure("Leaving the review", err) from err
        hass.bus.async_fire(
            EVENT_REVIEW_LEFT,
            {
                "transaction_id": transaction_id,
                "transition": result.get("transition"),
                "rating": call.data.get("rating", DEFAULT_REVIEW_RATING),
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        await runtime["coordinator"].async_request_refresh()

    async def export_customers(call: ServiceCall) -> dict[str, Any]:
        coordinator = _entry_data(hass, call.data.get("config_entry_id"))["coordinator"]
        output_format = call.data.get("format", "json")
        return {
            "format": output_format,
            "filename": f"localtrailerhire-customers.{output_format}",
            "customer_count": len(coordinator.customer_history),
            "content": export_customer_history(coordinator.customer_history, output_format),
        }

    async def clear_customers(call: ServiceCall) -> None:
        coordinator = _entry_data(hass, call.data.get("config_entry_id"))["coordinator"]
        await coordinator.clear_customer_history(call.data.get("scope", "all"))

    async def sync_messages(call: ServiceCall) -> dict[str, Any]:
        coordinator = _entry_data(hass, call.data.get("config_entry_id"))["coordinator"]
        return await coordinator.sync_message_history(call.data.get("batch_size", 10))

    async def export_messages(call: ServiceCall) -> dict[str, Any]:
        coordinator = _entry_data(hass, call.data.get("config_entry_id"))["coordinator"]
        output_format = call.data.get("format", "json")
        archive = coordinator.message_history
        return {
            "format": output_format,
            "filename": f"localtrailerhire-messages.{output_format}",
            "conversation_count": len(archive),
            "message_count": count_archived_messages(archive),
            "content": export_message_archive(archive, output_format),
        }

    async def clear_messages(call: ServiceCall) -> None:
        coordinator = _entry_data(hass, call.data.get("config_entry_id"))["coordinator"]
        await coordinator.clear_message_history()

    async def auto_review_dry_run(call: ServiceCall) -> dict[str, Any]:
        coordinator = _entry_data(hass, call.data.get("config_entry_id"))["coordinator"]
        return coordinator.auto_review_dry_run(call.data.get("transaction_id"))

    async def auto_review_retry(call: ServiceCall) -> dict[str, Any]:
        coordinator = _entry_data(hass, call.data.get("config_entry_id"))["coordinator"]
        return await coordinator.retry_auto_reviews_now(_transaction_id(call))

    definitions: tuple[tuple[str, Any, vol.Schema, SupportsResponse], ...] = (
        (SERVICE_SEND_MESSAGE, send_message, SERVICE_SEND_MESSAGE_SCHEMA, SupportsResponse.NONE),
        (SERVICE_REFRESH_NOW, refresh_now, SERVICE_ENTRY_SCHEMA, SupportsResponse.NONE),
        (
            SERVICE_MARK_MESSAGE_SENT,
            mark_message_sent,
            SERVICE_TRANSACTION_SCHEMA,
            SupportsResponse.NONE,
        ),
        (
            SERVICE_FIRE_CONFIRMED_EVENTS,
            fire_confirmed_events,
            SERVICE_FIRE_CONFIRMED_EVENTS_SCHEMA,
            SupportsResponse.NONE,
        ),
        (SERVICE_ACCEPT_BOOKING, accept_booking, SERVICE_TRANSACTION_SCHEMA, SupportsResponse.NONE),
        (
            SERVICE_DECLINE_BOOKING,
            decline_booking,
            SERVICE_TRANSACTION_SCHEMA,
            SupportsResponse.NONE,
        ),
        (SERVICE_LEAVE_REVIEW, leave_review, SERVICE_LEAVE_REVIEW_SCHEMA, SupportsResponse.NONE),
        (
            SERVICE_EXPORT_CUSTOMER_HISTORY,
            export_customers,
            SERVICE_EXPORT_SCHEMA,
            SupportsResponse.ONLY,
        ),
        (
            SERVICE_CLEAR_CUSTOMER_HISTORY,
            clear_customers,
            SERVICE_CLEAR_HISTORY_SCHEMA,
            SupportsResponse.NONE,
        ),
        (
            SERVICE_SYNC_MESSAGE_HISTORY,
            sync_messages,
            SERVICE_SYNC_MESSAGES_SCHEMA,
            SupportsResponse.OPTIONAL,
        ),
        (
            SERVICE_EXPORT_MESSAGE_HISTORY,
            export_messages,
            SERVICE_EXPORT_SCHEMA,
            SupportsResponse.ONLY,
        ),
        (
            SERVICE_CLEAR_MESSAGE_HISTORY,
            clear_messages,
            SERVICE_ENTRY_SCHEMA,
            SupportsResponse.NONE,
        ),
        (
            SERVICE_AUTO_REVIEW_DRY_RUN,
            auto_review_dry_run,
            SERVICE_AUTO_REVIEW_DRY_RUN_SCHEMA,
            SupportsResponse.ONLY,
        ),
        (
            SERVICE_AUTO_REVIEW_RETRY_NOW,
            auto_review_retry,
            SERVICE_AUTO_REVIEW_RETRY_SCHEMA,
            SupportsResponse.OPTIONAL,
        ),
    )
    for name, handler, schema, response in definitions:
        if not hass.services.has_service(DOMAIN, name):
            hass.services.async_register(
                DOMAIN,
                name,
                handler,
                schema=schema,
                supports_response=response,
            )
