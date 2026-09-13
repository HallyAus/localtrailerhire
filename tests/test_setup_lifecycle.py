"""Exercise config-entry startup ordering and transactional cleanup."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

COMPONENT = Path(__file__).resolve().parent.parent / "custom_components" / "localtrailerhire"
DOMAIN = "localtrailerhire"
ENTRY_ID = "entry-under-test"
SERVICES = ("send_message", "leave_review", "refresh_now")
PLATFORMS = ("sensor", "binary_sensor", "calendar")


class FakeConfigEntryError(Exception):
    """Fatal config-entry setup failure."""


class FakeConfigEntryNotReady(Exception):
    """Retryable config-entry setup failure."""


class FakeConfigEntryAuthFailed(Exception):
    """Config-entry authentication failure."""


def _load_lifecycle_module() -> ModuleType:
    """Load the lifecycle helper against lightweight HA exception stubs."""
    homeassistant = ModuleType("homeassistant")
    exceptions = ModuleType("homeassistant.exceptions")
    exceptions.ConfigEntryError = FakeConfigEntryError
    exceptions.ConfigEntryNotReady = FakeConfigEntryNotReady
    exceptions.ConfigEntryAuthFailed = FakeConfigEntryAuthFailed

    name = "lth_setup_lifecycle_test"
    spec = importlib.util.spec_from_file_location(name, COMPONENT / "setup_lifecycle.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    original_homeassistant = sys.modules.get("homeassistant")
    original_exceptions = sys.modules.get("homeassistant.exceptions")
    try:
        sys.modules["homeassistant"] = homeassistant
        sys.modules["homeassistant.exceptions"] = exceptions
        sys.modules[name] = module
        spec.loader.exec_module(module)
    finally:
        if original_homeassistant is None:
            sys.modules.pop("homeassistant", None)
        else:
            sys.modules["homeassistant"] = original_homeassistant
        if original_exceptions is None:
            sys.modules.pop("homeassistant.exceptions", None)
        else:
            sys.modules["homeassistant.exceptions"] = original_exceptions

    return module


LIFECYCLE = _load_lifecycle_module()


@dataclass
class FakeEntry:
    """Minimal config entry used by setup tests."""

    entry_id: str = ENTRY_ID


class FakeServices:
    """Minimal Home Assistant service registry used by lifecycle tests."""

    def __init__(self, registered: set[tuple[str, str]]) -> None:
        self.registered = registered
        self.removed: list[tuple[str, str]] = []

    def has_service(self, domain: str, service: str) -> bool:
        return (domain, service) in self.registered

    def async_remove(self, domain: str, service: str) -> None:
        self.registered.discard((domain, service))
        self.removed.append((domain, service))


class FakeConfigEntries:
    """Model HA's per-platform forwarding and unloading semantics."""

    def __init__(
        self,
        *,
        forward_errors: dict[str, BaseException] | None = None,
        partially_loaded: set[str] | None = None,
        unload_errors: dict[str, BaseException] | None = None,
        unload_results: dict[str, bool] | None = None,
        block_forward: str | None = None,
    ) -> None:
        self.forward_errors = forward_errors or {}
        self.partially_loaded = partially_loaded or set()
        self.unload_errors = unload_errors or {}
        self.unload_results = unload_results or {}
        self.block_forward = block_forward
        self.forward_started = asyncio.Event()
        self.forward_calls: list[tuple[str, ...]] = []
        self.unload_calls: list[tuple[str, ...]] = []
        self.loaded: set[str] = set()
        self.on_forward: Callable[[str], None] = lambda _platform: None
        self.on_unload: Callable[[str], None] = lambda _platform: None

    async def async_forward_entry_setups(
        self,
        _entry: FakeEntry,
        platforms: tuple[str, ...],
    ) -> None:
        assert len(platforms) == 1, "transactional setup forwards one platform at a time"
        platform = platforms[0]
        self.forward_calls.append(platforms)
        self.on_forward(platform)

        if platform in self.partially_loaded:
            self.loaded.add(platform)
        if platform == self.block_forward:
            self.forward_started.set()
            await asyncio.Future()
        if error := self.forward_errors.get(platform):
            raise error
        self.loaded.add(platform)

    async def async_unload_platforms(
        self,
        _entry: FakeEntry,
        platforms: tuple[str, ...],
    ) -> bool:
        assert len(platforms) == 1, "rollback unloads every platform independently"
        platform = platforms[0]
        self.unload_calls.append(platforms)
        self.on_unload(platform)

        if error := self.unload_errors.get(platform):
            raise error
        if not self.unload_results.get(platform, True):
            return False
        self.loaded.discard(platform)
        return True


class FakeHass:
    """Minimal Home Assistant runtime used by lifecycle tests."""

    def __init__(
        self,
        runtimes: dict[str, Any],
        services: FakeServices,
        config_entries: FakeConfigEntries | None = None,
    ) -> None:
        self.data = {DOMAIN: runtimes}
        self.services = services
        self.config_entries = config_entries or FakeConfigEntries()


class FakeCoordinator:
    """Coordinator that observes readiness or raises a setup exception."""

    def __init__(
        self,
        on_refresh: Callable[[], None],
        error: BaseException | None = None,
    ) -> None:
        self.on_refresh = on_refresh
        self.error = error
        self.calls = 0

    async def async_config_entry_first_refresh(self) -> None:
        self.calls += 1
        self.on_refresh()
        if self.error is not None:
            raise self.error


class BlockingCoordinator(FakeCoordinator):
    """Coordinator used to exercise real task cancellation."""

    def __init__(self) -> None:
        super().__init__(lambda: None)
        self.refresh_started = asyncio.Event()

    async def async_config_entry_first_refresh(self) -> None:
        self.calls += 1
        self.refresh_started.set()
        await asyncio.Future()


def _all_services() -> set[tuple[str, str]]:
    return {(DOMAIN, service) for service in SERVICES}


async def _run_transaction(
    hass: FakeHass,
    coordinator: FakeCoordinator,
    entry: FakeEntry | None = None,
) -> None:
    await LIFECYCLE.async_setup_transaction(
        hass,
        entry or FakeEntry(),
        coordinator,
        domain=DOMAIN,
        registered_services=SERVICES,
        platforms=PLATFORMS,
    )


@pytest.mark.asyncio
async def test_success_observes_runtime_and_services_then_forwards_each_platform() -> None:
    """The first scan and every platform see a complete runtime."""
    services = FakeServices(_all_services())
    config_entries = FakeConfigEntries()
    hass = FakeHass({ENTRY_ID: {"coordinator": object()}}, services, config_entries)

    def assert_ready() -> None:
        assert ENTRY_ID in hass.data[DOMAIN]
        assert all(services.has_service(DOMAIN, service) for service in SERVICES)

    config_entries.on_forward = lambda _platform: assert_ready()
    coordinator = FakeCoordinator(assert_ready)

    await _run_transaction(hass, coordinator)

    assert coordinator.calls == 1
    assert config_entries.forward_calls == [(platform,) for platform in PLATFORMS]
    assert config_entries.unload_calls == []
    assert config_entries.loaded == set(PLATFORMS)
    assert services.removed == []
    assert ENTRY_ID in hass.data[DOMAIN]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_type",
    (
        FakeConfigEntryError,
        FakeConfigEntryNotReady,
        FakeConfigEntryAuthFailed,
        RuntimeError,
        asyncio.CancelledError,
    ),
)
async def test_first_refresh_failure_or_cancellation_cleans_partial_setup(
    error_type: type[BaseException],
) -> None:
    """Every first-refresh exit leaves the final entry retryable."""
    services = FakeServices(_all_services())
    hass = FakeHass({ENTRY_ID: {"coordinator": object()}}, services)
    error = error_type("setup failed")
    coordinator = FakeCoordinator(lambda: None, error)

    with pytest.raises(error_type) as raised:
        await _run_transaction(hass, coordinator)

    assert raised.value is error
    assert coordinator.calls == 1
    assert hass.config_entries.forward_calls == []
    assert hass.config_entries.unload_calls == []
    assert hass.data[DOMAIN] == {}
    assert services.registered == _all_services()
    assert services.removed == []


@pytest.mark.asyncio
async def test_external_task_cancellation_during_first_refresh_still_cleans_up() -> None:
    """A real Task.cancel request cannot strand setup state."""
    services = FakeServices(_all_services())
    hass = FakeHass({ENTRY_ID: {"coordinator": object()}}, services)
    coordinator = BlockingCoordinator()

    setup_task = asyncio.create_task(_run_transaction(hass, coordinator))
    await coordinator.refresh_started.wait()
    setup_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await setup_task

    assert coordinator.calls == 1
    assert hass.config_entries.forward_calls == []
    assert hass.data[DOMAIN] == {}
    assert services.registered == _all_services()


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", (RuntimeError, asyncio.CancelledError))
async def test_first_refresh_exit_preserves_healthy_entry_and_shared_services(
    error_type: type[BaseException],
) -> None:
    """A failed second account cannot remove a healthy account's actions."""
    healthy_entry = "healthy-entry"
    healthy_runtime = {"coordinator": object()}
    services = FakeServices(_all_services())
    hass = FakeHass(
        {
            healthy_entry: healthy_runtime,
            ENTRY_ID: {"coordinator": object()},
        },
        services,
    )

    with pytest.raises(error_type):
        await _run_transaction(
            hass,
            FakeCoordinator(lambda: None, error_type("setup failed")),
        )

    assert hass.data[DOMAIN] == {healthy_entry: healthy_runtime}
    assert services.registered == _all_services()
    assert services.removed == []


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ("runtime", "service"))
async def test_readiness_guard_cleans_up_without_starting_scan(missing: str) -> None:
    """A partial setup is rejected before it can emit a booking event."""
    registered = _all_services()
    runtimes: dict[str, Any] = {ENTRY_ID: {"coordinator": object()}}
    if missing == "runtime":
        runtimes.clear()
    else:
        registered.remove((DOMAIN, SERVICES[-1]))

    services = FakeServices(registered)
    hass = FakeHass(runtimes, services)
    coordinator = FakeCoordinator(lambda: None)

    with pytest.raises(FakeConfigEntryError):
        await _run_transaction(hass, coordinator)

    assert coordinator.calls == 0
    assert hass.config_entries.forward_calls == []
    assert hass.data[DOMAIN] == {}
    expected_services = _all_services()
    if missing == "service":
        expected_services.remove((DOMAIN, SERVICES[-1]))
    assert services.registered == expected_services


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", (RuntimeError, asyncio.CancelledError))
async def test_partial_platform_forward_is_unloaded_before_runtime_cleanup(
    error_type: type[BaseException],
) -> None:
    """Success plus a partially loaded failing platform unwind in reverse order."""
    error = error_type("forward failed")
    config_entries = FakeConfigEntries(
        forward_errors={"binary_sensor": error},
        partially_loaded={"binary_sensor"},
    )
    services = FakeServices(_all_services())
    hass = FakeHass({ENTRY_ID: {"coordinator": object()}}, services, config_entries)
    config_entries.on_unload = lambda _platform: (
        pytest.fail("runtime removed before platform unload")
        if ENTRY_ID not in hass.data[DOMAIN]
        else None
    )

    with pytest.raises(error_type) as raised:
        await _run_transaction(hass, FakeCoordinator(lambda: None))

    assert raised.value is error
    assert config_entries.forward_calls == [("sensor",), ("binary_sensor",)]
    assert config_entries.unload_calls == [("binary_sensor",), ("sensor",)]
    assert config_entries.loaded == set()
    assert hass.data[DOMAIN] == {}
    assert services.registered == _all_services()


@pytest.mark.asyncio
async def test_external_cancellation_during_partial_forward_unloads_platforms() -> None:
    """A real cancellation waits for reverse-order platform rollback."""
    config_entries = FakeConfigEntries(
        partially_loaded={"binary_sensor"},
        block_forward="binary_sensor",
    )
    services = FakeServices(_all_services())
    hass = FakeHass({ENTRY_ID: {"coordinator": object()}}, services, config_entries)

    setup_task = asyncio.create_task(_run_transaction(hass, FakeCoordinator(lambda: None)))
    await config_entries.forward_started.wait()
    setup_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await setup_task

    assert config_entries.forward_calls == [("sensor",), ("binary_sensor",)]
    assert config_entries.unload_calls == [("binary_sensor",), ("sensor",)]
    assert config_entries.loaded == set()
    assert hass.data[DOMAIN] == {}
    assert services.registered == _all_services()


@pytest.mark.asyncio
async def test_forward_failure_preserves_healthy_entry_and_shared_services() -> None:
    """Rollback of a second account cannot disrupt an already healthy one."""
    healthy_entry = "healthy-entry"
    healthy_runtime = {"coordinator": object()}
    error = RuntimeError("forward failed")
    config_entries = FakeConfigEntries(forward_errors={"calendar": error})
    services = FakeServices(_all_services())
    hass = FakeHass(
        {
            healthy_entry: healthy_runtime,
            ENTRY_ID: {"coordinator": object()},
        },
        services,
        config_entries,
    )

    with pytest.raises(RuntimeError) as raised:
        await _run_transaction(hass, FakeCoordinator(lambda: None))

    assert raised.value is error
    assert config_entries.unload_calls == [
        ("calendar",),
        ("binary_sensor",),
        ("sensor",),
    ]
    assert config_entries.loaded == set()
    assert hass.data[DOMAIN] == {healthy_entry: healthy_runtime}
    assert services.registered == _all_services()
    assert services.removed == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_mode", ("exception", "false_result"))
async def test_one_unload_failure_does_not_block_remaining_rollback(
    caplog: pytest.LogCaptureFixture,
    failure_mode: str,
) -> None:
    """A broken platform unload cannot strand other platforms or runtime state."""
    forward_error = RuntimeError("forward failed")
    unload_error = RuntimeError("unload failed")
    config_entries = FakeConfigEntries(
        forward_errors={"calendar": forward_error},
        partially_loaded={"calendar"},
        unload_errors={"binary_sensor": unload_error} if failure_mode == "exception" else None,
        unload_results={"binary_sensor": False} if failure_mode == "false_result" else None,
    )
    services = FakeServices(_all_services())
    hass = FakeHass({ENTRY_ID: {"coordinator": object()}}, services, config_entries)

    with pytest.raises(RuntimeError) as raised:
        await _run_transaction(hass, FakeCoordinator(lambda: None))

    assert raised.value is forward_error
    assert config_entries.unload_calls == [
        ("calendar",),
        ("binary_sensor",),
        ("sensor",),
    ]
    assert config_entries.loaded == {"binary_sensor"}
    assert hass.data[DOMAIN] == {}
    assert services.registered == _all_services()
    expected_log = (
        "Failed to unwind Local Trailer Hire platform binary_sensor"
        if failure_mode == "exception"
        else "Could not fully unwind Local Trailer Hire platform binary_sensor"
    )
    assert expected_log in caplog.text
