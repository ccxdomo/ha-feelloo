"""Binary sensor platform for Feelloo."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FeellooMainCoordinator

_LOGGER = logging.getLogger(__name__)

BINARY_SENSOR_DEFINITIONS = {
    "home": ("mdi:home", None),
    "in_range": ("mdi:bluetooth", None),
    "gateway_online": (None, BinarySensorDeviceClass.CONNECTIVITY),
    "charging": (None, BinarySensorDeviceClass.BATTERY_CHARGING),
    "is_ringing": ("mdi:bell-ring", None),
    "battery_low": (None, BinarySensorDeviceClass.BATTERY),
    "extended_search": ("mdi:map-search", None),
}


def _bool_at(data: dict, *path: str) -> bool | None:
    """Safely walk a nested dict path and return a bool or None."""
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current if isinstance(current, bool) else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Feelloo binary sensors."""
    try:
        main_coordinator: FeellooMainCoordinator = hass.data[DOMAIN][entry.entry_id]["main"]
    except (KeyError, TypeError):
        _LOGGER.error("Main coordinator missing for entry %s", entry.entry_id)
        return

    entities = []
    seen_ids: set[str] = set()

    for cat in main_coordinator.cats or []:
        if not isinstance(cat, dict):
            continue
        cat_uid = cat.get("_id")
        name = (cat.get("profile") or {}).get("name", "Unknown")
        if not isinstance(cat_uid, str) or not cat_uid:
            _LOGGER.debug("Skipping cat with invalid _id")
            continue
        for key, (icon, device_class) in BINARY_SENSOR_DEFINITIONS.items():
            unique_id = f"{cat_uid}_{key}"
            if unique_id in seen_ids:
                _LOGGER.warning("Duplicate unique_id %s, skipping", unique_id)
                continue
            seen_ids.add(unique_id)
            entities.append(
                FeellooBinarySensor(main_coordinator, cat_uid, name, key, icon, device_class)
            )
    async_add_entities(entities)


class FeellooBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Feelloo binary sensor."""

    def __init__(
        self,
        coordinator: FeellooMainCoordinator,
        cat_uid: str,
        cat_name: str,
        key: str,
        icon: str | None,
        device_class: BinarySensorDeviceClass | None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._cat_uid = cat_uid
        self._key = key
        self._attr_unique_id = f"{cat_uid}_{key}"
        self._attr_translation_key = key
        self._attr_has_entity_name = True
        if device_class:
            self._attr_device_class = device_class
        if icon:
            self._attr_icon = icon
        self._attr_device_info = {
            "identifiers": {(DOMAIN, cat_uid)},
            "name": cat_name,
            "manufacturer": "Feelloo",
            "model": "Cat Tracker",
        }

    def _get_cat(self) -> dict | None:
        """Get the cat data from coordinator."""
        if self.coordinator.cats is None:
            return None
        for cat in self.coordinator.cats:
            if isinstance(cat, dict) and cat.get("_id") == self._cat_uid:
                return cat
        return None

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        cat = self._get_cat()
        if not cat:
            return None
        if self._key == "home":
            return _bool_at(cat, "presence", "status", "home")
        if self._key == "in_range":
            return _bool_at(cat, "presence", "status", "in_range")
        if self._key == "gateway_online":
            return _bool_at(cat, "gateway", "online")
        if self._key == "charging":
            return _bool_at(cat, "gateway", "tag", "status", "charging")
        if self._key == "is_ringing":
            return _bool_at(cat, "gateway", "tag", "status", "is_ringing")
        if self._key == "battery_low":
            return _bool_at(cat, "gateway", "tag", "display_battery_low_warning")
        if self._key == "extended_search":
            return _bool_at(cat, "gateway", "tag", "extended_search", "enabled")
        return False

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self._get_cat() is not None
