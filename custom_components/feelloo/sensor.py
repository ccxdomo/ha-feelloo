"""Sensor platform for Feelloo."""

from __future__ import annotations

import logging
import math
from datetime import datetime

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FeellooMainCoordinator, FeellooActivityCoordinator, FeellooTerritoryCoordinator, FeellooSessionCoordinator, FeellooActivityWeekCoordinator, FeellooActivityMonthCoordinator

_LOGGER = logging.getLogger(__name__)


def _parse_timestamp(ts):
    """Parse a timestamp string, rejecting naïve datetimes."""
    if not isinstance(ts, str):
        _LOGGER.debug("Rejecting non-string timestamp: %r", ts)
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        _LOGGER.debug("Rejecting malformed timestamp: %r", ts)
        return None
    if dt.tzinfo is None:
        _LOGGER.debug("Rejecting naïve datetime (no timezone): %r", ts)
        return None
    return dt


def _clamp(value, min_val, max_val, name, log_prefix):
    """Clamp a numeric value to a range, logging rejections."""
    if value is None:
        return None
    if isinstance(value, bool):
        _LOGGER.debug("%s: rejecting boolean %s: %r", log_prefix, name, value)
        return None
    if isinstance(value, str):
        try:
            value = float(value)
        except (ValueError, TypeError):
            _LOGGER.debug("%s: rejecting non-numeric %s: %r", log_prefix, name, value)
            return None
    if not isinstance(value, (int, float)):
        _LOGGER.debug("%s: rejecting non-numeric %s: %r", log_prefix, name, value)
        return None
    if not math.isfinite(value):
        _LOGGER.debug("%s: rejecting non-finite %s: %r", log_prefix, name, value)
        return None
    if min_val is not None and value < min_val:
        _LOGGER.debug("%s: rejecting %s below min (%s < %s): %r", log_prefix, name, value, min_val, value)
        return None
    if max_val is not None and value > max_val:
        _LOGGER.debug("%s: rejecting %s above max (%s > %s): %r", log_prefix, name, value, max_val, value)
        return None
    return value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Feelloo sensors."""
    try:
        main: FeellooMainCoordinator = hass.data[DOMAIN][entry.entry_id]["main"]
    except (KeyError, TypeError) as exc:
        _LOGGER.error("Main coordinator missing for entry %s: %s", entry.entry_id, exc)
        return

    coordinators = {}
    for key in ["activity", "activity_week", "activity_month", "territory", "session"]:
        try:
            coordinators[key] = hass.data[DOMAIN][entry.entry_id][key]
        except (KeyError, TypeError):
            _LOGGER.warning("Coordinator %s not available for entry %s", key, entry.entry_id)
            coordinators[key] = None

    if main.cats is None:
        _LOGGER.warning("No cats data available for entry %s, skipping sensor setup", entry.entry_id)
        return

    entities = []
    seen_ids: set[str] = set()

    for cat in main.cats:
        cat_uid = cat.get("_id")
        name = (cat.get("profile") or {}).get("name", "Unknown")
        if not cat_uid:
            _LOGGER.debug("Skipping cat with missing _id")
            continue

        sensors = []
        sensors.extend([
            FeellooBatterySensor(main, cat_uid, name),
            FeellooLatitudeSensor(main, cat_uid, name),
            FeellooLongitudeSensor(main, cat_uid, name),
            FeellooGpsPrecisionSensor(main, cat_uid, name),
            FeellooLastSeenSensor(main, cat_uid, name),
            FeellooPresenceTimeSensor(main, cat_uid, name),
            FeellooExtendedSearchExpirationSensor(main, cat_uid, name),
            FeellooSignalStrengthSensor(main, cat_uid, name),
        ])
        
        activity = coordinators.get("activity")
        if activity:
            sensors.extend([
                FeellooActivitySensor(activity, cat_uid, name),
                FeellooActivityRestSensor(activity, cat_uid, name),
                FeellooActivityCalmSensor(activity, cat_uid, name),
                FeellooActivityActionSensor(activity, cat_uid, name),
            ])
        
        territory = coordinators.get("territory")
        if territory:
            sensors.extend([
                FeellooLastOutingStartSensor(territory, cat_uid, name),
                FeellooLastOutingEndSensor(territory, cat_uid, name),
                FeellooOutingCountSensor(territory, cat_uid, name),
            ])
        
        session = coordinators.get("session")
        if session:
            sensors.extend([
                FeellooLastSessionDurationSensor(session, cat_uid, name),
                FeellooLastSessionPointsCountSensor(session, cat_uid, name),
                FeellooLastSessionStartSensor(session, cat_uid, name),
                FeellooLastSessionEndSensor(session, cat_uid, name),
            ])
        
        activity_week = coordinators.get("activity_week")
        if activity_week:
            sensors.extend([
                FeellooActivityRestWeekSensor(activity_week, cat_uid, name),
                FeellooActivityCalmWeekSensor(activity_week, cat_uid, name),
                FeellooActivityActionWeekSensor(activity_week, cat_uid, name),
            ])
        
        activity_month = coordinators.get("activity_month")
        if activity_month:
            sensors.extend([
                FeellooActivityRestMonthSensor(activity_month, cat_uid, name),
                FeellooActivityCalmMonthSensor(activity_month, cat_uid, name),
                FeellooActivityActionMonthSensor(activity_month, cat_uid, name),
            ])

        for sensor in sensors:
            uid = sensor.unique_id
            if uid in seen_ids:
                _LOGGER.warning("Duplicate unique_id %s for cat %s, skipping", uid, cat_uid)
                continue
            seen_ids.add(uid)
            entities.append(sensor)

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
        if self.coordinator.cats is None:
            return None
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
        val = (((cat.get("gateway") or {}).get("tag") or {}).get("status") or {}).get("battery_level")
        return _clamp(val, 0, 100, "battery_level", self._attr_unique_id)


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
        val = ((cat.get("geolocation") or {}).get("last_geolocation") or {}).get("latitude")
        return _clamp(val, -90, 90, "latitude", self._attr_unique_id)


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
        val = ((cat.get("geolocation") or {}).get("last_geolocation") or {}).get("longitude")
        return _clamp(val, -180, 180, "longitude", self._attr_unique_id)


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
        val = ((cat.get("geolocation") or {}).get("last_geolocation") or {}).get("precision_meter")
        return _clamp(val, 0, None, "precision_meter", self._attr_unique_id)


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
        ts = ((cat.get("geolocation") or {}).get("last_geolocation") or {}).get("date_time")
        return _parse_timestamp(ts)


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
        ts = ((cat.get("presence") or {}).get("status") or {}).get("presence_indication_time")
        return _parse_timestamp(ts)


class FeellooActivitySensor(CoordinatorEntity, SensorEntity):
    """Activity sensor — legacy combined activity."""

    _attr_icon = "mdi:run"
    _attr_has_entity_name = True

    def __init__(self, activity_coordinator, cat_uid, cat_name):
        super().__init__(activity_coordinator)
        self._cat_uid = cat_uid
        self._key = "activity"
        self._attr_unique_id = f"{cat_uid}_{self._key}"
        self._attr_translation_key = self._key
        self._attr_device_info = {
            "identifiers": {(DOMAIN, cat_uid)},
            "name": cat_name,
            "manufacturer": "Feelloo",
            "model": "Cat Tracker",
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.get_activity(self._cat_uid) is not None

    @property
    def native_value(self):
        activity = self.coordinator.get_activity(self._cat_uid)
        if not activity:
            return None
        # Return most dominant activity from average
        avg = activity.get("average") or {}
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
        activity = self.coordinator.get_activity(self._cat_uid)
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
        val = (activity.get("average") or {}).get("rest_percentage")
        return _clamp(val, 0, 100, "rest_percentage", self._attr_unique_id)

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
        val = (activity.get("average") or {}).get("calm_percentage")
        return _clamp(val, 0, 100, "calm_percentage", self._attr_unique_id)


class FeellooActivityActionSensor(FeellooActivityBaseSensor):
    """Activity action percentage sensor."""

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "activity_action", "mdi:run")

    @property
    def native_value(self):
        activity = self._get_activity()
        if not activity:
            return None
        val = (activity.get("average") or {}).get("action_percentage")
        return _clamp(val, 0, 100, "action_percentage", self._attr_unique_id)


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
        ts = (((cat.get("gateway") or {}).get("tag") or {}).get("extended_search") or {}).get("expiration_date")
        if ts and ts != "1970-01-01T00:00:00.000Z":
            return _parse_timestamp(ts)
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
        return _parse_timestamp(ts)


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
        return _parse_timestamp(ts)


class FeellooOutingCountSensor(FeellooTerritoryBaseSensor):
    """Total number of territory sessions."""

    _attr_icon = "mdi:map-marker-path"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "outing_count")

    @property
    def native_value(self):
        paths = self.coordinator.get_paths(self._cat_uid)
        if paths is None:
            return None
        return len(paths)

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
        start_dt = _parse_timestamp(start)
        end_dt = _parse_timestamp(end)
        if start_dt is None or end_dt is None:
            return None
        duration = int((end_dt - start_dt).total_seconds() / 60)
        if duration < 0:
            _LOGGER.debug("%s: rejecting negative duration: %s", self._attr_unique_id, duration)
            return None
        return duration


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
        points = session.get("points")
        if points is None:
            return None
        if not isinstance(points, list):
            _LOGGER.debug("%s: rejecting non-list points: %r", self._attr_unique_id, type(points))
            return None
        return len(points)

    @property
    def extra_state_attributes(self):
        """Return session points as attributes."""
        session = self._get_session()
        if not session:
            return {}
        points = session.get("points", [])
        if not isinstance(points, list):
            _LOGGER.debug("%s: rejecting non-list points in attributes: %r", self._attr_unique_id, type(points))
            return {}
        return {
            "points": [
                {
                    "latitude": (p.get("geolocation") or {}).get("latitude"),
                    "longitude": (p.get("geolocation") or {}).get("longitude"),
                    "precision_meter": (p.get("geolocation") or {}).get("precision_meter"),
                    "source": (p.get("geolocation") or {}).get("source"),
                    "date_time": p.get("date_time"),
                }
                for p in points if isinstance(p, dict)
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
        return _parse_timestamp(ts)


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
        return _parse_timestamp(ts)


class FeellooActivityWeekBaseSensor(CoordinatorEntity, SensorEntity):
    """Base for weekly activity percentage sensors."""

    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FeellooActivityWeekCoordinator,
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
        """Get weekly activity data for this cat."""
        return self.coordinator.get_activity(self._cat_uid)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._get_activity() is not None


class FeellooActivityRestWeekSensor(FeellooActivityWeekBaseSensor):
    """Weekly activity rest percentage sensor."""

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "activity_rest_week", "mdi:sleep")

    @property
    def native_value(self):
        activity = self._get_activity()
        if not activity:
            return None
        val = (activity.get("average") or {}).get("rest_percentage")
        return _clamp(val, 0, 100, "rest_percentage_week", self._attr_unique_id)

    @property
    def extra_state_attributes(self):
        """Return full history as attribute."""
        activity = self._get_activity()
        if not activity:
            return {}
        return {
            "history": activity.get("history", []),
        }


class FeellooActivityCalmWeekSensor(FeellooActivityWeekBaseSensor):
    """Weekly activity calm percentage sensor."""

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "activity_calm_week", "mdi:cat")

    @property
    def native_value(self):
        activity = self._get_activity()
        if not activity:
            return None
        val = (activity.get("average") or {}).get("calm_percentage")
        return _clamp(val, 0, 100, "calm_percentage_week", self._attr_unique_id)


class FeellooActivityActionWeekSensor(FeellooActivityWeekBaseSensor):
    """Weekly activity action percentage sensor."""

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "activity_action_week", "mdi:run")

    @property
    def native_value(self):
        activity = self._get_activity()
        if not activity:
            return None
        val = (activity.get("average") or {}).get("action_percentage")
        return _clamp(val, 0, 100, "action_percentage_week", self._attr_unique_id)


class FeellooActivityMonthBaseSensor(CoordinatorEntity, SensorEntity):
    """Base for monthly activity percentage sensors."""

    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FeellooActivityMonthCoordinator,
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
        """Get monthly activity data for this cat."""
        return self.coordinator.get_activity(self._cat_uid)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._get_activity() is not None


class FeellooActivityRestMonthSensor(FeellooActivityMonthBaseSensor):
    """Monthly activity rest percentage sensor."""

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "activity_rest_month", "mdi:sleep")

    @property
    def native_value(self):
        activity = self._get_activity()
        if not activity:
            return None
        val = (activity.get("average") or {}).get("rest_percentage")
        return _clamp(val, 0, 100, "rest_percentage_month", self._attr_unique_id)

    @property
    def extra_state_attributes(self):
        """Return full history as attribute."""
        activity = self._get_activity()
        if not activity:
            return {}
        return {
            "history": activity.get("history", []),
        }


class FeellooActivityCalmMonthSensor(FeellooActivityMonthBaseSensor):
    """Monthly activity calm percentage sensor."""

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "activity_calm_month", "mdi:cat")

    @property
    def native_value(self):
        activity = self._get_activity()
        if not activity:
            return None
        val = (activity.get("average") or {}).get("calm_percentage")
        return _clamp(val, 0, 100, "calm_percentage_month", self._attr_unique_id)


class FeellooActivityActionMonthSensor(FeellooActivityMonthBaseSensor):
    """Monthly activity action percentage sensor."""

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "activity_action_month", "mdi:run")

    @property
    def native_value(self):
        activity = self._get_activity()
        if not activity:
            return None
        val = (activity.get("average") or {}).get("action_percentage")
        return _clamp(val, 0, 100, "action_percentage_month", self._attr_unique_id)


class FeellooSignalStrengthSensor(FeellooSensorBase):
    """BLE signal strength sensor."""

    _attr_icon = "mdi:signal"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, cat_uid, cat_name):
        super().__init__(coordinator, cat_uid, cat_name, "signal_strength")

    @property
    def native_value(self):
        cat = self._get_cat()
        if not cat:
            return None
        presence = cat.get("presence") or {}
        status = presence.get("status") or {}
        in_range = status.get("in_range")
        rssi = status.get("f32_rssi_dbm")
        if in_range is False:
            return 0
        if rssi is None:
            return None
        # Handle string values from API
        if isinstance(rssi, str):
            try:
                rssi = float(rssi)
            except (ValueError, TypeError):
                _LOGGER.debug("%s: rejecting non-numeric RSSI: %r", self._attr_unique_id, rssi)
                return None
        if not isinstance(rssi, (int, float)):
            _LOGGER.debug("%s: rejecting non-numeric RSSI: %r", self._attr_unique_id, rssi)
            return None
        if not math.isfinite(rssi):
            _LOGGER.debug("%s: rejecting non-finite RSSI: %r", self._attr_unique_id, rssi)
            return None
        val = max(0, min(100, round(rssi + 154)))
        return _clamp(val, 0, None, "signal_strength", self._attr_unique_id)

    @property
    def extra_state_attributes(self):
        """Return raw RSSI dBm as attribute."""
        cat = self._get_cat()
        if not cat:
            return {}
        rssi = ((cat.get("presence") or {}).get("status") or {}).get("f32_rssi_dbm")
        return {
            "rssi_dbm": rssi,
        }
