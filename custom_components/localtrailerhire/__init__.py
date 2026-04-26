"""The Local Trailer Hire integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import APIError, AuthenticationError, SharetribeFlexAPI
from .util import parse_iso_datetime
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
    SERVICE_FIRE_CONFIRMED_EVENTS,
    SERVICE_MARK_MESSAGE_SENT,
    SERVICE_REFRESH_NOW,
    SERVICE_SEND_MESSAGE,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


class LocalTrailerHireStore(Store):
    """Persistent store with schema migration.

    v1 stored ``seen_transitions`` (a flat ``txn_id -> last_transition`` map)
    alongside ``sent_messages``. v2 collapses those into a single
    ``transaction_states`` map keyed by transaction id.
    """

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        if old_major_version < 2:
            seen = old_data.pop("seen_transitions", {}) or {}
            sent = old_data.get("sent_messages", {}) or {}
            transaction_states = old_data.setdefault("transaction_states", {})
            for txn_id, last_transition in seen.items():
                transaction_states.setdefault(
                    txn_id,
                    {
                        "last_transition": last_transition,
                        "last_transitioned_at": None,
                        "message_sent": txn_id in sent,
                        "message_sent_at": sent.get(txn_id),
                        "event_fired_at": None,
                    },
                )
            _LOGGER.info(
                "Migrated %d transactions from storage v1 to v2", len(seen)
            )
        return old_data

# Service schemas
SERVICE_SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required("transaction_id"): cv.string,
        vol.Required("message"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)

SERVICE_MARK_MESSAGE_SENT_SCHEMA = vol.Schema(
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

SERVICE_REFRESH_NOW_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
    }
)


def _get_entry_data(
    hass: HomeAssistant, config_entry_id: str | None
) -> dict[str, Any]:
    """Resolve the integration data dict for a given (or sole) config entry.

    If ``config_entry_id`` is provided, it must match a configured entry.
    Otherwise, exactly one entry must be configured.
    """
    entries = hass.data.get(DOMAIN, {})
    valid = {
        eid: data
        for eid, data in entries.items()
        if isinstance(data, dict) and "api" in data
    }

    if not valid:
        raise HomeAssistantError("No Local Trailer Hire integration configured")

    if config_entry_id:
        if config_entry_id not in valid:
            raise HomeAssistantError(
                f"config_entry_id {config_entry_id} not found"
            )
        return valid[config_entry_id]

    if len(valid) > 1:
        raise HomeAssistantError(
            "Multiple Local Trailer Hire entries configured; "
            "specify config_entry_id"
        )

    return next(iter(valid.values()))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Local Trailer Hire from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Initialize storage for tracking sent messages and transaction states.
    # ``LocalTrailerHireStore`` handles version migration on load.
    store = LocalTrailerHireStore(hass, STORAGE_VERSION, STORAGE_KEY)
    stored_data = await store.async_load() or {}
    stored_data.setdefault("sent_messages", {})
    stored_data.setdefault("transaction_states", {})

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

    # Define service handlers
    async def async_send_message(call: ServiceCall) -> None:
        """Handle send_message service call."""
        transaction_id = call.data.get("transaction_id", "")
        message = call.data.get("message", "")

        _LOGGER.debug(
            "SERVICE CALL: localtrailerhire.send_message - "
            "transaction_id=%s, message_length=%d",
            transaction_id[:8] + "..." if transaction_id else "EMPTY",
            len(message) if message else 0,
        )

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

        entry_data = _get_entry_data(hass, call.data.get("config_entry_id"))
        api_client = entry_data["api"]
        coord = entry_data.get("coordinator")

        try:
            await api_client.send_message(transaction_id, message)

            # Mark message as sent in storage (idempotent protection)
            if coord:
                await coord.mark_message_sent(transaction_id)

            # Fire event for successful message send
            hass.bus.async_fire(
                EVENT_MESSAGE_SENT,
                {
                    "transaction_id": transaction_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

            _LOGGER.debug(
                "send_message succeeded for transaction %s", transaction_id
            )

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

    async def async_refresh_now(call: ServiceCall) -> None:
        """Force an immediate coordinator refresh.

        If ``config_entry_id`` is omitted, refreshes all configured entries.
        """
        entry_id = call.data.get("config_entry_id")
        if entry_id:
            entry_data = _get_entry_data(hass, entry_id)
            await entry_data["coordinator"].async_request_refresh()
            return

        refreshed = False
        for entry_data in hass.data.get(DOMAIN, {}).values():
            if isinstance(entry_data, dict) and "coordinator" in entry_data:
                await entry_data["coordinator"].async_request_refresh()
                refreshed = True
        if not refreshed:
            raise HomeAssistantError("No Local Trailer Hire integration configured")

    async def async_mark_message_sent(call: ServiceCall) -> None:
        """Manually mark a transaction as having had a message sent."""
        transaction_id = call.data.get("transaction_id", "").strip()

        if len(transaction_id) != 36 or transaction_id.count("-") != 4:
            raise HomeAssistantError(
                "transaction_id must be a valid UUID format"
            )

        entry_data = _get_entry_data(hass, call.data.get("config_entry_id"))
        coord = entry_data.get("coordinator")
        if not coord:
            raise HomeAssistantError("No coordinator available")
        await coord.mark_message_sent(transaction_id)
        _LOGGER.debug("Marked message_sent=true for transaction %s", transaction_id)

    async def async_fire_confirmed_events(call: ServiceCall) -> None:
        """Re-scan and fire confirmed events for bookings in the last N hours."""
        hours_back = call.data.get("hours_back", 24)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

        entry_data = _get_entry_data(hass, call.data.get("config_entry_id"))
        coord = entry_data.get("coordinator")
        if not coord:
            raise HomeAssistantError("No coordinator available")
        await coord.fire_confirmed_events_since(cutoff, dry_run=False)

    # Register services (each independently to handle upgrades)
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_MESSAGE,
            async_send_message,
            schema=SERVICE_SEND_MESSAGE_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH_NOW):
        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH_NOW,
            async_refresh_now,
            schema=SERVICE_REFRESH_NOW_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_MARK_MESSAGE_SENT):
        hass.services.async_register(
            DOMAIN,
            SERVICE_MARK_MESSAGE_SENT,
            async_mark_message_sent,
            schema=SERVICE_MARK_MESSAGE_SENT_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_FIRE_CONFIRMED_EVENTS):
        hass.services.async_register(
            DOMAIN,
            SERVICE_FIRE_CONFIRMED_EVENTS,
            async_fire_confirmed_events,
            schema=SERVICE_FIRE_CONFIRMED_EVENTS_SCHEMA,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)

        # Remove services when the last entry is unloaded
        if not hass.data.get(DOMAIN):
            for service in (
                SERVICE_SEND_MESSAGE,
                SERVICE_REFRESH_NOW,
                SERVICE_MARK_MESSAGE_SENT,
                SERVICE_FIRE_CONFIRMED_EVENTS,
            ):
                if hass.services.has_service(DOMAIN, service):
                    hass.services.async_remove(DOMAIN, service)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


class LocalTrailerHireCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Coordinator for Local Trailer Hire data.

    Transaction State Store structure (per transaction_id):
    {
        "last_transition": str,
        "last_transitioned_at": str (ISO timestamp),
        "message_sent": bool,
        "message_sent_at": str (ISO timestamp) or None,
        "event_fired_at": str (ISO timestamp) or None,
    }
    """

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

        # Ensure expected keys exist (storage migration handles legacy data)
        self._stored_data.setdefault("transaction_states", {})
        self._stored_data.setdefault("sent_messages", {})

        # Diagnostics for debugging
        self.last_fetch_utc: str | None = None
        self.last_success_utc: str | None = None
        self.total_fetched: int = 0
        self.pages_fetched: int = 0
        self.newest_transaction_id: str | None = None
        self.confirmed_new_count: int = 0

    async def _async_update_data(self) -> list[dict[str, Any]]:
        """Fetch data from API with detailed debug logging."""
        now = datetime.now(timezone.utc)
        self.last_fetch_utc = now.isoformat()

        try:
            bookings = await self.api.get_transactions(
                last_transitions=self.last_transitions,
                include_sensitive=self.include_sensitive,
            )

            # Update diagnostics
            self.last_success_utc = now.isoformat()
            self.total_fetched = len(bookings)
            diagnostics = self.api.diagnostics
            self.pages_fetched = len(diagnostics.get("pages", []))

            # Update refresh token if it changed
            if (
                self.api.refresh_token
                and self.api.refresh_token != self.entry.data.get(CONF_REFRESH_TOKEN)
            ):
                new_data = dict(self.entry.data)
                new_data[CONF_REFRESH_TOKEN] = self.api.refresh_token
                self.hass.config_entries.async_update_entry(self.entry, data=new_data)

            # Detect newly confirmed bookings and fire events
            confirmed_count = await self._detect_confirmed_bookings(bookings)
            self.confirmed_new_count = confirmed_count

            # Find newest transaction by last_transitioned_at
            newest_txn = self._find_newest_transaction(bookings)
            if newest_txn:
                self.newest_transaction_id = newest_txn.get("transaction_id")

            # Debug logging: summary of refresh
            upcoming_count = sum(1 for b in bookings if b.get("category") == CATEGORY_UPCOMING)
            _LOGGER.debug(
                "Refresh ok: fetched=%d pages=%d newest_last_transitioned_at=%s confirmed_new=%d",
                self.total_fetched,
                self.pages_fetched,
                newest_txn.get("last_transitioned_at") if newest_txn else "none",
                confirmed_count,
            )

            # Debug logging: newest 5 transactions
            self._log_newest_transactions(bookings, count=5)

            return bookings

        except AuthenticationError as err:
            # Trigger reauth flow
            raise ConfigEntryAuthFailed("Authentication failed") from err

        except APIError as err:
            raise UpdateFailed(f"API error: {err}") from err

        except Exception as err:
            _LOGGER.exception("Unexpected error fetching data")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    def _find_newest_transaction(
        self, bookings: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Find the transaction with the most recent last_transitioned_at."""
        newest = None
        newest_dt = None

        for booking in bookings:
            dt = parse_iso_datetime(booking.get("last_transitioned_at"))
            if dt is None:
                continue
            if newest_dt is None or dt > newest_dt:
                newest_dt = dt
                newest = booking

        return newest

    def _log_newest_transactions(
        self, bookings: list[dict[str, Any]], count: int = 5
    ) -> None:
        """Log the N newest transactions by last_transitioned_at for debugging."""
        # Sort by last_transitioned_at descending
        sorted_bookings = sorted(
            [b for b in bookings if b.get("last_transitioned_at")],
            key=lambda x: x.get("last_transitioned_at", ""),
            reverse=True,
        )

        for i, booking in enumerate(sorted_bookings[:count]):
            _LOGGER.debug(
                "Newest[%d]: txn=%s transition=%s transitioned_at=%s listing=%s",
                i,
                booking.get("transaction_id", "?")[:8],  # First 8 chars of UUID
                booking.get("last_transition", "?"),
                booking.get("last_transitioned_at", "?"),
                booking.get("listing_title", "?")[:30],  # Truncate listing title
            )

    async def _detect_confirmed_bookings(
        self, bookings: list[dict[str, Any]]
    ) -> int:
        """Detect newly confirmed bookings and fire events.

        A booking is considered "newly confirmed" when:
        1. Its last_transition is in CONFIRMED_TRANSITIONS (is_confirmed)
        2. AND one of the following:
           a. We haven't seen this transaction before (previously is None)
           b. The last_transitioned_at timestamp changed
           c. The previous last_transition was NOT in CONFIRMED_TRANSITIONS
        3. AND message_sent is False (to prevent duplicate events if message already sent)

        Returns the count of new confirmations detected.
        """
        now = datetime.now(timezone.utc)
        transaction_states = self._stored_data.get("transaction_states", {})
        changes_made = False
        confirmed_count = 0

        for booking in bookings:
            txn_id = booking.get("transaction_id")
            last_transition = booking.get("last_transition")
            last_transitioned_at = booking.get("last_transitioned_at")

            if not txn_id or not last_transition:
                continue

            # Check if this is a confirmed transition
            is_confirmed = last_transition in CONFIRMED_TRANSITIONS

            if not is_confirmed:
                # Still update state tracking even for non-confirmed transitions
                # so we can detect when a non-confirmed -> confirmed transition happens
                if txn_id not in transaction_states:
                    transaction_states[txn_id] = {
                        "last_transition": last_transition,
                        "last_transitioned_at": last_transitioned_at,
                        "message_sent": False,
                        "message_sent_at": None,
                        "event_fired_at": None,
                    }
                    changes_made = True
                elif transaction_states[txn_id].get("last_transitioned_at") != last_transitioned_at:
                    transaction_states[txn_id]["last_transition"] = last_transition
                    transaction_states[txn_id]["last_transitioned_at"] = last_transitioned_at
                    changes_made = True
                continue

            # This is a confirmed transition - check if it's newly confirmed
            previously = transaction_states.get(txn_id)

            is_new_confirmation = False
            reason = ""

            if previously is None:
                # Never seen this transaction
                is_new_confirmation = True
                reason = "new_transaction"
            elif previously.get("last_transitioned_at") != last_transitioned_at:
                # Timestamp changed - this could be a re-confirmation or modification
                is_new_confirmation = True
                reason = f"timestamp_changed (old={previously.get('last_transitioned_at')})"
            elif previously.get("last_transition") not in CONFIRMED_TRANSITIONS:
                # Transition changed from non-confirmed to confirmed
                is_new_confirmation = True
                reason = f"transition_changed (old={previously.get('last_transition')})"

            # Check if message was already sent for this transaction
            # (idempotent protection - don't fire event again if message sent)
            if is_new_confirmation and previously and previously.get("message_sent"):
                _LOGGER.debug(
                    "Skipping event for txn=%s: message already sent at %s",
                    txn_id,
                    previously.get("message_sent_at"),
                )
                # Still update the state
                transaction_states[txn_id] = {
                    "last_transition": last_transition,
                    "last_transitioned_at": last_transitioned_at,
                    "message_sent": True,
                    "message_sent_at": previously.get("message_sent_at"),
                    "event_fired_at": previously.get("event_fired_at"),
                }
                changes_made = True
                continue

            if is_new_confirmation:
                confirmed_count += 1

                _LOGGER.info(
                    "Booking confirmed: txn=%s transition=%s customer=%s listing=%s",
                    txn_id,
                    last_transition,
                    booking.get("customer_display_name") or booking.get("customer_first_name", ""),
                    booking.get("listing_title", ""),
                )
                _LOGGER.debug(
                    "Confirmation reason=%s, transitioned_at=%s",
                    reason,
                    last_transitioned_at,
                )

                # Fire event
                event_data = {
                    "transaction_id": txn_id,
                    "last_transition": last_transition,
                    "last_transitioned_at": last_transitioned_at,
                    "customer_first_name": booking.get("customer_first_name"),
                    "customer_display_name": booking.get("customer_display_name"),
                    "listing_title": booking.get("listing_title"),
                    "listing_id": booking.get("listing_id"),
                    "booking_start": booking.get("booking_start"),
                    "booking_end": booking.get("booking_end"),
                    "payout_total_aud": booking.get("payout_total_aud"),
                    "timestamp": now.isoformat(),
                }
                self.hass.bus.async_fire(EVENT_BOOKING_CONFIRMED, event_data)

                # Update state
                transaction_states[txn_id] = {
                    "last_transition": last_transition,
                    "last_transitioned_at": last_transitioned_at,
                    "message_sent": False,
                    "message_sent_at": None,
                    "event_fired_at": now.isoformat(),
                }
                changes_made = True
            else:
                # Not a new confirmation, but update state if needed
                if txn_id not in transaction_states:
                    transaction_states[txn_id] = {
                        "last_transition": last_transition,
                        "last_transitioned_at": last_transitioned_at,
                        "message_sent": False,
                        "message_sent_at": None,
                        "event_fired_at": None,
                    }
                    changes_made = True

        # Persist changes to storage
        if changes_made:
            self._stored_data["transaction_states"] = transaction_states
            await self._store.async_save(self._stored_data)

        return confirmed_count

    async def fire_confirmed_events_since(
        self,
        cutoff: datetime,
        dry_run: bool = False,
    ) -> int:
        """Re-fire confirmed events for bookings transitioned since cutoff.

        This is a debugging tool to re-trigger events without sending messages.

        Args:
            cutoff: Only fire events for transactions transitioned after this time.
            dry_run: If True, just log what would be fired without actually firing.

        Returns:
            Number of events fired (or would be fired if dry_run).
        """
        if not self.data:
            _LOGGER.warning("No data available to fire events")
            return 0

        now = datetime.now(timezone.utc)
        fired_count = 0

        for booking in self.data:
            last_transition = booking.get("last_transition")
            last_transitioned_at = booking.get("last_transitioned_at")
            txn_id = booking.get("transaction_id")

            if not last_transition or last_transition not in CONFIRMED_TRANSITIONS:
                continue

            transitioned_dt = parse_iso_datetime(last_transitioned_at)
            if transitioned_dt is None:
                continue

            if transitioned_dt < cutoff:
                continue

            fired_count += 1

            if dry_run:
                _LOGGER.info(
                    "[DRY RUN] Would fire event for txn=%s, transition=%s, at=%s",
                    txn_id,
                    last_transition,
                    last_transitioned_at,
                )
            else:
                _LOGGER.info(
                    "REPLAY EVENT FIRED: %s - txn=%s, transition=%s, at=%s",
                    EVENT_BOOKING_CONFIRMED,
                    txn_id,
                    last_transition,
                    last_transitioned_at,
                )
                event_data = {
                    "transaction_id": txn_id,
                    "last_transition": last_transition,
                    "last_transitioned_at": last_transitioned_at,
                    "customer_first_name": booking.get("customer_first_name"),
                    "customer_display_name": booking.get("customer_display_name"),
                    "listing_title": booking.get("listing_title"),
                    "listing_id": booking.get("listing_id"),
                    "booking_start": booking.get("booking_start"),
                    "booking_end": booking.get("booking_end"),
                    "payout_total_aud": booking.get("payout_total_aud"),
                    "timestamp": now.isoformat(),
                    "is_replay": True,
                }
                self.hass.bus.async_fire(EVENT_BOOKING_CONFIRMED, event_data)

        _LOGGER.info(
            "fire_confirmed_events_since: cutoff=%s, fired=%d, dry_run=%s",
            cutoff.isoformat(),
            fired_count,
            dry_run,
        )
        return fired_count

    async def mark_message_sent(self, transaction_id: str) -> None:
        """Mark a transaction as having had a message sent."""
        transaction_states = self._stored_data.get("transaction_states", {})
        now_iso = datetime.now(timezone.utc).isoformat()

        if transaction_id in transaction_states:
            transaction_states[transaction_id]["message_sent"] = True
            transaction_states[transaction_id]["message_sent_at"] = now_iso
        else:
            # Create new entry
            transaction_states[transaction_id] = {
                "last_transition": None,
                "last_transitioned_at": None,
                "message_sent": True,
                "message_sent_at": now_iso,
                "event_fired_at": None,
            }

        self._stored_data["transaction_states"] = transaction_states
        await self._store.async_save(self._stored_data)
        _LOGGER.debug("Marked message_sent=True for transaction %s", transaction_id)

    def has_message_been_sent(self, transaction_id: str) -> bool:
        """Check if a message has already been sent for a transaction."""
        transaction_states = self._stored_data.get("transaction_states", {})
        state = transaction_states.get(transaction_id)
        if state:
            return state.get("message_sent", False)
        return False

    def get_diagnostics(self) -> dict[str, Any]:
        """Get diagnostic information for debugging."""
        return {
            "last_fetch_utc": self.last_fetch_utc,
            "last_success_utc": self.last_success_utc,
            "total_fetched": self.total_fetched,
            "pages_fetched": self.pages_fetched,
            "newest_transaction_id": self.newest_transaction_id,
            "confirmed_new_count": self.confirmed_new_count,
            "transaction_states_count": len(
                self._stored_data.get("transaction_states", {})
            ),
            "update_interval_seconds": self.update_interval.total_seconds()
            if self.update_interval
            else None,
        }
