"""Setting up Argus from the UI: the server's address and a read-only API token."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .api import ArgusAuthError, ArgusClient, ArgusConnectionError, normalize_url
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    TOKEN_PREFIX,
)
from .coordinator import ArgusConfigEntry

_LOGGER = logging.getLogger(__name__)

TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


class ArgusConfigFlow(ConfigFlow, domain=DOMAIN):
    """One entry per Argus server and person."""

    VERSION = 1

    async def _check(self, url: str, token: str, verify_ssl: bool) -> tuple[dict[str, str], dict[str, Any]]:
        """Signs in with the token. Answers form errors, and on success the server and person."""
        if not token.strip().startswith(TOKEN_PREFIX):
            return {CONF_API_TOKEN: "invalid_token_format"}, {}
        if urlparse(url).scheme not in ("http", "https"):
            return {CONF_URL: "invalid_url"}, {}

        client = ArgusClient(async_get_clientsession(self.hass, verify_ssl=verify_ssl), url, token.strip())
        try:
            info = await client.get_info()
            me = await client.get_me()
        except ArgusAuthError:
            return {"base": "invalid_auth"}, {}
        except ArgusConnectionError as err:
            _LOGGER.debug("Could not reach Argus at %s: %s", url, err)
            return {"base": "cannot_connect"}, {}
        except Exception:
            _LOGGER.exception("Unexpected error while checking Argus at %s", url)
            return {"base": "unknown"}, {}
        return {}, {"info": info, "me": me}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = normalize_url(user_input[CONF_URL])
            errors, found = await self._check(url, user_input[CONF_API_TOKEN], user_input[CONF_VERIFY_SSL])
            if not errors:
                await self.async_set_unique_id(f"{url}|{found['me']['id']}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"{found['info'].get('name') or 'Argus'} ({urlparse(url).hostname})",
                    data={
                        CONF_URL: url,
                        CONF_API_TOKEN: user_input[CONF_API_TOKEN].strip(),
                        CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_URL): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
                vol.Required(CONF_API_TOKEN): TOKEN_SELECTOR,
                vol.Required(CONF_VERIFY_SSL, default=True): bool,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The token stopped working, usually because it was revoked: ask for a new one."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, found = await self._check(
                entry.data[CONF_URL], user_input[CONF_API_TOKEN], entry.data.get(CONF_VERIFY_SSL, True)
            )
            if not errors:
                await self.async_set_unique_id(f"{entry.data[CONF_URL]}|{found['me']['id']}")
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_TOKEN: user_input[CONF_API_TOKEN].strip()}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_TOKEN): TOKEN_SELECTOR}),
            description_placeholders={"url": entry.data[CONF_URL]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ArgusConfigEntry) -> OptionsFlow:
        return ArgusOptionsFlow()


class ArgusOptionsFlow(OptionsFlow):
    """How often to ask Argus for new readings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])})

        current = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=1,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )
