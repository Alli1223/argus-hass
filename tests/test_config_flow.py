"""Setting Argus up from the UI, a token that stops working, and the options."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.argus.const import CONF_SCAN_INTERVAL, DOMAIN

from .conftest import TOKEN, URL, USER_ID, FakeArgus

USER_INPUT = {CONF_URL: URL + "/", CONF_API_TOKEN: f"  {TOKEN} ", CONF_VERIFY_SSL: True}


async def test_creates_an_entry(hass: HomeAssistant, argus: FakeArgus) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Argus (argus.example.com)"
    assert result["data"] == {CONF_URL: URL, CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True}
    assert result["result"].unique_id == f"{URL}|{USER_ID}"


async def test_refuses_an_enrollment_token(hass: HomeAssistant, argus: FakeArgus) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_API_TOKEN: "argus_et_" + "a" * 43}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_API_TOKEN: "invalid_token_format"}


async def test_reports_a_refused_token(
    hass: HomeAssistant, argus: FakeArgus, aioclient_mock: AiohttpClientMocker
) -> None:
    argus.status = 401
    argus.install(aioclient_mock)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["errors"] == {"base": "invalid_auth"}


async def test_reports_an_unreachable_server(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{URL}/api/info", exc=TimeoutError())

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["errors"] == {"base": "cannot_connect"}


async def test_the_same_account_is_set_up_once(
    hass: HomeAssistant, argus: FakeArgus, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_takes_a_new_token(hass: HomeAssistant, argus: FakeArgus, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    new_token = "argus_at_" + "b" * 43

    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_TOKEN: new_token})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_API_TOKEN] == new_token


async def test_options_set_the_poll_interval(
    hass: HomeAssistant, argus: FakeArgus, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_SCAN_INTERVAL: 60})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_SCAN_INTERVAL: 60}
    assert config_entry.runtime_data.update_interval.total_seconds() == 60
