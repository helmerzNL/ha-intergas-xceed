"""Config flow for HeatCon."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    HeatconApiClient,
    HeatconApiError,
    HeatconInvalidAuthError,
)
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class HeatconConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HeatCon."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "HeatconOptionsFlow":
        """Get the options flow for this handler."""
        return HeatconOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()

            api = HeatconApiClient(
                host=user_input[CONF_HOST],
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                session=async_get_clientsession(self.hass),
            )

            try:
                await api.async_test_connection()
            except HeatconInvalidAuthError as err:
                _LOGGER.warning(
                    "HeatCon authentication failed for host %s: %s",
                    user_input[CONF_HOST],
                    err,
                )
                errors["base"] = "invalid_auth"
            except HeatconApiError as err:
                _LOGGER.exception(
                    "Unable to connect to HeatCon at host %s: %s",
                    user_input[CONF_HOST],
                    err,
                )
                errors["base"] = "cannot_connect"
            else:
                options = {
                    CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                }
                data = {
                    CONF_HOST: user_input[CONF_HOST],
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }
                return self.async_create_entry(
                    title=f"HeatCon ({user_input[CONF_HOST]})",
                    data=data,
                    options=options,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=10, max=3600),
                    ),
                }
            ),
            errors=errors,
        )


class HeatconOptionsFlow(config_entries.OptionsFlow):
    """Handle options for the HeatCon integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the integration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
                }
            ),
        )
