"""Pure Xiaomi Mi Scale BLE decoder.

The decoder accepts Home Assistant Bluetooth service data and never opens a BLE
scanner. Xiaomi V1 (181d) and V2 (181b) advertisements are weight-first; body
composition fields are retained only when the scale broadcasts them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

from .const import UUID_V1, UUID_V2


@dataclass(frozen=True, slots=True)
class ParsedMeasurement:
    weight_kg: float
    original_unit: str
    measured_at: datetime
    stable: bool
    impedance: int | None
    protocol: str
    model: str | None
    mac_address: str
    rssi: int | None
    raw_payload: dict[str, Any]


def normalize_mac(address: str) -> str:
    """Return the canonical uppercase colon-separated MAC address."""

    compact = "".join(ch for ch in address.strip().upper() if ch.isalnum())
    if len(compact) != 12 or any(ch not in "0123456789ABCDEF" for ch in compact):
        raise ValueError("Invalid Bluetooth MAC address")
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


def _service_key(key: object) -> str:
    value = str(key).lower().strip()
    if value in {"181b", "0x181b"}:
        return UUID_V2
    if value in {"181d", "0x181d"}:
        return UUID_V1
    return value


def _as_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return bytes.fromhex(value.replace(" ", ""))
    raise ValueError("Unsupported BLE payload")


def _v1(payload: bytes) -> tuple[float, str, bool, int | None]:
    if len(payload) < 3:
        raise ValueError("Xiaomi V1 payload is shorter than 3 bytes")
    # V1 reports the unit in byte 0 and hundredths of the native unit in 1:3.
    unit_byte = payload[0]
    raw = int.from_bytes(payload[1:3], "little")
    if unit_byte & 0x03 == 0x03 or unit_byte & 0xA0 == 0xA0:
        unit, native_weight = "lbs", raw / 100
        weight_kg = native_weight * 0.45359237
    elif unit_byte & 0x12 == 0x12:
        unit, native_weight = "jin", raw / 100
        weight_kg = native_weight * 0.5
    else:
        unit, native_weight = "kg", raw / 200
        weight_kg = native_weight
    # V1 scale advertisements are final readings in the official protocol.
    stable = True
    return round(weight_kg, 3), unit, stable, None


def _v2(payload: bytes) -> tuple[float, str, bool, int | None]:
    if len(payload) < 13:
        raise ValueError("Xiaomi V2 payload is shorter than 13 bytes")
    # V2 layout: control byte at 1, unit at 0, weight at 11:13, impedance at 9:11.
    control = payload[1]
    unit_byte = payload[0]
    raw_weight = int.from_bytes(payload[11:13], "little")
    if unit_byte == 0x03:
        unit, weight_kg = "lbs", raw_weight * 0.01 * 0.45359237
    elif unit_byte == 0x02:
        unit, weight_kg = "kg", raw_weight * 0.005
    else:
        unit, weight_kg = "kg", raw_weight / 200
    has_impedance = bool(control & (1 << 1))
    impedance = int.from_bytes(payload[9:11], "little") if has_impedance else None
    return round(weight_kg, 3), unit, bool(control & (1 << 5)), impedance


def parse_service_info(service_info: Any, *, expected_mac: str | None = None) -> ParsedMeasurement | None:
    """Parse one HA Bluetooth service-info object.

    The function also accepts a small mapping in tests, with ``service_data``,
    ``address`` and optional ``rssi`` keys.
    """

    if isinstance(service_info, Mapping):
        service_data = service_info.get("service_data", {})
        address = str(service_info.get("address", ""))
        rssi = service_info.get("rssi")
        name = service_info.get("name")
    else:
        service_data = getattr(service_info, "service_data", {})
        address = str(getattr(service_info, "address", ""))
        rssi = getattr(service_info, "rssi", None)
        name = getattr(service_info, "name", None)
    try:
        mac = normalize_mac(address)
    except ValueError:
        return None
    if expected_mac and mac != normalize_mac(expected_mac):
        return None
    normalized = {_service_key(key): _as_bytes(value) for key, value in service_data.items()}
    selected = next((uuid for uuid in (UUID_V2, UUID_V1) if uuid in normalized), None)
    if not selected:
        return None
    payload = normalized[selected]
    weight_kg, unit, stable, impedance = _v2(payload) if selected == UUID_V2 else _v1(payload)
    if not 5 <= weight_kg <= 300:
        raise ValueError("Xiaomi weight is outside the supported physical range")
    return ParsedMeasurement(
        weight_kg=weight_kg,
        original_unit=unit,
        measured_at=datetime.now(UTC),
        stable=stable,
        impedance=impedance,
        protocol="xiaomi_v2" if selected == UUID_V2 else "xiaomi_v1",
        model=str(name) if name else None,
        mac_address=mac,
        rssi=int(rssi) if rssi is not None else None,
        raw_payload={"service_uuid": selected, "payload_hex": payload.hex()},
    )
