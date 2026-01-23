"""The Local Trailer Hire integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import APIError, AuthenticationError, SharetribeFlexAPI
from .const import (
    CATEGORY_UPCOMING,
    CONF_CLIENT_ID,
    CONF_INCLUDE_SENSITIVE,
    CONF_LAST_TRANSITIONS,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONFIRMED_TRANSITIONS,
    DEFAULT_INCLUDE_SENSITIVE,
    DEFAULT_LAST_TRANSITIONS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_BOOKING_CONFIRMED,
    EVENT_MESSAGE_SENT,
    SERVICE_SEND_MESSAGE,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

# Service schema
SERVICE_SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required("transaction_id"): cv.string,
        vol.Required("message"): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Local Trailer Hire from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Initialize storage for tracking sent messages and seen states
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    stored_data = await store.async_load() or {}
    if "sent_messages" not in stored_data:
        stored_data["sent_messages"] = {}
    if "seen_transitions" not in stored_data:
        stored_data["seen_transitions"] = {}

    # Get configuration
    client_id = entry.data[CONF_CLIENT_ID]
    username = entry.data.get(CONF_USERNAME)
    password = entry.data.get(CONF_PASSWORD)
    refresh_token = entry.data.get(CONF_REFRESH_TOKEN)

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    transitions_str = entry.options.get(
        CONF_LAST_TRANSITIONS, ",".join(DEFAULT_LAST_TRANSITIONS)
    )
    last_transitions = [t.strip() for t in transitions_str.split(",") if t.strip()]
    include_sensitive = entry.options.get(CONF_INCLUDE_SENSITIVE, DEFAULT_INCLUDE_SENSITIVE)

    # Create API client
    session = async_get_clientsession(hass)
    api = SharetribeFlexAPI(
        session=session,
        client_id=client_id,
        username=username,
        password=password,
        refresh_token=refresh_token,
    )

    # Test authentication
    try:
        await api.authenticate()
    except AuthenticationError as err:
        raise ConfigEntryAuthFailed("Authentication failed") from err
    except APIError as err:
        raise ConfigEntryNotReady("API connection failed") from err

    # Update refresh token if changed
    if api.refresh_token and api.refresh_token != refresh_token:
        new_data = dict(entry.data)
        new_data[CONF_REFRESH_TOKEN] = api.refresh_token
        hass.config_entries.async_update_entry(entry, data=new_data)

    # Create coordinator
    coordinator = LocalTrailerHireCoordinator(
        hass=hass,
        api=api,
        entry=entry,
        last_transitions=last_transitions,
        include_sensitive=include_sensitive,
        update_interval=timedelta(minutes=scan_interval),
        store=store,
        stored_data=stored_data,
    )

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "api": api,
        "store": store,
        "stored_data": stored_data,
    }

    # Register services (only once per domain)
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE):
        async def async_send_message(call: ServiceCall) -> None:
            """Handle send_message service call."""
            transaction_id = call.data.get("transaction_id", "")
            message = call.data.get("message", "")

            # Validate inputs
            if not transaction_id or not isinstance(transaction_id, str):
                raise HomeAssistantError(
                    "transaction_id is required and must be a non-empty string"
                )

            # Basic UUID format validation (should be 36 chars with hyphens)
            transaction_id = transaction_id.strip()
            if len(transaction_id) != 36 or transaction_id.count("-") != 4:
                raise HomeAssistantError(
                    f"transaction_id must be a valid UUID format (got: {transaction_id[:20]}...)"
                )

            if not message or not isinstance(message, str):
                raise HomeAssistantError(
                    "message is required and must be a non-empty string"
                )

            message = message.strip()
            if not message:
                raise HomeAssistantError("message cannot be empty or whitespace only")

            # Find the API client (use first available entry)
            api_client = None
            for entry_data in hass.data[DOMAIN].values():
                if isinstance(entry_data, dict) and "api" in entry_data:
                    api_client = entry_data["api"]
                    break

            if not api_client:
                _LOGGER.error("No API client available for send_message service")
                raise HomeAssistantError(
                    "No Local Trailer Hire integration configured"
                )

            try:
                await api_client.send_message(transaction_id, message)

                # Fire event for successful message send
                hass.bus.async_fire(
                    EVENT_MESSAGE_SENT,
                    {
                        "transaction_id": transaction_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )

                _LOGGER.info("Message sent to transaction %s", transaction_id)

            except AuthenticationError as err:
                _LOGGER.error("Authentication failed when sending message: %s", err)
                raise HomeAssistantError(
                    "Authentication failed. Please reconfigure the integration."
                ) from err

            except APIError as err:
                _LOGGER.error("Failed to send message: %s", err)
                raise HomeAssistantError(
                    f"Failed to send message: {err}"
                ) from err

            except Exception as err:
                _LOGGER.exception("Unexpected error sending message: %s", err)
                raise HomeAssistantError(
                    f"Unexpected error: {type(err).__name__}"
                ) from err

        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_MESSAGE,
            async_send_message,
            schema=SERVICE_SEND_MESSAGE_SCHEMA,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


class LocalTrailerHireCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Coordinator for Local Trailer Hire data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: SharetribeFlexAPI,
        entry: ConfigEntry,
        last_transitions: list[str],
        include_sensitive: bool,
        update_interval: timedelta,
        store: Store,
        stored_data: dict[str, Any],
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.api = api
        self.entry = entry
        self.last_transitions = last_transitions
        self.include_sensitive = include_sensitive
        self._store = store
        self._stored_data = stored_data
        self._previous_transitions: dict[str, str] = {}  # txn_id -> last_transition

    async def _async_update_data(self) -> list[dict[str, Any]]:
        """Fetch data from API."""
        try:
            bookings = await self.api.get_transactions(
                last_transitions=self.last_transitions,
                include_sensitive=self.include_sensitive,
            )

            # Update refresh token if it changed
            if (
                self.api.refresh_token
                and self.api.refresh_token != self.entry.data.get(CONF_REFRESH_TOKEN)
            ):
                new_data = dict(self.entry.data)
                new_data[CONF_REFRESH_TOKEN] = self.api.refresh_token
                self.hass.config_entries.async_update_entry(self.entry, data=new_data)

            # Detect newly confirmed bookings and fire events
            await self._detect_confirmed_bookings(bookings)

            # Log categorized counts
            upcoming_count = sum(1 for b in bookings if b.get("category") == CATEGORY_UPCOMING)
            _LOGGER.debug(
                "Fetched %d total bookings (%d upcoming)",
                len(bookings),
                upcoming_count,
            )
            return bookings

        except AuthenticationError as err:
            # Trigger reauth flow
            raise ConfigEntryAuthFailed("Authentication failed") from err

        except APIError as err:
            raise UpdateFailed(f"API error: {err}") from err

        except Exception as err:
            _LOGGER.exception("Unexpected error fetching data")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def _detect_confirmed_bookings(
        self, bookings: list[dict[str, Any]]
    ) -> None:
        """Detect newly confirmed bookings and fire events.

        A booking is considered "newly confirmed" when:
        1. Its last_transition is in CONFIRMED_TRANSITIONS
        2. booking_start is in the future
        3. We haven't seen this transition state for this transaction before
        """
        now = datetime.now(timezone.utc)
        seen_transitions = self._stored_data.get("seen_transitions", {})
        changes_made = False

        for booking in bookings:
            txn_id = booking.get("transaction_id")
            last_transition = booking.get("last_transition")
            booking_start_str = booking.get("booking_start")

            if not txn_id or not last_transition:
                continue

            # Check if this is a confirmed transition
            if last_transition not in CONFIRMED_TRANSITIONS:
                continue

            # Check if booking_start is in the future
            if booking_start_str:
                try:
                    start_str = booking_start_str
                    if isinstance(start_str, str):
                        if start_str.endswith("Z"):
                            start_str = start_str[:-1] + "+00:00"
                        start_dt = datetime.fromisoformat(start_str)
                        if start_dt.tzinfo is None:
                            start_dt = start_dt.replace(tzinfo=timezone.utc)

                        if start_dt < now:
                            # Booking has already started, skip
                            continue
                except (ValueError, TypeError):
                    # Can't parse date, skip this check
                    pass

            # Check if we've already seen this transition for this transaction
            previous_transition = seen_transitions.get(txn_id)

            if previous_transition != last_transition:
                # New confirmed booking detected!
                _LOGGER.info(
                    "Confirmed booking detected: txn_id=%s, transition=%s, "
                    "customer=%s %s, listing=%s",
                    txn_id,
                    last_transition,
                    booking.get("customer_first_name", ""),
                    booking.get("customer_last_name", ""),
                    booking.get("listing_title", ""),
                )

                # Fire event
                self.hass.bus.async_fire(
                    EVENT_BOOKING_CONFIRMED,
                    {
                        "transaction_id": txn_id,
                        "last_transition": last_transition,
                        "customer_first_name": booking.get("customer_first_name"),
                        "customer_last_name": booking.get("customer_last_name"),
                        "customer_display_name": booking.get("customer_display_name"),
                        "listing_title": booking.get("listing_title"),
                        "listing_id": booking.get("listing_id"),
                        "booking_start": booking_start_str,
                        "booking_end": booking.get("booking_end"),
                        "payout_total_aud": booking.get("payout_total_aud"),
                        "timestamp": now.isoformat(),
                    },
                )

                # Update seen transitions
                seen_transitions[txn_id] = last_transition
                changes_made = True

        # Persist changes to storage
        if changes_made:
            self._stored_data["seen_transitions"] = seen_transitions
            await self._store.async_save(self._stored_data)

    async def mark_message_sent(self, transaction_id: str) -> None:
        """Mark a transaction as having had a message sent."""
        sent_messages = self._stored_data.get("sent_messages", {})
        sent_messages[transaction_id] = datetime.now(timezone.utc).isoformat()
        self._stored_data["sent_messages"] = sent_messages
        await self._store.async_save(self._stored_data)

    def has_message_been_sent(self, transaction_id: str) -> bool:
        """Check if a message has already been sent for a transaction."""
        sent_messages = self._stored_data.get("sent_messages", {})
        return transaction_id in sent_messages
