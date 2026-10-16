"""Home Assistant runtime: native BLE callback, sessions and offline sync."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event

from .api import ScaleApiClient
from .const import (
    CONF_API_TOKEN,
    CONF_API_URL,
    CONF_DEVICE_NAME,
    CONF_MAC_ADDRESS,
    CONF_SESSION_WINDOW,
    DEFAULT_SESSION_WINDOW,
    DOMAIN,
    SIGNAL_UPDATE,
)
from .parser import ParsedMeasurement, normalize_mac, parse_native_entity_state, parse_service_info
from .queue import OfflineQueue
from .session import SessionAggregator

_LOGGER = logging.getLogger(__name__)


class ScaleRuntime:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self.mac_address = normalize_mac(entry.data[CONF_MAC_ADDRESS])
        self.device_name = entry.data.get(CONF_DEVICE_NAME, "Smart House Scale")
        self.api = ScaleApiClient(
            entry.options.get(CONF_API_URL, entry.data[CONF_API_URL]),
            entry.options.get(CONF_API_TOKEN, entry.data.get(CONF_API_TOKEN)),
        )
        window = int(entry.options.get(CONF_SESSION_WINDOW, DEFAULT_SESSION_WINDOW))
        self.sessions = SessionAggregator(window)
        self.queue = OfflineQueue(Path(hass.config.path("smart_house_scale_queue.sqlite3")))
        self.cancel_ble: Any = None
        self.cancel_native_entity: Callable[[], None] | None = None
        self.native_entity_id: str | None = None
        self.native_model: str | None = None
        self.native_retry_task: asyncio.Task[None] | None = None
        self.flush_task: asyncio.Task[None] | None = None
        self.last_state = "listening"
        self.last_measurement: dict[str, Any] | None = None
        self.last_ble_seen_at: str | None = None
        self.last_error: str | None = None
        self.pending_count = len(self.queue)
        self.user_summaries: dict[str, dict[str, Any]] = {}

    async def async_start(self) -> None:
        matcher = {"address": self.mac_address}
        # Advertisement callbacks are required here: the normal callback only
        # fires when HA sees changed data and would hide repeated scale frames.
        register = getattr(bluetooth, "async_register_advertisement_callback", None)
        if register:
            self.cancel_ble = register(self.hass, self._on_advertisement, self.mac_address)
        else:
            self.cancel_ble = bluetooth.async_register_callback(
                self.hass, self._on_advertisement, matcher, bluetooth.BluetoothScanningMode.PASSIVE
            )
        if not await self._async_connect_native_entity():
            self.native_retry_task = asyncio.create_task(self._async_retry_native_entity())
        self.flush_task = asyncio.create_task(self._flush_loop())
        await self.async_flush_queue()

    async def async_stop(self) -> None:
        if self.cancel_ble:
            self.cancel_ble()
            self.cancel_ble = None
        if self.cancel_native_entity:
            self.cancel_native_entity()
            self.cancel_native_entity = None
        if self.native_retry_task:
            self.native_retry_task.cancel()
            await asyncio.gather(self.native_retry_task, return_exceptions=True)
            self.native_retry_task = None
        if self.flush_task:
            self.flush_task.cancel()
            await asyncio.gather(self.flush_task, return_exceptions=True)
            self.flush_task = None

    @callback
    def _on_advertisement(self, service_info: Any, *_args: Any) -> None:
        self.last_ble_seen_at = datetime.now(UTC).isoformat()
        try:
            parsed = parse_service_info(service_info, expected_mac=self.mac_address)
        except ValueError as exc:
            self.last_state = "parse_error"
            self.last_error = str(exc)
            _LOGGER.debug("Could not parse Xiaomi advertisement: %s", exc)
            return
        if not parsed:
            return
        self.last_state = "not_stabilized" if not parsed.stable else "measurement_received"
        final = self.sessions.ingest(parsed)
        if final:
            self.hass.async_create_task(self._async_finalize(final))

    async def _async_retry_native_entity(self) -> None:
        for delay in (3, 10, 30):
            await asyncio.sleep(delay)
            if await self._async_connect_native_entity():
                return

    async def _async_connect_native_entity(self) -> bool:
        """Listen to the native Xiaomi BLE weight entity when available."""

        entity_id, model = self._find_native_weight_entity()
        if not entity_id:
            return False
        if entity_id == self.native_entity_id and self.cancel_native_entity:
            return True
        if self.cancel_native_entity:
            self.cancel_native_entity()
        self.native_entity_id = entity_id
        self.native_model = model
        self.cancel_native_entity = async_track_state_change_event(
            self.hass, [entity_id], self._async_native_state_changed
        )
        _LOGGER.info("Using native Xiaomi BLE weight entity %s", entity_id)
        return True

    def _find_native_weight_entity(self) -> tuple[str | None, str | None]:
        device_registry = dr.async_get(self.hass)
        native_device_ids: set[str] = set()
        models: dict[str, str | None] = {}
        for device in device_registry.devices.values():
            for connection_type, connection_value in device.connections:
                if connection_type != dr.CONNECTION_BLUETOOTH:
                    continue
                try:
                    matches = normalize_mac(str(connection_value)) == self.mac_address
                except ValueError:
                    matches = False
                if matches:
                    native_device_ids.add(device.id)
                    models[device.id] = device.model

        entity_registry = er.async_get(self.hass)
        candidates = []
        for entity in entity_registry.entities.values():
            if entity.domain != "sensor" or entity.platform != "xiaomi_ble":
                continue
            if native_device_ids and entity.device_id not in native_device_ids:
                continue
            if entity.disabled_by:
                continue
            searchable = " ".join(
                str(value or "")
                for value in (entity.entity_id, entity.unique_id, entity.original_name, entity.original_device_class)
            ).lower()
            if "weight" in searchable or "peso" in searchable:
                candidates.append(entity)
        if not candidates and not native_device_ids:
            return None, None
        if not candidates:
            return None, None
        candidates.sort(key=lambda item: (0 if "weight" in str(item.original_device_class).lower() else 1, item.entity_id))
        selected = candidates[0]
        return selected.entity_id, models.get(selected.device_id)

    @callback
    def _async_native_state_changed(self, event: Any) -> None:
        self.last_ble_seen_at = datetime.now(UTC).isoformat()
        reading = parse_native_entity_state(
            event.data.get("new_state"),
            mac_address=self.mac_address,
            entity_id=self.native_entity_id or "",
            model=self.native_model,
        )
        if not reading:
            return
        self.last_state = "measurement_received"
        final = self.sessions.ingest(reading)
        if final:
            self.hass.async_create_task(self._async_finalize(final))

    async def _async_finalize(self, reading: ParsedMeasurement) -> None:
        payload = {
            "measurement_uuid": str(uuid.uuid4()),
            "session_uuid": str(self.sessions.last_finalized.session_uuid) if self.sessions.last_finalized else None,
            "session_started_at": self.sessions.last_finalized.started_at.isoformat() if self.sessions.last_finalized else None,
            "session_last_seen_at": self.sessions.last_finalized.last_seen_at.isoformat() if self.sessions.last_finalized else None,
            "advertisement_count": self.sessions.last_finalized.advertisement_count if self.sessions.last_finalized else 1,
            "mac_address": reading.mac_address,
            "device_name": self.device_name,
            "measured_at": reading.measured_at.isoformat(),
            "received_at": datetime.now(UTC).isoformat(),
            "weight_kg": reading.weight_kg,
            "original_unit": reading.original_unit,
            "impedance": reading.impedance,
            "rssi": reading.rssi,
            "protocol": reading.protocol,
            "model": reading.model,
            "raw_payload": reading.raw_payload,
            "stable": reading.stable,
        }
        self.last_measurement = payload
        try:
            response = await self.api.post_measurement(payload)
            self.last_state = response.get("status", "assigned")
            self.last_error = None
            self._update_summary(response)
        except Exception as exc:  # network errors are expected during outages
            self.last_state = "queued"
            self.last_error = type(exc).__name__
            self.queue.put(payload["measurement_uuid"], payload, payload["received_at"])
        self.pending_count = len(self.queue)
        async_dispatcher_send(self.hass, SIGNAL_UPDATE, self.entry.entry_id)

    def _update_summary(self, response: dict[str, Any]) -> None:
        summary = response.get("user_summary")
        if summary and summary.get("user_id"):
            self.user_summaries[str(summary["user_id"])] = summary

    async def async_flush_queue(self) -> None:
        for item in self.queue.items():
            try:
                response = await self.api.post_measurement(item)
            except Exception as exc:
                self.last_error = type(exc).__name__
                break
            self.queue.remove(item["measurement_uuid"])
            self._update_summary(response)
        self.pending_count = len(self.queue)
        async_dispatcher_send(self.hass, SIGNAL_UPDATE, self.entry.entry_id)

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            await self.async_flush_queue()

    async def async_refresh_users(self) -> list[dict[str, Any]]:
        try:
            users = await self.api.request("GET", "/api/v1/scale-users")
        except Exception as exc:
            self.last_error = type(exc).__name__
            return list(self.user_summaries.values())
        for user in users if isinstance(users, list) else []:
            try:
                summary = await self.api.request("GET", f"/api/v1/scale-users/{user['id']}/summary")
                self.user_summaries[str(user["id"])] = {**user, **summary}
            except Exception:
                self.user_summaries[str(user["id"])] = user
        return list(self.user_summaries.values())

    def diagnostics(self) -> dict[str, Any]:
        return {
            "state": self.last_state,
            "mac_address": self.mac_address,
            "device_name": self.device_name,
            "api_url": self.api.base_url,
            "last_measurement": self.last_measurement,
            "last_ble_seen": self.last_ble_seen_at,
            "native_entity_id": self.native_entity_id,
            "last_attempt": self.api.last_attempt,
            "last_sync": self.api.last_success,
            "queue_items": self.pending_count,
            "last_error": self.last_error or self.api.last_error,
        }
