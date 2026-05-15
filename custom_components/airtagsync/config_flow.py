"""Config flow for AirTagSync."""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_FMIP_KEY_B64, CONF_HOST, CONF_INCLUDE_AUDIO, CONF_LATITUDE,
    CONF_LONGITUDE, CONF_PORT, CONF_PRIVATE_KEY, CONF_RADIUS_M,
    CONF_SCAN_INTERVAL_S, CONF_USERNAME, DEFAULT_INCLUDE_AUDIO, DEFAULT_PORT,
    DEFAULT_RADIUS_M, DEFAULT_SCAN_INTERVAL_S, DOMAIN, REMOTE_ITEMS_DATA,
)
from .decryptor import decrypt_items_data, extract_fmip_key, parse_items

_LOGGER = logging.getLogger(__name__)


def _build_schema() -> vol.Schema:
    """Build the form schema. Kept as a function so it's cheap to re-render on errors."""
    return vol.Schema({
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PRIVATE_KEY): selector.TextSelector(
            selector.TextSelectorConfig(multiline=True)
        ),
        vol.Required("fmip_key_b64_or_bplist"): selector.TextSelector(
            selector.TextSelectorConfig(multiline=True)
        ),
        vol.Required(CONF_LATITUDE): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=-90, max=90, step=0.000001,
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Required(CONF_LONGITUDE): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=-180, max=180, step=0.000001,
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Required(CONF_RADIUS_M, default=DEFAULT_RADIUS_M): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=10, max=10000, step=1,
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="m",
            )
        ),
        vol.Optional(CONF_SCAN_INTERVAL_S, default=DEFAULT_SCAN_INTERVAL_S): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=10, max=600, step=5,
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="s",
            )
        ),
        vol.Optional(CONF_INCLUDE_AUDIO, default=DEFAULT_INCLUDE_AUDIO): bool,
    })


async def _validate_ssh_and_decrypt(user_input: dict[str, Any], fmip_key: bytes) -> int:
    """End-to-end validation: SSH+fetch+decrypt+parse. Returns item count.

    asyncssh import is deferred to here so the module loads even before
    HA finishes pip-installing requirements.
    """
    import asyncssh  # deferred — installed on first integration add

    private_key = asyncssh.import_private_key(user_input[CONF_PRIVATE_KEY])
    async with asyncssh.connect(
        user_input[CONF_HOST],
        port=user_input.get(CONF_PORT, DEFAULT_PORT),
        username=user_input[CONF_USERNAME],
        client_keys=[private_key],
        known_hosts=None,
    ) as conn:
        proc = await asyncio.wait_for(
            conn.run(f"cat {REMOTE_ITEMS_DATA}", encoding=None, check=True),
            timeout=15,
        )

    raw = decrypt_items_data(proc.stdout, fmip_key)
    items = parse_items(raw, include_audio=user_input.get(CONF_INCLUDE_AUDIO, DEFAULT_INCLUDE_AUDIO))
    return len(items)


def _parse_fmip_key(text: str) -> bytes:
    """Accept either base64'd raw 32-byte key OR base64'd FMIPDataManager.bplist."""
    blob = base64.b64decode(text.strip(), validate=False)
    if len(blob) == 32:
        return blob
    # otherwise treat as bplist
    return extract_fmip_key(blob)


class AirTagSyncConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single-step config flow with end-to-end validation."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            fmip_key: bytes | None = None
            try:
                fmip_key = _parse_fmip_key(user_input["fmip_key_b64_or_bplist"])
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("FMIP key parse error: %s", err)
                errors["fmip_key_b64_or_bplist"] = "invalid_fmip_key"

            if fmip_key is not None:
                try:
                    item_count = await _validate_ssh_and_decrypt(user_input, fmip_key)
                except asyncio.TimeoutError:
                    errors["base"] = "ssh_connect_failed"
                except ValueError as err:
                    _LOGGER.warning("Decrypt error: %s", err)
                    errors["base"] = "decrypt_failed"
                except Exception as err:  # noqa: BLE001
                    # asyncssh.PermissionDenied / ConnectionLost / OSError / etc.
                    cls = type(err).__name__
                    _LOGGER.warning("SSH/validation error (%s): %s", cls, err)
                    if "Permission" in cls or "auth" in str(err).lower():
                        errors["base"] = "ssh_auth_failed"
                    else:
                        errors["base"] = "ssh_connect_failed"
                else:
                    await self.async_set_unique_id(f"{user_input[CONF_USERNAME]}@{user_input[CONF_HOST]}")
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"AirTagSync ({user_input[CONF_HOST]}) — {item_count} items",
                        data={
                            CONF_HOST: user_input[CONF_HOST],
                            CONF_PORT: user_input.get(CONF_PORT, DEFAULT_PORT),
                            CONF_USERNAME: user_input[CONF_USERNAME],
                            CONF_PRIVATE_KEY: user_input[CONF_PRIVATE_KEY],
                            CONF_FMIP_KEY_B64: base64.b64encode(fmip_key).decode("ascii"),
                            CONF_LATITUDE: user_input[CONF_LATITUDE],
                            CONF_LONGITUDE: user_input[CONF_LONGITUDE],
                            CONF_RADIUS_M: user_input.get(CONF_RADIUS_M, DEFAULT_RADIUS_M),
                            CONF_SCAN_INTERVAL_S: user_input.get(CONF_SCAN_INTERVAL_S, DEFAULT_SCAN_INTERVAL_S),
                            CONF_INCLUDE_AUDIO: user_input.get(CONF_INCLUDE_AUDIO, DEFAULT_INCLUDE_AUDIO),
                        },
                    )

        return self.async_show_form(step_id="user", data_schema=_build_schema(), errors=errors)
