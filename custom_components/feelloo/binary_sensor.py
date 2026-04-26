"""Binary sensor platform for Feelloo."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FeellooCoordinator

BINARY_SENSORS = [
    ("home", "presence", "status", "home", None, "mdi:home"),
    ("in_range", "presence", "status", "in_range", None, "mdi:bluetooth"),
    ("gateway_online", "gateway", "online", None, BinarySensorDeviceClass.CONNECTIVITY, None),
    ("charging", "gateway", "tag", "status", "charging", BinarySensorDeviceClass.BATTERY_CHARGING, None),
    ("is_ringing", "gateway", "tag", "status", "is_ringing", None, "mdi:bell-ring"),
    ("battery_low", "gateway", "tag", "display_battery_low_warning", None, BinarySensorDeviceClass.BATTERY, None),
    ("extended_search", "gateway", "tag", "extended_search", "enabled", None, "mdi:map-search"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Feelloo binary sensors."""
    coordinator: FeellooCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for cat in coordinator.cats:
        cat_uid = cat.get("_id")
        name = cat.get("profile", {}).get("name", "Unknown")
        if not cat_uid:
            continue
        for key, *path in BINARY_SENSORS:
            entities.append(
                FeellooBinarySensor(coordinator, cat_uid, name, key, path)
            )
    async_add_entities(entities)


class FeellooBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Feelloo binary sensor."""

    def __init__(
        self,
        coordinator: FeellooCoordinator,
        cat_uid: str,
        cat_name: str,
        key: str,
        path: tuple,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._cat_uid = cat_uid
        self._cat_name = cat_name
        self._key = key
        self._path = path
        self._attr_unique_id = f"{cat_uid}_{key}"
        self._attr_translation_key = key
        self._attr_has_entity_name = True

        device_class = path[-2] if len(path) >= 2 and isinstance(path[-2], BinarySensorDeviceClass) else None
        icon = path[-1] if path and isinstance(path[-1], str) else None

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
        for cat in self.coordinator.cats:
            if cat.get("_id") == self._cat_uid:
                return cat
        return None

    def _get_value(self, data: dict, path: tuple) -> bool:
        """Navigate nested dict and return boolean value."""
        try:
            for key in path:
                if key is None:
                    continue
                if isinstance(key, str):
                    data = data[key]
                else:
                    data = key  # Should not happen
            return bool(data)
        except (KeyError, TypeError):
            return False

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        cat = self._get_cat()
        if not cat:
            return None
        # Build the actual path, filtering out None and device_class/icon
        actual_path = tuple(p for p in self._path if p is not None and not isinstance(p, (BinarySensorDeviceClass, str)))
        # For paths with nested access like ("gateway", "tag", "status", "charging")
        # We need to handle the structure correctly
        if self._key == "home":
            return cat.get("presence", {}).get("status", {}).get("home", False)
        if self._key == "in_range":
            return cat.get("presence", {}).get("status", {}).get("in_range", False)
        if self._key == "gateway_online":
            return cat.get("gateway", {}).get("online", False)
        if self._key == "charging":
            return cat.get("gateway", {}).get("tag", {}).get("status", {}).get("charging", False)
        if self._key == "is_ringing":
            return cat.get("gateway", {}).get("tag", {}).get("status", {}).get("is_ringing", False)
        if self._key == "battery_low":
            return cat.get("gateway", {}).get("tag", {}).get("display_battery_low_warning", False)
        if self._key == "extended_search":
            return cat.get("gateway", {}).get("tag", {}).get("extended_search", {}).get("enabled", False)
        return False

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._get_cat() is not None
