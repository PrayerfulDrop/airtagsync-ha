"""AirTag device_tracker entities."""

from __future__ import annotations

import re

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_LATITUDE, CONF_LONGITUDE, CONF_RADIUS_M, DOMAIN, MANUFACTURER,
    MODEL_AIRTAG, MODEL_AUDIO,
)
from .coordinator import AirTagSyncCoordinator
from .decryptor import Item, haversine_m

_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def _slug(s: str) -> str:
    s = s.lower().replace(" ", "_")
    return _SLUG_RE.sub("", s).strip("_") or "airtag"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback
) -> None:
    coordinator: AirTagSyncCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: dict[str, AirTagTracker] = {}

    @callback
    def _sync() -> None:
        new_entities: list[AirTagTracker] = []
        for item in coordinator.data or []:
            if item.identifier in known:
                continue
            ent = AirTagTracker(coordinator, item, entry)
            known[item.identifier] = ent
            new_entities.append(ent)
        if new_entities:
            add(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_sync))
    _sync()


class AirTagTracker(CoordinatorEntity[AirTagSyncCoordinator], TrackerEntity):
    """A FindMy item exposed as a device_tracker.gps entity."""

    _attr_has_entity_name = True
    _attr_name = None  # use device name

    def __init__(self, coordinator: AirTagSyncCoordinator, item: Item, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._identifier = item.identifier
        self._attr_unique_id = f"airtag_{_slug(item.name)}"
        self._entry = entry
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
        return DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=name,
            manufacturer=MANUFACTURER,
            model=model,
            sw_version=sw,
        )

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        return self._item.location.latitude if self._item and self._item.location else None

    @property
    def longitude(self) -> float | None:
        return self._item.location.longitude if self._item and self._item.location else None

    @property
    def location_accuracy(self) -> int:
        loc = self._item.location if self._item else None
        return int(loc.horizontal_accuracy) if loc else 0

    @property
    def location_name(self) -> str | None:
        # Returning None lets HA's zone matching fall through. We also expose
        # home/not_home explicitly via the integration's home radius config —
        # but HA already does zone matching itself when we provide lat/lon, so
        # we just hint via location_name only if our radius classifies as home.
        item = self._item
        if not item or not item.location:
            return None
        d = haversine_m(
            item.location.latitude, item.location.longitude,
            self._entry.data[CONF_LATITUDE], self._entry.data[CONF_LONGITUDE],
        )
        if d <= self._entry.data[CONF_RADIUS_M]:
            return "home"
        return None  # let HA's zone resolver decide

    @property
    def extra_state_attributes(self) -> dict:
        item = self._item
        attrs: dict = {"airtag_id": self._identifier}
        if item and item.location:
            attrs["last_seen_ms"] = item.location.timestamp_ms
            if item.location.altitude is not None:
                attrs["altitude"] = item.location.altitude
        if item and item.serial_number:
            attrs["serial_number"] = item.serial_number
        return attrs
