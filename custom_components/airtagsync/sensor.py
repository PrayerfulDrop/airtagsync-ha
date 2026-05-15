"""Battery status sensor per AirTag."""

from __future__ import annotations

import re

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL_AIRTAG, MODEL_AUDIO
from .coordinator import AirTagSyncCoordinator
from .decryptor import Item, battery_label

_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def _slug(s: str) -> str:
    s = s.lower().replace(" ", "_")
    return _SLUG_RE.sub("", s).strip("_") or "airtag"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback
) -> None:
    coordinator: AirTagSyncCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: dict[str, BatterySensor] = {}

    @callback
    def _sync() -> None:
        new: list[BatterySensor] = []
        for item in coordinator.data or []:
            if item.identifier in known:
                continue
            ent = BatterySensor(coordinator, item)
            known[item.identifier] = ent
            new.append(ent)
        if new:
            add(new)

    entry.async_on_unload(coordinator.async_add_listener(_sync))
    _sync()


class BatterySensor(CoordinatorEntity[AirTagSyncCoordinator], SensorEntity):
    """AirTag battery status — Apple reports a level enum, not percentage."""

    _attr_has_entity_name = True
    _attr_name = "Battery"
    _attr_icon = "mdi:battery"

    def __init__(self, coordinator: AirTagSyncCoordinator, item: Item) -> None:
        super().__init__(coordinator)
        self._identifier = item.identifier
        slug = _slug(item.name)
        self._attr_unique_id = f"airtag_{slug}_battery"
        self._fallback_name = item.name
        self._fallback_audio = item.is_audio_accessory
        self._fallback_sw = item.system_version

    @property
    def _item(self) -> Item | None:
        for it in self.coordinator.data or []:
            if it.identifier == self._identifier:
                return it
        return None

    @property
    def device_info(self) -> DeviceInfo:
        item = self._item
        name = item.name if item else self._fallback_name
        sw = (item.system_version if item else self._fallback_sw) or ""
        model = MODEL_AUDIO if (item.is_audio_accessory if item else self._fallback_audio) else MODEL_AIRTAG
        device_unique = f"airtag_{_slug(name)}"
        return DeviceInfo(
            identifiers={(DOMAIN, device_unique)},
            name=name,
            manufacturer=MANUFACTURER,
            model=model,
            sw_version=sw,
        )

    @property
    def native_value(self) -> str:
        item = self._item
        return battery_label(item.battery_status if item else None)
