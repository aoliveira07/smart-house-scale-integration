"""Smart House Scale Home Assistant integration.

The integration is intentionally thin: Home Assistant owns Bluetooth discovery,
while the central Smart House API owns users, history and assignment decisions.
"""

from __future__ import annotations

from .const import DOMAIN

PLATFORMS = ["sensor"]


async def async_setup(hass, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass, entry) -> bool:
    from .runtime import ScaleRuntime

    runtime = ScaleRuntime(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    await runtime.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass, entry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    runtime = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if runtime:
        await runtime.async_stop()
    return unloaded


async def _async_options_updated(hass, entry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
