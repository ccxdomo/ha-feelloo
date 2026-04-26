"""Sensor platform for Feelloo."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FeellooMainCoordinator, FeellooActivityCoordinator, FeellooTerritoryCoordinator, FeellooSessionCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Feelloo sensors."""
    main: FeellooMainCoordinator = hass.data[DOMAIN][entry.entry_id]["main"]
    activity: FeellooActivityCoordinator = hass.data[DOMAIN][entry.entry_id]["activity"]
    territory: FeellooTerritoryCoordinator = hass.data[DOMAIN][entry.entry_id]["territory"]
    session: FeellooSessionCoordinator = hass.data[DOMAIN][entry.entry_id]["session"]

    entities = []
    for cat in main.cats:
        cat_uid = cat.get("_id")
        name = cat.get("profile", {}).get("name", "Unknown")
        if not cat_uid:
            continue
        entities.extend([
            FeellooBatterySensor(main, cat_uid, name),
            FeellooLatitudeSensor(main, cat_uid, name),
            FeellooLongitudeSensor(main, cat_uid, name),
            FeellooGpsPrecisionSensor(main, cat_uid, name),
            FeellooLastSeenSensor(main, cat_uid, name),
            FeellooPresenceTimeSensor(main, cat_uid, name),
            FeellooActivitySensor(main, activity, cat_uid, name),
            FeellooActivityRestSensor(activity, cat_uid, name),
            FeellooActivityCalmSensor(activity, cat_uid, name),
            FeellooActivityActionSensor(activity, cat_uid, name),
            FeellooExtendedSearchExpirationSensor(main, cat_uid, name),
            FeellooLastOutingStartSensor(territory, cat_uid, name),
            FeellooLastOutingEndSensor(territory, cat_uid, name),
            FeellooOutingCountSensor(territory, cat_uid, name),
            FeellooLastSessionDurationSensor(session, cat_uid, name),
            FeellooLastSessionPointsCountSensor(session, cat_uid, name),
            FeellooLastSessionStartSensor(session, cat_uid, name),
            FeellooLastSessionEndSensor(session, cat_uid, name),
        ])
    async_add_entities(entities)


class FeellooSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Feelloo sensors tied to main coordinator."""

    def __init__(
        self,
        coordinator: FeellooMainCoordinator,
        cat_uid: str,
        cat_name: str,
        key: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._cat_uid = cat_uid
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
    """Activity sensor — legacy combined activity."""

    _attr_icon = "mdi:run"

    def __init__(self, main_coordinator, activity_coordinator, cat_uid, cat_name):
        super().__init__(main_coordinator, cat_uid, cat_name, "activity")
        self._activity_coordinator = activity_coordinator

    @property
    def native_value(self):
        cat = self._get_cat()
        if not cat:
            return None
        activity = self._activity_coordinator.get_activity(self._cat_uid)
        if not activity:
            return None
        # Return most dominant activity from average
        avg = activity.get("average", {})
        rest = avg.get("rest_percentage", 0)
        calm = avg.get("calm_percentage", 0)
        action = avg.get("action_percentage", 0)
        if action >= calm and action >= rest:
            return "active"
        if calm >= rest:
            return "calm"
        return "sleep"

    @property
    def extra_state_attributes(self):
        """Return extra attributes with full history."""
        activity = self._activity_coordinator.get_activity(self._cat_uid)
        if not activity:
            return {}
        return {
            "history": activity.get("history", []),
        }


class FeellooActivityBaseSensor(CoordinatorEntity, SensorEntity):
    """Base for activity percentage sensors."""

    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FeellooActivityCoordinator,
        cat_uid: str,
        cat_name: str,
        key: str,
        icon: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._cat_uid = cat_uid
        self._key = key
        self._attr_unique_id = f"{cat_uid}_{key}"
        self._attr_translation_key = key
        self._attr_icon = icon
        self._attr_device_info = {
            "identifiers": {(DOMAIN, cat_uid)},
            "name": cat_name,
            "manufacturer": "Feelloo",
            "model": "Cat Tracker",
        }

    def _get_activity(self) -> dict | None:
        """Get activity data for this cat."""
        return self.coordinator.get_activity(self._cat_uid)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._get_activity() is not None


class FeellooActivityRestSensor(FeellooActivityBaseSensor):
    """Activity rest percentage sensor."""

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "activity_rest", "mdi:sleep")

    @property
    def native_value(self):
        activity = self._get_activity()
        if not activity:
            return None
        return activity.get("average", {}).get("rest_percentage")

    @property
    def extra_state_attributes(self):
        """Return full history as attribute."""
        activity = self._get_activity()
        if not activity:
            return {}
        return {
            "history": activity.get("history", []),
        }


class FeellooActivityCalmSensor(FeellooActivityBaseSensor):
    """Activity calm percentage sensor."""

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "activity_calm", "mdi:cat")

    @property
    def native_value(self):
        activity = self._get_activity()
        if not activity:
            return None
        return activity.get("average", {}).get("calm_percentage")


class FeellooActivityActionSensor(FeellooActivityBaseSensor):
    """Activity action percentage sensor."""

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "activity_action", "mdi:run")

    @property
    def native_value(self):
        activity = self._get_activity()
        if not activity:
            return None
        return activity.get("average", {}).get("action_percentage")


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


class FeellooTerritoryBaseSensor(CoordinatorEntity, SensorEntity):
    """Base for territory sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FeellooTerritoryCoordinator,
        cat_uid: str,
        cat_name: str,
        key: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._cat_uid = cat_uid
        self._key = key
        self._attr_unique_id = f"{cat_uid}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = {
            "identifiers": {(DOMAIN, cat_uid)},
            "name": cat_name,
            "manufacturer": "Feelloo",
            "model": "Cat Tracker",
        }

    def _get_last_session(self) -> dict | None:
        """Get the most recent territory session."""
        return self.coordinator.get_last_session(self._cat_uid)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._get_last_session() is not None


class FeellooLastOutingStartSensor(FeellooTerritoryBaseSensor):
    """Timestamp of last outing start."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "last_outing_start")

    @property
    def native_value(self):
        session = self._get_last_session()
        if not session:
            return None
        ts = session.get("start_date")
        if ts:
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None


class FeellooLastOutingEndSensor(FeellooTerritoryBaseSensor):
    """Timestamp of last outing end."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "last_outing_end")

    @property
    def native_value(self):
        session = self._get_last_session()
        if not session:
            return None
        ts = session.get("end_date")
        if ts:
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None


class FeellooOutingCountSensor(FeellooTerritoryBaseSensor):
    """Total number of territory sessions."""

    _attr_icon = "mdi:map-marker-path"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "outing_count")

    @property
    def native_value(self):
        paths = self.coordinator.get_paths(self._cat_uid)
        return len(paths) if paths else 0

    @property
    def available(self) -> bool:
        """Available if we have paths data."""
        paths = self.coordinator.get_paths(self._cat_uid)
        return paths is not None


class FeellooSessionBaseSensor(CoordinatorEntity, SensorEntity):
    """Base for session detail sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FeellooSessionCoordinator,
        cat_uid: str,
        cat_name: str,
        key: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._cat_uid = cat_uid
        self._key = key
        self._attr_unique_id = f"{cat_uid}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = {
            "identifiers": {(DOMAIN, cat_uid)},
            "name": cat_name,
            "manufacturer": "Feelloo",
            "model": "Cat Tracker",
        }

    def _get_session(self) -> dict | None:
        """Get the session detail for this cat."""
        return self.coordinator.get_session(self._cat_uid)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._get_session() is not None


class FeellooLastSessionDurationSensor(FeellooSessionBaseSensor):
    """Duration in minutes of the last territory session."""

    _attr_icon = "mdi:timer"
    _attr_native_unit_of_measurement = "min"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "last_session_duration")

    @property
    def native_value(self):
        session = self._get_session()
        if not session:
            return None
        start = session.get("start_date")
        end = session.get("end_date")
        if not start or not end:
            return None
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            return int((end_dt - start_dt).total_seconds() / 60)
        except (ValueError, TypeError):
            return None


class FeellooLastSessionPointsCountSensor(FeellooSessionBaseSensor):
    """Number of GPS points in the last territory session."""

    _attr_icon = "mdi:map-marker-multiple"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "last_session_points_count")

    @property
    def native_value(self):
        session = self._get_session()
        if not session:
            return None
        points = session.get("points", [])
        return len(points) if points else 0

    @property
    def extra_state_attributes(self):
        """Return session points as attributes."""
        session = self._get_session()
        if not session:
            return {}
        points = session.get("points", [])
        return {
            "points": [
                {
                    "latitude": p.get("geolocation", {}).get("latitude"),
                    "longitude": p.get("geolocation", {}).get("longitude"),
                    "precision_meter": p.get("geolocation", {}).get("precision_meter"),
                    "source": p.get("geolocation", {}).get("source"),
                    "date_time": p.get("date_time"),
                }
                for p in points
            ],
            "session_id": session.get("session_id"),
        }


class FeellooLastSessionStartSensor(FeellooSessionBaseSensor):
    """Timestamp of last territory session start."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "last_session_start")

    @property
    def native_value(self):
        session = self._get_session()
        if not session:
            return None
        ts = session.get("start_date")
        if ts:
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None


class FeellooLastSessionEndSensor(FeellooSessionBaseSensor):
    """Timestamp of last territory session end."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "last_session_end")

    @property
    def native_value(self):
        session = self._get_session()
        if not session:
            return None
        ts = session.get("end_date")
        if ts:
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None
