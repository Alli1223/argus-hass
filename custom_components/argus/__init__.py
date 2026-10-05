"""The Argus integration: an Argus server's hosts, alerts and containers in Home Assistant."""

from __future__ import annotations

from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry

from .api import ArgusClient
from .const import DOMAIN
from .coordinator import ArgusConfigEntry, ArgusCoordinator
from .entity import server_device

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ArgusConfigEntry) -> bool:
    client = ArgusClient(
        async_get_clientsession(hass, verify_ssl=entry.data.get(CONF_VERIFY_SSL, True)),
        entry.data[CONF_URL],
        entry.data[CONF_API_TOKEN],
    )
    coordinator = ArgusCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # The server's device first, so the host devices can name it as their parent.
    server = dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, **server_device(coordinator))
    coordinator.server_device_id = server.id

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ArgusConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: ArgusConfigEntry) -> None:
    """Options changed (such as how often to poll): start again with them."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(hass: HomeAssistant, entry: ArgusConfigEntry, device: DeviceEntry) -> bool:
    """Lets people delete devices for hosts that are gone from Argus, but not ones still there."""
    coordinator = entry.runtime_data
    return not any(
        domain == DOMAIN and (identifier in coordinator.data.hosts or identifier == entry.entry_id)
        for domain, identifier in device.identifiers
    )
