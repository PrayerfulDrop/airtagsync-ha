"""DataUpdateCoordinator: SSH to Mac, fetch Items.data, decrypt."""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import timedelta
from typing import Any

import asyncssh

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_FMIP_KEY_B64, CONF_HOST, CONF_INCLUDE_AUDIO, CONF_PORT,
    CONF_PRIVATE_KEY, CONF_SCAN_INTERVAL_S, CONF_USERNAME,
    DEFAULT_INCLUDE_AUDIO, DEFAULT_PORT, DEFAULT_SCAN_INTERVAL_S,
    DOMAIN, REMOTE_ITEMS_DATA,
)
from .decryptor import Item, decrypt_items_data, parse_items

_LOGGER = logging.getLogger(__name__)


class AirTagSyncCoordinator(DataUpdateCoordinator[list[Item]]):
    """Polls the Mac via SSH and exposes decrypted AirTag items to HA entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=entry.data.get(CONF_SCAN_INTERVAL_S, DEFAULT_SCAN_INTERVAL_S)),
        )
        self.entry = entry
        # Decode the FMIP key once
        import base64
        self._fmip_key = base64.b64decode(entry.data[CONF_FMIP_KEY_B64])
        self._include_audio = entry.data.get(CONF_INCLUDE_AUDIO, DEFAULT_INCLUDE_AUDIO)

    async def _async_update_data(self) -> list[Item]:
        host = self.entry.data[CONF_HOST]
        port = self.entry.data.get(CONF_PORT, DEFAULT_PORT)
        user = self.entry.data[CONF_USERNAME]
        private_key_pem = self.entry.data[CONF_PRIVATE_KEY]

        try:
            blob = await asyncio.wait_for(
                _fetch_items_data(host, port, user, private_key_pem),
                timeout=20,
            )
        except (asyncssh.Error, asyncio.TimeoutError, OSError) as err:
            raise UpdateFailed(f"SSH fetch failed: {err}") from err

        try:
            raw = decrypt_items_data(blob, self._fmip_key)
        except Exception as err:
            raise UpdateFailed(f"Decrypt failed: {err}") from err

        return parse_items(raw, include_audio=self._include_audio)


async def _fetch_items_data(host: str, port: int, user: str, private_key_pem: str) -> bytes:
    """SSH to host, run the restricted `cat Items.data` command, return raw bytes."""
    key = asyncssh.import_private_key(private_key_pem)
    async with asyncssh.connect(
        host,
        port=port,
        username=user,
        client_keys=[key],
        known_hosts=None,  # we don't pin hosts; key auth is the trust anchor
    ) as conn:
        proc = await conn.run(f"cat {REMOTE_ITEMS_DATA}", encoding=None, check=True)
        return proc.stdout  # bytes
