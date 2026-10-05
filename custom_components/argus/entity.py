"""Shared entity plumbing: every Argus host is a device, under one device for the server."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ArgusCoordinator

# Home Assistant 2026.8 links a device to its parent by the parent's device id; earlier releases by
# the parent's identifiers.
LINKS_BY_DEVICE_ID = "via_device_id" in DeviceInfo.__annotations__


def server_device(coordinator: ArgusCoordinator) -> DeviceInfo:
    entry = coordinator.config_entry
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=coordinator.server.get("name") or "Argus",
        manufacturer="Argus",
        model="Argus server",
        sw_version=coordinator.server.get("version"),
        configuration_url=coordinator.client.url,
        entry_type=DeviceEntryType.SERVICE,
    )


class ArgusServerEntity(CoordinatorEntity[ArgusCoordinator]):
    """Something about the whole Argus server."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ArgusCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"
        self._attr_device_info = server_device(coordinator)


class ArgusHostEntity(CoordinatorEntity[ArgusCoordinator]):
    """Something about one host. It goes unavailable if the host disappears from Argus."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ArgusCoordinator, host_id: str, key: str) -> None:
        super().__init__(coordinator)
        self.host_id = host_id
        self._attr_unique_id = f"{host_id}_{key}"
        host = coordinator.data.hosts[host_id]
        device = DeviceInfo(
            identifiers={(DOMAIN, host_id)},
            name=host["displayName"],
            manufacturer="Argus",
            model=host.get("osName") or host.get("platform"),
            sw_version=host.get("agentVersion"),
            configuration_url=f"{coordinator.client.url}/hosts/{host_id}",
        )
        if LINKS_BY_DEVICE_ID:
            device["via_device_id"] = coordinator.server_device_id  # type: ignore[typeddict-unknown-key]
        else:
            device["via_device"] = (DOMAIN, coordinator.config_entry.entry_id)
        self._attr_device_info = device

    @property
    def host(self) -> dict[str, Any]:
        return self.coordinator.data.hosts[self.host_id]

    @property
    def available(self) -> bool:
        return super().available and self.host_id in self.coordinator.data.hosts
