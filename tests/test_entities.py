"""What Argus's hosts, alerts, containers and temperatures look like in Home Assistant."""

from __future__ import annotations

import copy

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.argus.const import DOMAIN, EVENT_ALERT_FIRED, EVENT_ALERT_RESOLVED

from .conftest import ALERT, HOST, HOST_ID, OTHER_HOST_ID, FakeArgus


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def poll(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """What the coordinator does on each tick of its interval."""
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


def find_device(hass: HomeAssistant, entry: MockConfigEntry, identifier: str) -> dr.DeviceEntry | None:
    registry = dr.async_get(hass)
    if hasattr(registry, "async_get_device_by_identifier"):  # Home Assistant 2026.8 and later
        return registry.async_get_device_by_identifier((DOMAIN, identifier), entry.entry_id)
    return registry.async_get_device(identifiers={(DOMAIN, identifier)})


async def test_a_host_becomes_a_device_with_readings(
    hass: HomeAssistant, argus: FakeArgus, config_entry: MockConfigEntry
) -> None:
    await setup(hass, config_entry)

    device = find_device(hass, config_entry, HOST_ID)
    assert device is not None
    assert device.via_device_id == find_device(hass, config_entry, config_entry.entry_id).id
    assert device.name == "homeassistant"
    assert device.model == "Home Assistant OS 16.2"
    assert device.configuration_url == f"https://argus.example.com/hosts/{HOST_ID}"

    assert hass.states.get("sensor.homeassistant_cpu_usage").state == "12.3"
    assert hass.states.get("sensor.homeassistant_memory_usage").state == "41.3"
    assert hass.states.get("sensor.homeassistant_fullest_disk").state == "63.0"
    assert hass.states.get("sensor.homeassistant_load_1_min").state == "0.46"
    assert hass.states.get("sensor.homeassistant_last_boot").state == "2026-10-05T07:59:00+00:00"
    # 125 kB/s is 1 Mbit/s, shown in Mbit/s.
    network_in = hass.states.get("sensor.homeassistant_network_in")
    assert network_in.attributes["unit_of_measurement"] == "Mbit/s"
    assert float(network_in.state) == 1.0

    assert hass.states.get("binary_sensor.homeassistant_online").state == STATE_ON
    assert hass.states.get("binary_sensor.homeassistant_agent_update").state == STATE_OFF


async def test_swap_and_single_temperature_sensors_start_disabled(
    hass: HomeAssistant, argus: FakeArgus, config_entry: MockConfigEntry
) -> None:
    await setup(hass, config_entry)
    registry = er.async_get(hass)

    assert registry.async_get("sensor.homeassistant_swap_usage").disabled
    assert registry.async_get("sensor.homeassistant_nvme0_composite").disabled
    assert hass.states.get("sensor.homeassistant_swap_usage") is None


async def test_highest_temperature_uses_each_sensors_newest_reading(
    hass: HomeAssistant, argus: FakeArgus, config_entry: MockConfigEntry
) -> None:
    await setup(hass, config_entry)

    state = hass.states.get("sensor.homeassistant_highest_temperature")
    assert state.state == "52.0"
    assert state.attributes["sensor"] == "cpu_thermal/temp1"
    assert state.attributes["sensors"] == {"cpu_thermal/temp1": 52.0, "nvme0/Composite": 40.0}


async def test_alerts_show_as_counts_and_problems(
    hass: HomeAssistant, argus: FakeArgus, config_entry: MockConfigEntry
) -> None:
    await setup(hass, config_entry)

    assert hass.states.get("binary_sensor.homeassistant_problem").state == STATE_ON
    assert hass.states.get("binary_sensor.homeassistant_problem").attributes["severity"] == "Warning"
    assert hass.states.get("sensor.homeassistant_firing_alerts").state == "1"
    server = hass.states.get("sensor.argus_firing_alerts")
    assert server.state == "1"
    assert server.attributes["warning"] == 1
    assert server.attributes["alerts"][0]["title"] == ALERT["title"]
    assert hass.states.get("sensor.argus_hosts_online").state == "1"


async def test_containers_are_running_or_not(
    hass: HomeAssistant, argus: FakeArgus, config_entry: MockConfigEntry
) -> None:
    await setup(hass, config_entry)

    assert hass.states.get("binary_sensor.homeassistant_container_homeassistant").state == STATE_ON
    stopped = hass.states.get("binary_sensor.homeassistant_container_addon_argus_agent")
    assert stopped.state == STATE_OFF
    assert stopped.attributes["restarts_last_hour"] == 2


async def test_alert_changes_fire_events(
    hass: HomeAssistant,
    argus: FakeArgus,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    await setup(hass, config_entry)
    fired: list[Event] = async_capture_events(hass, EVENT_ALERT_FIRED)
    resolved: list[Event] = async_capture_events(hass, EVENT_ALERT_RESOLVED)

    new_alert = {**copy.deepcopy(ALERT), "id": "a2", "severity": "Critical", "title": "Disk full"}
    argus.alerts = [new_alert]
    argus.install(aioclient_mock)
    await poll(hass, config_entry)

    assert [event.data["title"] for event in fired] == ["Disk full"]
    assert fired[0].data["severity"] == "Critical"
    assert fired[0].data["host_name"] == "homeassistant"
    assert [event.data["alert_id"] for event in resolved] == ["a1"]
    assert hass.states.get("binary_sensor.homeassistant_problem").attributes["severity"] == "Critical"


async def test_hosts_and_containers_come_and_go(
    hass: HomeAssistant,
    argus: FakeArgus,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    await setup(hass, config_entry)

    argus.hosts.append({**copy.deepcopy(HOST), "id": OTHER_HOST_ID, "displayName": "nas", "status": "Offline"})
    argus.containers[0]["containers"].pop()
    argus.install(aioclient_mock)
    await poll(hass, config_entry)

    assert hass.states.get("binary_sensor.nas_online").state == STATE_OFF
    assert hass.states.get("sensor.argus_hosts_online").attributes["offline"] == ["nas"]
    assert hass.states.get("binary_sensor.homeassistant_container_addon_argus_agent").state == STATE_UNAVAILABLE

    argus.hosts = [host for host in argus.hosts if host["id"] != OTHER_HOST_ID]
    argus.install(aioclient_mock)
    await poll(hass, config_entry)
    assert hass.states.get("binary_sensor.nas_online").state == STATE_UNAVAILABLE


async def test_a_revoked_token_asks_for_a_new_one(
    hass: HomeAssistant,
    argus: FakeArgus,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    await setup(hass, config_entry)

    argus.status = 401
    argus.install(aioclient_mock)
    await poll(hass, config_entry)

    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]
    assert hass.states.get("sensor.homeassistant_cpu_usage").state == STATE_UNAVAILABLE


async def test_an_unreachable_server_retries_setup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    aioclient_mock.get("https://argus.example.com/api/info", exc=TimeoutError())
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_only_hosts_gone_from_argus_can_be_removed(
    hass: HomeAssistant, argus: FakeArgus, config_entry: MockConfigEntry
) -> None:
    await setup(hass, config_entry)
    devices = dr.async_get(hass)
    gone = devices.async_get_or_create(config_entry_id=config_entry.entry_id, identifiers={(DOMAIN, "gone")})
    present = find_device(hass, config_entry, HOST_ID)

    from custom_components.argus import async_remove_config_entry_device

    assert await async_remove_config_entry_device(hass, config_entry, gone)
    assert not await async_remove_config_entry_device(hass, config_entry, present)
