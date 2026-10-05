"""Diagnostics download, with the token removed."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant

from .coordinator import ArgusConfigEntry


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ArgusConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(entry.as_dict(), {CONF_API_TOKEN}),
        "server": coordinator.server,
        "data": asdict(coordinator.data) if coordinator.data else None,
    }
