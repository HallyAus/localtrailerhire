"""Setup lifecycle safeguards for Local Trailer Hire."""

from __future__ import annotations

import logging
from collections.abc import Collection
from typing import Any, Protocol

from homeassistant.exceptions import ConfigEntryError

_LOGGER = logging.getLogger(__name__)


class FirstRefreshCoordinator(Protocol):
    """Coordinator capability required during config-entry setup."""

    async def async_config_entry_first_refresh(self) -> None:
        """Fetch the first coordinator update."""


class ServiceRegistry(Protocol):
    """Service-registry capability required by lifecycle readiness checks."""

    def has_service(self, domain: str, service: str) -> bool:
        """Return whether an integration action is registered."""


class SetupEntry(Protocol):
    """Config-entry capability required by the setup transaction."""

    entry_id: str


class ConfigEntriesManager(Protocol):
    """Config-entry forwarding capabilities required by setup."""

    async def async_forward_entry_setups(
        self,
        entry: SetupEntry,
        platforms: Collection[Any],
    ) -> None:
        """Forward a config entry to one or more platforms."""

    async def async_unload_platforms(
        self,
        entry: SetupEntry,
        platforms: Collection[Any],
    ) -> bool:
        """Unload a config entry from one or more platforms."""


class SetupRuntime(Protocol):
    """Home Assistant capabilities required during config-entry setup."""

    data: dict[str, Any]
    services: ServiceRegistry
    config_entries: ConfigEntriesManager


async def _async_unload_attempted_platforms(
    hass: SetupRuntime,
    entry: SetupEntry,
    attempted_platforms: Collection[Any],
) -> None:
    """Best-effort unload every attempted platform in reverse setup order."""
    for platform in reversed(tuple(attempted_platforms)):
        try:
            unloaded = await hass.config_entries.async_unload_platforms(entry, (platform,))
        except BaseException:
            # Preserve the original setup exception while still attempting to
            # unwind every other platform and the integration runtime.
            _LOGGER.exception("Failed to unwind Local Trailer Hire platform %s", platform)
            continue

        if not unloaded:
            _LOGGER.warning("Could not fully unwind Local Trailer Hire platform %s", platform)


async def async_setup_transaction(
    hass: SetupRuntime,
    entry: SetupEntry,
    coordinator: FirstRefreshCoordinator,
    *,
    domain: str,
    registered_services: Collection[str],
    platforms: Collection[Any],
) -> None:
    """Run the initial scan and platform forwarding as one setup transaction.

    A first refresh can fire booking events synchronously. Event automations
    must therefore be able to resolve the runtime and call every integration
    action before the coordinator is allowed to scan. Any exception or task
    cancellation unwinds every platform that setup attempted, then removes the
    partial runtime. Integration-wide actions remain registered by ``async_setup``
    so Home Assistant can validate automations even when an entry fails to load.
    """
    runtimes = hass.data.get(domain, {})
    attempted_platforms: list[Any] = []

    try:
        if entry.entry_id not in runtimes:
            raise ConfigEntryError("Runtime is not ready before the initial booking scan")

        missing_services = [
            service
            for service in registered_services
            if not hass.services.has_service(domain, service)
        ]
        if missing_services:
            raise ConfigEntryError(
                "Integration actions are not ready before the initial booking scan"
            )

        await coordinator.async_config_entry_first_refresh()

        # Forward one platform at a time so a failure cannot leave sibling
        # setup tasks running while rollback starts. Include the current
        # platform before awaiting because Home Assistant may partially load it
        # before surfacing an exception.
        for platform in platforms:
            attempted_platforms.append(platform)
            await hass.config_entries.async_forward_entry_setups(entry, (platform,))
    except BaseException:
        try:
            await _async_unload_attempted_platforms(hass, entry, attempted_platforms)
        finally:
            # Platforms may need the coordinator during unload, so remove the
            # runtime only after platform rollback finishes. Services are
            # integration-wide and intentionally survive entry failures.
            runtimes.pop(entry.entry_id, None)
        raise
