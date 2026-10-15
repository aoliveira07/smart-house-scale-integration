"""Stable Home Assistant entities for the scale device and house users."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfMass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.util import slugify

from .const import DOMAIN, SIGNAL_UPDATE
from .runtime import ScaleRuntime


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    runtime: ScaleRuntime = hass.data[DOMAIN][entry.entry_id]
    users = await runtime.async_refresh_users()
    entities: list[SensorEntity] = [
        ScaleDeviceSensor(runtime, "last_measurement", "Última pesagem", SensorDeviceClass.WEIGHT, UnitOfMass.KILOGRAMS),
        ScaleDeviceSensor(runtime, "last_seen", "Última comunicação", None, None),
        ScaleDeviceSensor(runtime, "pending_measurements", "Pesagens pendentes", None, None),
        ScaleDiagnosticSensor(runtime),
    ]
    for user in users:
        entities.extend(UserSensor(runtime, user, metric) for metric in UserSensor.METRICS)
    async_add_entities(entities)
    known_user_ids = {str(user["id"]) for user in users}

    @callback
    def _async_new_data() -> None:
        additions: list[SensorEntity] = []
        for user_id, user in runtime.user_summaries.items():
            if user_id not in known_user_ids:
                additions.extend(UserSensor(runtime, user, metric) for metric in UserSensor.METRICS)
                known_user_ids.add(user_id)
        if additions:
            entities.extend(additions)
            async_add_entities(additions)
        for entity in entities:
            entity.async_write_ha_state()

    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_UPDATE, _async_new_data))


class RuntimeEntity(SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, runtime: ScaleRuntime):
        self.runtime = runtime
        self._attr_device_info = {
            "identifiers": {(DOMAIN, runtime.mac_address)},
            "name": runtime.device_name,
            "manufacturer": "Xiaomi",
            "model": "Xiaomi BLE Scale",
        }


class ScaleDeviceSensor(RuntimeEntity):
    def __init__(self, runtime: ScaleRuntime, key: str, name: str, device_class: Any, unit: Any):
        super().__init__(runtime)
        self.key = key
        self._attr_name = name
        self._attr_unique_id = f"{runtime.mac_address.lower().replace(':', '')}_{key}"
        self._attr_suggested_object_id = f"smart_house_scale_{key}"
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_entity_category = EntityCategory.DIAGNOSTIC if key != "last_measurement" else None
        self._attr_state_class = SensorStateClass.MEASUREMENT if key == "last_measurement" else None

    @property
    def native_value(self) -> Any:
        if self.key == "last_measurement":
            return (self.runtime.last_measurement or {}).get("weight_kg")
        if self.key == "last_seen":
            return self.runtime.api.last_attempt
        return self.runtime.pending_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.key == "last_measurement":
            return self.runtime.last_measurement or {}
        return self.runtime.diagnostics()


class ScaleDiagnosticSensor(RuntimeEntity):
    _attr_name = "Bluetooth/API diagnostic"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime: ScaleRuntime):
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.mac_address.lower().replace(':', '')}_diagnostic"
        self._attr_suggested_object_id = "smart_house_scale_diagnostic"

    @property
    def native_value(self) -> str:
        return self.runtime.last_state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.runtime.diagnostics()


class UserSensor(RuntimeEntity):
    METRICS = ("weight", "bmi", "weight_trend", "weight_change_7d", "weight_change_30d")

    def __init__(self, runtime: ScaleRuntime, user: dict[str, Any], metric: str):
        super().__init__(runtime)
        self.user_id = str(user["id"])
        self.metric = metric
        self._user = user
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"user_{self.user_id}")},
            "name": user.get("name", "Usuário"),
            "manufacturer": "Smart House",
            "model": "Scale user",
        }
        self._attr_unique_id = f"{self.user_id}_{metric}"
        self._attr_name = f"{user.get('name', 'Usuário')} {metric.replace('_', ' ')}"
        self._attr_suggested_object_id = f"{slugify(user.get('name', 'usuario'))}_{metric}"
        if metric == "weight":
            self._attr_device_class = SensorDeviceClass.WEIGHT
            self._attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
            self._attr_state_class = SensorStateClass.MEASUREMENT
        elif metric == "bmi":
            self._attr_native_unit_of_measurement = "kg/m²"
        else:
            self._attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
        self._attr_extra_state_attributes = {"origin": "measured" if metric == "weight" else "calculated"}

    @property
    def _summary(self) -> dict[str, Any]:
        return self.runtime.user_summaries.get(self.user_id, self._user)

    @property
    def native_value(self) -> Any:
        mapping = {
            "weight": "current_weight_kg",
            "bmi": "bmi",
            "weight_trend": "trend_kg_per_day",
            "weight_change_7d": "change_7d_kg",
            "weight_change_30d": "change_30d_kg",
        }
        return self._summary.get(mapping[self.metric])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        summary = self._summary
        return {
            "origin": "measured" if self.metric == "weight" else "calculated",
            "user_id": self.user_id,
            "last_measured_at": summary.get("last_measured_at"),
            "target_weight_kg": summary.get("target_weight_kg"),
            "bmi_classification": summary.get("bmi_classification"),
            "frequency_per_week": summary.get("frequency_per_week"),
        }
