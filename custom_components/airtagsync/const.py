"""Constants for the AirTagSync integration."""

from __future__ import annotations

DOMAIN = "airtagsync"

# Config entry keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PRIVATE_KEY = "private_key"
CONF_FMIP_KEY_B64 = "fmip_key_b64"  # 32-byte FMIP symmetric key, base64-encoded
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_RADIUS_M = "radius_m"
CONF_SCAN_INTERVAL_S = "scan_interval_s"
CONF_INCLUDE_AUDIO = "include_audio_accessories"

DEFAULT_PORT = 22
DEFAULT_SCAN_INTERVAL_S = 30
DEFAULT_RADIUS_M = 100
DEFAULT_INCLUDE_AUDIO = False

# Remote path on the Mac — fixed by macOS, no need to make this configurable
REMOTE_ITEMS_DATA = "~/Library/Caches/com.apple.findmy.fmipcore/Items.data"

MANUFACTURER = "Apple"
MODEL_AIRTAG = "AirTag"
MODEL_AUDIO = "AirPods"
