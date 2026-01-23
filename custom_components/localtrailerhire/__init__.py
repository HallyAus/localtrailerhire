"""The Local Trailer Hire integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import APIError, AuthenticationError, SharetribeFlexAPI
from .const import (
    CONF_CLIENT_ID,
    CONF_INCLUDE_SENSITIVE,
    CONF_LAST_TRANSITIONS,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DEFAULT_INCLUDE_SENSITIVE,
    DEFAULT_LAST_TRANSITIONS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Local Trailer Hire from a config entry."""
    hass.data.setdefault(DOMAIN, {})

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
    )

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "api": api,
    }

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

            _LOGGER.debug("Fetched %d upcoming bookings", len(bookings))
            return bookings

        except AuthenticationError as err:
            # Trigger reauth flow
            raise ConfigEntryAuthFailed("Authentication failed") from err

        except APIError as err:
            raise UpdateFailed(f"API error: {err}") from err

        except Exception as err:
            _LOGGER.exception("Unexpected error fetching data")
            raise UpdateFailed(f"Unexpected error: {err}") from err
