"""Sensor platform for Feelloo."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FeellooCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Feelloo sensors."""
    coordinator: FeellooCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for cat in coordinator.cats:
        cat_uid = cat.get("_id")
        name = cat.get("profile", {}).get("name", "Unknown")
        if not cat_uid:
            continue
        entities.extend([
            FeellooBatterySensor(coordinator, cat_uid, name),
            FeellooLatitudeSensor(coordinator, cat_uid, name),
            FeellooLongitudeSensor(coordinator, cat_uid, name),
            FeellooGpsPrecisionSensor(coordinator, cat_uid, name),
            FeellooLastSeenSensor(coordinator, cat_uid, name),
            FeellooPresenceTimeSensor(coordinator, cat_uid, name),
            FeellooActivitySensor(coordinator, cat_uid, name),
            FeellooExtendedSearchExpirationSensor(coordinator, cat_uid, name),
        ])
    async_add_entities(entities)


class FeellooSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Feelloo sensors."""

    def __init__(
        self,
        coordinator: FeellooCoordinator,
        cat_uid: str,
        cat_name: str,
        key: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._cat_uid = cat_uid
        self._cat_name = cat_name
        self._key = key
        self._attr_unique_id = f"{cat_uid}_{key}"
        self._attr_translation_key = key
        self._attr_has_entity_name = True
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
    def available(self) -> bool:
        """Return if entity is available."""
        return self._get_cat() is not None


class FeellooBatterySensor(FeellooSensorBase):
    """Battery level sensor."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "battery")

    @property
    def native_value(self):
        cat = self._get_cat()
        if not cat:
            return None
        return cat.get("gateway", {}).get("tag", {}).get("status", {}).get("battery_level")


class FeellooLatitudeSensor(FeellooSensorBase):
    """Latitude sensor."""

    _attr_icon = "mdi:latitude"

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "latitude")

    @property
    def native_value(self):
        cat = self._get_cat()
        if not cat:
            return None
        return cat.get("geolocation", {}).get("last_geolocation", {}).get("latitude")


class FeellooLongitudeSensor(FeellooSensorBase):
    """Longitude sensor."""

    _attr_icon = "mdi:longitude"

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "longitude")

    @property
    def native_value(self):
        cat = self._get_cat()
        if not cat:
            return None
        return cat.get("geolocation", {}).get("last_geolocation", {}).get("longitude")


class FeellooGpsPrecisionSensor(FeellooSensorBase):
    """GPS precision sensor."""

    _attr_native_unit_of_measurement = "m"
    _attr_icon = "mdi:crosshairs-gps"

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "gps_precision")

    @property
    def native_value(self):
        cat = self._get_cat()
        if not cat:
            return None
        return cat.get("geolocation", {}).get("last_geolocation", {}).get("precision_meter")


class FeellooLastSeenSensor(FeellooSensorBase):
    """Last seen timestamp sensor."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "last_seen")

    @property
    def native_value(self):
        cat = self._get_cat()
        if not cat:
            return None
        ts = cat.get("geolocation", {}).get("last_geolocation", {}).get("date_time")
        if ts:
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None


class FeellooPresenceTimeSensor(FeellooSensorBase):
    """Presence indication time sensor."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "presence_time")

    @property
    def native_value(self):
        cat = self._get_cat()
        if not cat:
            return None
        ts = cat.get("presence", {}).get("status", {}).get("presence_indication_time")
        if ts:
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None


class FeellooActivitySensor(FeellooSensorBase):
    """Activity sensor."""

    _attr_icon = "mdi:run"

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "activity")

    @property
    def native_value(self):
        cat = self._get_cat()
        if not cat:
            return None
        activity = cat.get("_activity", {})
        if activity is None:
            return None
        return activity.get("activity", activity.get("status"))


class FeellooExtendedSearchExpirationSensor(FeellooSensorBase):
    """Extended search expiration sensor."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "extended_search_expiration")

    @property
    def native_value(self):
        cat = self._get_cat()
        if not cat:
            return None
        ts = cat.get("gateway", {}).get("tag", {}).get("extended_search", {}).get("expiration_date")
        if ts and ts != "1970-01-01T00:00:00.000Z":
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None
