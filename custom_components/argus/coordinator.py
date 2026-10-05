"""Polls Argus and keeps the newest picture of its hosts, alerts, containers and temperatures."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ArgusAuthError, ArgusClient, ArgusError, latest_temperatures
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_ALERT_FIRED,
    EVENT_ALERT_RESOLVED,
    TEMPERATURE_WINDOW,
)

_LOGGER = logging.getLogger(__name__)

type ArgusConfigEntry = ConfigEntry[ArgusCoordinator]


@dataclass
class ArgusData:
    """One poll of Argus."""

    hosts: dict[str, dict[str, Any]] = field(default_factory=dict)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    # Containers by host id, then by container name.
    containers: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    # Newest temperature per sensor, by host id, then by `{device}/{sensor}`.
    temperatures: dict[str, dict[str, float]] = field(default_factory=dict)

    def alerts_for(self, host_id: str) -> list[dict[str, Any]]:
        return [alert for alert in self.alerts if alert["hostId"] == host_id]


class ArgusCoordinator(DataUpdateCoordinator[ArgusData]):
    """Reads everything in one go, so entities never mix readings from different moments."""

    config_entry: ArgusConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ArgusConfigEntry, client: ArgusClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        )
        self.client = client
        self.server: dict[str, Any] = {}
        # The device standing for the Argus server, which host devices hang off; set during setup.
        self.server_device_id: str | None = None

    async def _async_setup(self) -> None:
        try:
            self.server = await self.client.get_info()
        except ArgusAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ArgusError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_update_data(self) -> ArgusData:
        try:
            hosts, alerts, containers, temperatures = await asyncio.gather(
                self.client.get_hosts(),
                self.client.get_firing_alerts(),
                self.client.get_containers(),
                self.client.get_temperatures(TEMPERATURE_WINDOW),
            )
        except ArgusAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ArgusError as err:
            raise UpdateFailed(str(err)) from err

        data = ArgusData(
            hosts={host["id"]: host for host in hosts},
            alerts=alerts,
            containers={
                host["hostId"]: {container["name"]: container for container in host["containers"]}
                for host in containers
            },
            temperatures={host["hostId"]: latest_temperatures(host["history"]) for host in temperatures},
        )
        if self.data is not None:
            self._announce_alert_changes(self.data.alerts, data.alerts)
        return data

    def _announce_alert_changes(self, before: list[dict[str, Any]], after: list[dict[str, Any]]) -> None:
        """Fires an event for each alert that started or stopped firing since the last poll."""
        old = {alert["id"]: alert for alert in before}
        new = {alert["id"]: alert for alert in after}
        for alert_id in new.keys() - old.keys():
            self.hass.bus.async_fire(EVENT_ALERT_FIRED, _event_data(new[alert_id]))
        for alert_id in old.keys() - new.keys():
            self.hass.bus.async_fire(EVENT_ALERT_RESOLVED, _event_data(old[alert_id]))


def _event_data(alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "alert_id": alert["id"],
        "host_id": alert["hostId"],
        "host_name": alert["hostName"],
        "title": alert["title"],
        "severity": alert["severity"],
        "metric": alert["metric"],
        "value": alert.get("value"),
        "threshold": alert.get("threshold"),
        "fired_at": alert["firedAt"],
    }
