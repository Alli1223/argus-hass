"""Readings: each host's usage and temperatures, and the server's alert and host counts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfDataRate, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import ArgusConfigEntry, ArgusCoordinator, ArgusData
from .entity import ArgusHostEntity, ArgusServerEntity

PARALLEL_UPDATES = 0

# Attributes are stored with every state change; long alert lists are cut short to keep them small.
MAX_LISTED_ALERTS = 25


def _latest(key: str) -> Callable[[dict[str, Any]], Any]:
    return lambda host: (host.get("latest") or {}).get(key)


def _rounded(key: str, digits: int = 1) -> Callable[[dict[str, Any]], Any]:
    def value(host: dict[str, Any]) -> Any:
        reading = _latest(key)(host)
        return None if reading is None else round(reading, digits)

    return value


def _last_boot(host: dict[str, Any]) -> datetime | None:
    """Boot time to the minute, so it doesn't wobble between polls."""
    latest = host.get("latest")
    if not latest or not latest.get("uptimeSeconds"):
        return None
    sample = dt_util.parse_datetime(latest["time"])
    if sample is None:
        return None
    boot = sample - timedelta(seconds=latest["uptimeSeconds"])
    return boot.replace(second=0, microsecond=0)


@dataclass(frozen=True, kw_only=True)
class ArgusHostSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]


HOST_SENSORS: tuple[ArgusHostSensorDescription, ...] = (
    ArgusHostSensorDescription(
        key="cpu",
        translation_key="cpu",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_rounded("cpuPercent"),
    ),
    ArgusHostSensorDescription(
        key="memory",
        translation_key="memory",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_rounded("memoryPercent"),
    ),
    ArgusHostSensorDescription(
        key="swap",
        translation_key="swap",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        value_fn=_rounded("swapPercent"),
    ),
    ArgusHostSensorDescription(
        key="disk",
        translation_key="disk",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_rounded("diskUsedPercent"),
    ),
    ArgusHostSensorDescription(
        key="load_1",
        translation_key="load_1",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_rounded("load1", 2),
    ),
    ArgusHostSensorDescription(
        key="network_in",
        translation_key="network_in",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_rounded("netRxBytesPerSec", 0),
    ),
    ArgusHostSensorDescription(
        key="network_out",
        translation_key="network_out",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_rounded("netTxBytesPerSec", 0),
    ),
    ArgusHostSensorDescription(
        key="last_boot",
        translation_key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_last_boot,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ArgusConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([ArgusAlertCountSensor(coordinator), ArgusHostsOnlineSensor(coordinator)])

    known_hosts: set[str] = set()
    known_temperatures: set[tuple[str, str]] = set()

    @callback
    def add_new() -> None:
        """Adds entities for hosts and temperature sensors that appeared since the last poll."""
        data: ArgusData = coordinator.data
        entities: list[SensorEntity] = []
        for host_id in data.hosts.keys() - known_hosts:
            known_hosts.add(host_id)
            entities.extend(ArgusHostSensor(coordinator, host_id, description) for description in HOST_SENSORS)
            entities.append(ArgusHostAlertsSensor(coordinator, host_id))
            entities.append(ArgusHighestTemperatureSensor(coordinator, host_id))
        for host_id, readings in data.temperatures.items():
            if host_id not in data.hosts:
                continue
            for sensor in readings:
                if (host_id, sensor) not in known_temperatures:
                    known_temperatures.add((host_id, sensor))
                    entities.append(ArgusTemperatureSensor(coordinator, host_id, sensor))
        if entities:
            async_add_entities(entities)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class ArgusHostSensor(ArgusHostEntity, SensorEntity):
    """One of a host's latest readings."""

    entity_description: ArgusHostSensorDescription

    def __init__(self, coordinator: ArgusCoordinator, host_id: str, description: ArgusHostSensorDescription) -> None:
        super().__init__(coordinator, host_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.host)


class ArgusHostAlertsSensor(ArgusHostEntity, SensorEntity):
    """How many of Argus's alerts are firing for this host."""

    _attr_translation_key = "host_alerts"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ArgusCoordinator, host_id: str) -> None:
        super().__init__(coordinator, host_id, "alerts")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.alerts_for(self.host_id))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        alerts = self.coordinator.data.alerts_for(self.host_id)
        return {"alerts": [_alert_summary(alert) for alert in alerts[:MAX_LISTED_ALERTS]]}


class ArgusHighestTemperatureSensor(ArgusHostEntity, SensorEntity):
    """The hottest sensor on the host right now, and which one it is."""

    _attr_translation_key = "highest_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ArgusCoordinator, host_id: str) -> None:
        super().__init__(coordinator, host_id, "highest_temperature")

    @property
    def _readings(self) -> dict[str, float]:
        return self.coordinator.data.temperatures.get(self.host_id, {})

    @property
    def native_value(self) -> float | None:
        return max(self._readings.values(), default=None)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        readings = self._readings
        if not readings:
            return {}
        return {"sensor": max(readings, key=readings.__getitem__), "sensors": dict(sorted(readings.items()))}


class ArgusTemperatureSensor(ArgusHostEntity, SensorEntity):
    """One temperature sensor, such as `coretemp/Package id 0`. Off until someone turns it on."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: ArgusCoordinator, host_id: str, sensor: str) -> None:
        super().__init__(coordinator, host_id, f"temperature_{sensor}")
        self.sensor = sensor
        device, _, name = sensor.partition("/")
        self._attr_name = f"{device} {name}".strip() if name else device

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.temperatures.get(self.host_id, {}).get(self.sensor)


class ArgusAlertCountSensor(ArgusServerEntity, SensorEntity):
    """How many alerts are firing across every host."""

    _attr_translation_key = "firing_alerts"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ArgusCoordinator) -> None:
        super().__init__(coordinator, "firing_alerts")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.alerts)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        alerts = self.coordinator.data.alerts
        return {
            "critical": sum(alert["severity"] == "Critical" for alert in alerts),
            "warning": sum(alert["severity"] == "Warning" for alert in alerts),
            "info": sum(alert["severity"] == "Info" for alert in alerts),
            "alerts": [_alert_summary(alert) for alert in alerts[:MAX_LISTED_ALERTS]],
        }


class ArgusHostsOnlineSensor(ArgusServerEntity, SensorEntity):
    """How many hosts are reporting."""

    _attr_translation_key = "hosts_online"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ArgusCoordinator) -> None:
        super().__init__(coordinator, "hosts_online")

    @property
    def native_value(self) -> int:
        return sum(host["status"] == "Online" for host in self.coordinator.data.hosts.values())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        hosts = self.coordinator.data.hosts.values()
        return {
            "total": len(hosts),
            "offline": sorted(host["displayName"] for host in hosts if host["status"] != "Online"),
        }


def _alert_summary(alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": alert["title"],
        "host": alert["hostName"],
        "severity": alert["severity"],
        "fired_at": alert["firedAt"],
    }
