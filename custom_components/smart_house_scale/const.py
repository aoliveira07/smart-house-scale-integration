"""Constants for Smart House Scale."""

from __future__ import annotations

DOMAIN = "smart_house_scale"
NAME = "Smart House Scale"
VERSION = "0.1.7"

CONF_API_URL = "api_url"
CONF_API_TOKEN = "api_token"
CONF_MAC_ADDRESS = "mac_address"
CONF_DEVICE_NAME = "device_name"
CONF_SESSION_WINDOW = "session_window_seconds"

DEFAULT_API_URL = "http://192.168.0.201"
DEFAULT_SESSION_WINDOW = 30

UUID_V1 = "0000181d-0000-1000-8000-00805f9b34fb"
UUID_V2 = "0000181b-0000-1000-8000-00805f9b34fb"
SUPPORTED_UUIDS = (UUID_V1, UUID_V2)

STATUS_ASSIGNED = "assigned"
STATUS_PENDING = "pending"
STATUS_DISCARDED = "discarded"

SIGNAL_UPDATE = f"{DOMAIN}_update"
