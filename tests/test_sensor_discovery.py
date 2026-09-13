"""Regression tests for dynamic per-listing sensor discovery."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


class _CoordinatorEntity:
    @classmethod
    def __class_getitem__(cls, _item: Any) -> type[_CoordinatorEntity]:
        return cls

    def __init__(self, coordinator: Any) -> None:
        self.coordinator = coordinator


class _SensorEntity:
    pass


class _DeviceInfo(dict):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)


def _module(name: str, **attributes: Any) -> ModuleType:
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def _load_sensor_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    enum = SimpleNamespace
    stubs = {
        "homeassistant": _module("homeassistant"),
        "homeassistant.components": _module("homeassistant.components"),
        "homeassistant.components.sensor": _module(
            "homeassistant.components.sensor",
            SensorDeviceClass=enum(MONETARY="monetary", TIMESTAMP="timestamp"),
            SensorEntity=_SensorEntity,
            SensorStateClass=enum(MEASUREMENT="measurement", TOTAL="total"),
        ),
        "homeassistant.config_entries": _module("homeassistant.config_entries", ConfigEntry=object),
        "homeassistant.const": _module(
            "homeassistant.const",
            CURRENCY_DOLLAR="AUD",
            PERCENTAGE="%",
            EntityCategory=enum(DIAGNOSTIC="diagnostic"),
        ),
        "homeassistant.core": _module(
            "homeassistant.core", HomeAssistant=object, callback=lambda func: func
        ),
        "homeassistant.helpers": _module("homeassistant.helpers"),
        "homeassistant.helpers.device_registry": _module(
            "homeassistant.helpers.device_registry",
            DeviceEntryType=enum(SERVICE="service"),
            DeviceInfo=_DeviceInfo,
        ),
        "homeassistant.helpers.entity_platform": _module(
            "homeassistant.helpers.entity_platform", AddEntitiesCallback=object
        ),
        "homeassistant.helpers.update_coordinator": _module(
            "homeassistant.helpers.update_coordinator",
            CoordinatorEntity=_CoordinatorEntity,
        ),
    }
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)

    package = sys.modules["lth_pkg"]
    monkeypatch.setattr(package, "LocalTrailerHireCoordinator", object, raising=False)
    component = Path(__file__).resolve().parent.parent / "custom_components" / "localtrailerhire"
    spec = importlib.util.spec_from_file_location(
        "lth_pkg.sensor_discovery_test", component / "sensor.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


class _Coordinator:
    def __init__(self) -> None:
        self.listings: list[dict[str, Any]] = [{"id": "listing-1", "title": "First"}]
        self.data: list[dict[str, Any]] = []
        self.last_update_success = True
        self.listeners: list[Any] = []

    def async_add_listener(self, listener: Any) -> Any:
        self.listeners.append(listener)

        def remove_listener() -> None:
            self.listeners.remove(listener)

        return remove_listener

    def notify(self) -> None:
        for listener in list(self.listeners):
            listener()


class _Entry:
    entry_id = "entry-1"

    def __init__(self) -> None:
        self.options: dict[str, Any] = {}
        self.unload_callbacks: list[Any] = []

    def async_on_unload(self, callback: Any) -> None:
        self.unload_callbacks.append(callback)


@pytest.mark.asyncio
async def test_new_listing_gets_entities_after_platform_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensor = _load_sensor_module(monkeypatch)
    coordinator = _Coordinator()
    entry = _Entry()
    hass = SimpleNamespace(
        data={"localtrailerhire": {entry.entry_id: {"coordinator": coordinator}}}
    )
    batches: list[list[Any]] = []

    await sensor.async_setup_entry(hass, entry, lambda entities: batches.append(entities))
    initial_listing_entities = [
        entity for entity in batches[0] if isinstance(entity, sensor._BaseListingSensor)
    ]
    assert len(initial_listing_entities) == 3

    coordinator.listings.append({"id": "listing-2", "title": "Second"})
    coordinator.notify()

    assert len(batches) == 2
    assert {entity._listing_id for entity in batches[1]} == {"listing-2"}
    assert len(batches[1]) == 3


@pytest.mark.asyncio
async def test_listing_discovery_deduplicates_and_unsubscribes_on_unload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensor = _load_sensor_module(monkeypatch)
    coordinator = _Coordinator()
    entry = _Entry()
    hass = SimpleNamespace(
        data={"localtrailerhire": {entry.entry_id: {"coordinator": coordinator}}}
    )
    batches: list[list[Any]] = []

    await sensor.async_setup_entry(hass, entry, lambda entities: batches.append(entities))
    coordinator.notify()
    assert len(batches) == 1

    coordinator.listings.extend(
        [
            {"id": "listing-1", "title": "Duplicate"},
            {"id": "listing-2", "title": "Second"},
            {"id": None, "title": "Invalid"},
        ]
    )
    coordinator.notify()
    coordinator.notify()
    assert len(batches) == 2
    assert len(batches[1]) == 3

    assert len(entry.unload_callbacks) == 1
    entry.unload_callbacks[0]()
    coordinator.listings.append({"id": "listing-3", "title": "Third"})
    coordinator.notify()
    assert len(batches) == 2
