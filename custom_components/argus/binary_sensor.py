"""On/off states: whether each host reports, has alerts firing or an agent update, and its containers run."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ArgusConfigEntry, ArgusCoordinator
from .entity import ArgusHostEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ArgusConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    known_hosts: set[str] = set()
    known_containers: set[tuple[str, str]] = set()

    @callback
    def add_new() -> None:
        """Adds entities for hosts and containers that appeared since the last poll."""
        data = coordinator.data
        entities: list[BinarySensorEntity] = []
        for host_id in data.hosts.keys() - known_hosts:
            known_hosts.add(host_id)
            entities += [
                ArgusOnlineSensor(coordinator, host_id),
                ArgusProblemSensor(coordinator, host_id),
                ArgusAgentUpdateSensor(coordinator, host_id),
            ]
        for host_id, containers in data.containers.items():
            if host_id not in data.hosts:
                continue
            for name in containers:
                if (host_id, name) not in known_containers:
                    known_containers.add((host_id, name))
                    entities.append(ArgusContainerSensor(coordinator, host_id, name))
        if entities:
            async_add_entities(entities)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class ArgusOnlineSensor(ArgusHostEntity, BinarySensorEntity):
    """On while the host's agent is reporting."""

    _attr_translation_key = "online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: ArgusCoordinator, host_id: str) -> None:
        super().__init__(coordinator, host_id, "online")

    @property
    def is_on(self) -> bool:
        return self.host["status"] == "Online"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"last_seen": self.host.get("lastSeenAt"), "agent_version": self.host.get("agentVersion")}


class ArgusProblemSensor(ArgusHostEntity, BinarySensorEntity):
    """On while any of Argus's alerts is firing for the host."""

    _attr_translation_key = "problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: ArgusCoordinator, host_id: str) -> None:
        super().__init__(coordinator, host_id, "problem")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.alerts_for(self.host_id))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        severities = [alert["severity"] for alert in self.coordinator.data.alerts_for(self.host_id)]
        worst = next((level for level in ("Critical", "Warning", "Info") if level in severities), None)
        return {"severity": worst}


class ArgusAgentUpdateSensor(ArgusHostEntity, BinarySensorEntity):
    """On when a newer agent is available for the host."""

    _attr_translation_key = "agent_update"
    _attr_device_class = BinarySensorDeviceClass.UPDATE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ArgusCoordinator, host_id: str) -> None:
        super().__init__(coordinator, host_id, "agent_update")

    @property
    def is_on(self) -> bool:
        return bool((self.host.get("agentUpdate") or {}).get("available"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        update = self.host.get("agentUpdate") or {}
        return {"installed": self.host.get("agentVersion"), "available": update.get("available")}


class ArgusContainerSensor(ArgusHostEntity, BinarySensorEntity):
    """On while a Docker container is running. Unavailable once the host stops reporting it."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_translation_key = "container"

    def __init__(self, coordinator: ArgusCoordinator, host_id: str, name: str) -> None:
        super().__init__(coordinator, host_id, f"container_{name}")
        self.container_name = name
        self._attr_translation_placeholders = {"name": name}

    @property
    def _container(self) -> dict[str, Any] | None:
        return self.coordinator.data.containers.get(self.host_id, {}).get(self.container_name)

    @property
    def available(self) -> bool:
        return super().available and self._container is not None

    @property
    def is_on(self) -> bool:
        container = self._container
        return container is not None and container["state"] == "running"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        container = self._container or {}
        return {
            "state": container.get("state"),
            "health": container.get("health"),
            "image": container.get("image"),
            "restarts_last_hour": container.get("restartsLastHour"),
        }
