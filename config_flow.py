"""UI configuration flow for one physical scale and the central API."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from .const import (
    CONF_API_TOKEN,
    CONF_API_URL,
    CONF_DEVICE_NAME,
    CONF_MAC_ADDRESS,
    CONF_SESSION_WINDOW,
    DEFAULT_API_URL,
    DEFAULT_SESSION_WINDOW,
    DOMAIN,
)
from .parser import normalize_mac


class SmartHouseScaleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        errors: dict[str, str] = {}
        if user_input:
            try:
                user_input[CONF_MAC_ADDRESS] = normalize_mac(user_input[CONF_MAC_ADDRESS])
            except ValueError:
                errors[CONF_MAC_ADDRESS] = "invalid_mac"
            if not errors:
                await self.async_set_unique_id(user_input[CONF_MAC_ADDRESS].replace(":", "").lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input[CONF_DEVICE_NAME], data=user_input)
        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_NAME, default="Smart House Scale"): str,
                vol.Required(CONF_MAC_ADDRESS): str,
                vol.Required(CONF_API_URL, default=DEFAULT_API_URL): str,
                vol.Required(CONF_API_TOKEN): vol.All(str, vol.Length(min=1)),
                vol.Optional(CONF_SESSION_WINDOW, default=DEFAULT_SESSION_WINDOW): vol.All(int, vol.Range(min=5, max=300)),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry):
        return SmartHouseScaleOptionsFlow()


class SmartHouseScaleOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict | None = None):
        if user_input:
            return self.async_create_entry(data=user_input)
        entry = self.config_entry
        schema = vol.Schema(
            {
                vol.Required(CONF_API_URL, default=entry.data[CONF_API_URL]): str,
                vol.Required(CONF_API_TOKEN, default=entry.options.get(CONF_API_TOKEN, entry.data.get(CONF_API_TOKEN, ""))): vol.All(str, vol.Length(min=1)),
                vol.Optional(CONF_SESSION_WINDOW, default=entry.options.get(CONF_SESSION_WINDOW, DEFAULT_SESSION_WINDOW)): vol.All(int, vol.Range(min=5, max=300)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
