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
from .coordinator import FeellooMainCoordinator

BINARY_SENSOR_DEFINITIONS = {
    "home": ("mdi:home", None),
    "in_range": ("mdi:bluetooth", None),
    "gateway_online": (None, BinarySensorDeviceClass.CONNECTIVITY),
    "charging": (None, BinarySensorDeviceClass.BATTERY_CHARGING),
    "is_ringing": ("mdi:bell-ring", None),
    "battery_low": (None, BinarySensorDeviceClass.BATTERY),
    "extended_search": ("mdi:map-search", None),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Feelloo binary sensors."""
    main_coordinator: FeellooMainCoordinator = hass.data[DOMAIN][entry.entry_id]["main"]
    entities = []
    for cat in main_coordinator.cats:
        cat_uid = cat.get("_id")
        name = cat.get("profile", {}).get("name", "Unknown")
        if not cat_uid:
            continue
        for key, (icon, device_class) in BINARY_SENSOR_DEFINITIONS.items():
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
        for cat in self.coordinator.cats:
            if cat.get("_id") == self._cat_uid:
                return cat
        return None

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        cat = self._get_cat()
        if not cat:
            return None
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
