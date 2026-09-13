"""Coordinator-level message archive concurrency and call-bound regressions."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


class _CoordinatorBase:
    @classmethod
    def __class_getitem__(cls, _item: Any) -> type[_CoordinatorBase]:
        return cls


def _module(name: str, **attributes: Any) -> ModuleType:
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def _load_integration(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    issue_registry = _module(
        "homeassistant.helpers.issue_registry",
        IssueSeverity=SimpleNamespace(ERROR="error"),
        async_create_issue=lambda *_args, **_kwargs: None,
        async_delete_issue=lambda *_args, **_kwargs: None,
    )
    helpers = _module("homeassistant.helpers", issue_registry=issue_registry)
    services = _module(
        "lth_pkg.services",
        REGISTERED_SERVICES=(),
        async_register_services=lambda _hass: None,
    )
    setup_lifecycle = _module(
        "lth_pkg.setup_lifecycle", async_setup_transaction=lambda *_args, **_kwargs: None
    )
    stubs = {
        "homeassistant": _module("homeassistant"),
        "homeassistant.config_entries": _module("homeassistant.config_entries", ConfigEntry=object),
        "homeassistant.const": _module(
            "homeassistant.const",
            CONF_PASSWORD="password",
            CONF_USERNAME="username",
            Platform=SimpleNamespace(
                SENSOR="sensor", BINARY_SENSOR="binary_sensor", CALENDAR="calendar"
            ),
        ),
        "homeassistant.core": _module("homeassistant.core", HomeAssistant=object),
        "homeassistant.exceptions": _module(
            "homeassistant.exceptions",
            ConfigEntryAuthFailed=type("ConfigEntryAuthFailed", (Exception,), {}),
            ConfigEntryNotReady=type("ConfigEntryNotReady", (Exception,), {}),
            HomeAssistantError=type("HomeAssistantError", (Exception,), {}),
        ),
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.issue_registry": issue_registry,
        "homeassistant.helpers.aiohttp_client": _module(
            "homeassistant.helpers.aiohttp_client",
            async_get_clientsession=lambda _hass: None,
        ),
        "homeassistant.helpers.storage": _module("homeassistant.helpers.storage", Store=object),
        "homeassistant.helpers.update_coordinator": _module(
            "homeassistant.helpers.update_coordinator",
            DataUpdateCoordinator=_CoordinatorBase,
            UpdateFailed=type("UpdateFailed", (Exception,), {}),
        ),
        "lth_pkg.services": services,
        "lth_pkg.setup_lifecycle": setup_lifecycle,
    }
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)

    component = Path(__file__).resolve().parent.parent / "custom_components" / "localtrailerhire"
    package_name = "lth_pkg.coordinator_test"
    monkeypatch.setitem(sys.modules, f"{package_name}.api", sys.modules["lth_pkg.api"])
    monkeypatch.setitem(
        sys.modules, f"{package_name}.auto_review", sys.modules["lth_pkg.auto_review"]
    )
    monkeypatch.setitem(sys.modules, f"{package_name}.const", sys.modules["lth_pkg.const"])
    monkeypatch.setitem(
        sys.modules, f"{package_name}.customer_history", sys.modules["lth_pkg.customer_history"]
    )
    monkeypatch.setitem(
        sys.modules, f"{package_name}.message_archive", sys.modules["lth_pkg.message_archive"]
    )
    monkeypatch.setitem(sys.modules, f"{package_name}.services", services)
    monkeypatch.setitem(sys.modules, f"{package_name}.setup_lifecycle", setup_lifecycle)
    monkeypatch.setitem(sys.modules, f"{package_name}.util", sys.modules["lth_pkg.util"])
    spec = importlib.util.spec_from_file_location(package_name, component / "__init__.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


class _Store:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    async def async_save(self, value: dict[str, Any]) -> None:
        self.saved.append(copy.deepcopy(value))


class _BlockingAPI:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def get_messages_incremental(
        self, *_args: Any, **_kwargs: Any
    ) -> tuple[list, bool, None]:
        self.started.set()
        await self.release.wait()
        return [{"id": "new-message", "content": "Example"}], True, None


def _coordinator(module: ModuleType, api: Any) -> Any:
    coordinator = object.__new__(module.LocalTrailerHireCoordinator)
    coordinator.api = api
    coordinator.data = [{"transaction_id": "transaction-1"}]
    coordinator.message_history = {
        "transaction-1": {
            "messages": {"old-message": {"id": "old-message", "content": "Old"}},
            "message_count": 1,
            "sync_status": "complete",
        }
    }
    coordinator._stored_data = {
        "message_history": coordinator.message_history,
        "message_sync_cursor": 0,
    }
    coordinator._store = _Store()
    coordinator._message_archive_lock = asyncio.Lock()
    coordinator.history_retention = "forever"
    coordinator.archive_messages = True
    coordinator.awaiting_reply_txns = []
    coordinator.latest_message = None
    return coordinator


@pytest.mark.asyncio
async def test_clear_waits_for_inflight_sync_and_cannot_be_undone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_integration(monkeypatch)
    api = _BlockingAPI()
    coordinator = _coordinator(module, api)

    sync_task = asyncio.create_task(coordinator.sync_message_history())
    await api.started.wait()
    clear_task = asyncio.create_task(coordinator.clear_message_history())
    await asyncio.sleep(0)
    assert clear_task.done() is False

    api.release.set()
    await sync_task
    await clear_task

    assert coordinator.message_history == {}
    assert coordinator._stored_data["message_history"] == {}
    assert coordinator._store.saved[-1]["message_history"] == {}


class _CountingAPI:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_current_user_id(self) -> str:
        return "provider"

    async def get_messages_incremental(
        self, transaction_id: str, *_args: Any, **_kwargs: Any
    ) -> tuple[list, bool, None]:
        self.calls.append(transaction_id)
        return [], True, None

    @staticmethod
    def awaiting_reply(_messages: list, _provider_id: str) -> bool:
        return False

    @staticmethod
    def latest_message(_messages: list) -> None:
        return None


@pytest.mark.asyncio
async def test_active_reply_scan_is_excluded_from_same_poll_archive_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_integration(monkeypatch)
    api = _CountingAPI()
    coordinator = _coordinator(module, api)
    bookings = [
        {"transaction_id": "active-1", "category": "upcoming"},
        {"transaction_id": "active-2", "category": "in_progress"},
        {"transaction_id": "history-1", "category": "past"},
        {"transaction_id": "history-2", "category": "past"},
    ]

    scanned = await coordinator._refresh_awaiting_replies(bookings)
    await coordinator.sync_message_history(
        5,
        bookings=bookings,
        excluded_transaction_ids=scanned,
    )

    assert scanned == {"active-1", "active-2"}
    assert api.calls == ["active-1", "active-2", "history-1", "history-2"]
    assert len(api.calls) == len(set(api.calls))
