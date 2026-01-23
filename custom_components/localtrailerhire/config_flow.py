"""Config flow for Local Trailer Hire integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthenticationError, validate_credentials
from .const import (
    CONF_CLIENT_ID,
    CONF_LAST_TRANSITIONS,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DEFAULT_LAST_TRANSITIONS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class LocalTrailerHireConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Local Trailer Hire."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._client_id: str | None = None
        self._username: str | None = None
        self._password: str | None = None
        self._refresh_token: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._client_id = user_input[CONF_CLIENT_ID]
            self._username = user_input.get(CONF_USERNAME)
            self._password = user_input.get(CONF_PASSWORD)
            self._refresh_token = user_input.get(CONF_REFRESH_TOKEN)

            # Validate that we have either username/password or refresh_token
            has_password_creds = self._username and self._password
            has_refresh_token = bool(self._refresh_token)

            if not has_password_creds and not has_refresh_token:
                errors["base"] = "missing_credentials"
            else:
                # Validate credentials
                session = async_get_clientsession(self.hass)
                try:
                    success, new_refresh_token = await validate_credentials(
                        session=session,
                        client_id=self._client_id,
                        username=self._username,
                        password=self._password,
                        refresh_token=self._refresh_token,
                    )

                    if success:
                        # Store the refresh token from successful auth
                        if new_refresh_token:
                            self._refresh_token = new_refresh_token

                        # Check for existing entry
                        await self.async_set_unique_id(self._client_id)
                        self._abort_if_unique_id_configured()

                        return await self.async_step_options()
                    else:
                        errors["base"] = "invalid_auth"

                except Exception as err:
                    _LOGGER.exception("Unexpected error during config: %s", err)
                    errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CLIENT_ID): str,
                    vol.Optional(CONF_USERNAME): str,
                    vol.Optional(CONF_PASSWORD): str,
                    vol.Optional(CONF_REFRESH_TOKEN): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "auth_note": "Enter username/password OR a refresh token"
            },
        )

    async def async_step_options(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the options step."""
        if user_input is not None:
            # Create the config entry
            data = {
                CONF_CLIENT_ID: self._client_id,
                CONF_REFRESH_TOKEN: self._refresh_token,
            }

            # Only store username/password if provided (for re-auth fallback)
            if self._username:
                data[CONF_USERNAME] = self._username
            if self._password:
                data[CONF_PASSWORD] = self._password

            # Get transitions - empty string means no filter (fetch all)
            transitions_input = user_input.get(CONF_LAST_TRANSITIONS, "").strip()

            options = {
                CONF_SCAN_INTERVAL: user_input.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                ),
                CONF_LAST_TRANSITIONS: transitions_input,
            }

            return self.async_create_entry(
                title="Local Trailer Hire",
                data=data,
                options=options,
            )

        # Default is empty = no filter, determine upcoming by dates only
        default_transitions = ",".join(DEFAULT_LAST_TRANSITIONS) if DEFAULT_LAST_TRANSITIONS else ""

        return self.async_show_form(
            step_id="options",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                    vol.Optional(
                        CONF_LAST_TRANSITIONS,
                        default=default_transitions,
                    ): str,
                }
            ),
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle reauthorization."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reauthorization confirmation."""
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)

            try:
                success, new_refresh_token = await validate_credentials(
                    session=session,
                    client_id=user_input[CONF_CLIENT_ID],
                    username=user_input.get(CONF_USERNAME),
                    password=user_input.get(CONF_PASSWORD),
                    refresh_token=user_input.get(CONF_REFRESH_TOKEN),
                )

                if success:
                    # Update the config entry
                    entry = self.hass.config_entries.async_get_entry(
                        self.context["entry_id"]
                    )
                    if entry:
                        data = dict(entry.data)
                        data[CONF_CLIENT_ID] = user_input[CONF_CLIENT_ID]
                        if new_refresh_token:
                            data[CONF_REFRESH_TOKEN] = new_refresh_token
                        if user_input.get(CONF_USERNAME):
                            data[CONF_USERNAME] = user_input[CONF_USERNAME]
                        if user_input.get(CONF_PASSWORD):
                            data[CONF_PASSWORD] = user_input[CONF_PASSWORD]

                        self.hass.config_entries.async_update_entry(entry, data=data)
                        await self.hass.config_entries.async_reload(entry.entry_id)
                        return self.async_abort(reason="reauth_successful")

                errors["base"] = "invalid_auth"

            except Exception as err:
                _LOGGER.exception("Reauth error: %s", err)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CLIENT_ID): str,
                    vol.Optional(CONF_USERNAME): str,
                    vol.Optional(CONF_PASSWORD): str,
                    vol.Optional(CONF_REFRESH_TOKEN): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> LocalTrailerHireOptionsFlow:
        """Get the options flow for this handler."""
        return LocalTrailerHireOptionsFlow(config_entry)


class LocalTrailerHireOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Local Trailer Hire."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle options flow."""
        if user_input is not None:
            # Normalize transitions - strip whitespace
            data = dict(user_input)
            if CONF_LAST_TRANSITIONS in data:
                data[CONF_LAST_TRANSITIONS] = data[CONF_LAST_TRANSITIONS].strip()
            return self.async_create_entry(title="", data=data)

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        # Default is empty string = no filter
        default_transitions = ",".join(DEFAULT_LAST_TRANSITIONS) if DEFAULT_LAST_TRANSITIONS else ""
        current_transitions = self.config_entry.options.get(
            CONF_LAST_TRANSITIONS, default_transitions
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=current_interval
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                    vol.Optional(
                        CONF_LAST_TRANSITIONS, default=current_transitions
                    ): str,
                }
            ),
        )
