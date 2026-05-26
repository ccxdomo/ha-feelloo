"""Device tracker platform for Feelloo."""

from __future__ import annotations

import logging
import math
import os

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import FeellooMainCoordinator

_LOGGER = logging.getLogger(__name__)


# Base path for user-provided cat images
_LOCAL_IMAGE_DIR = "/config/www/feelloo"


async def _async_resolve_entity_picture(hass: HomeAssistant, cat_name: str) -> str | None:
    """Return the entity_picture path if a local image exists for this cat."""
    safe_name = slugify(cat_name)
    if not safe_name:
        return None
    for ext in ("jpg", "jpeg", "png", "webp"):
        path = os.path.join(_LOCAL_IMAGE_DIR, f"{safe_name}.{ext}")
        if await hass.async_add_executor_job(os.path.isfile, path):
            return f"/local/feelloo/{safe_name}.{ext}"
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Feelloo device trackers."""
    main_coordinator: FeellooMainCoordinator = hass.data[DOMAIN][entry.entry_id]["main"]
    entities = []
    for cat in main_coordinator.cats:
        cat_uid = cat.get("_id")
        name = (cat.get("profile") or {}).get("name", "Unknown")
        if not cat_uid:
            continue
        entities.append(FeellooDeviceTracker(hass, main_coordinator, cat_uid, name))
    async_add_entities(entities)


class FeellooDeviceTracker(CoordinatorEntity, TrackerEntity):
    """Device tracker for a Feelloo cat."""

    _attr_has_entity_name = False
    _attr_force_update = True

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: FeellooMainCoordinator,
        cat_uid: str,
        cat_name: str,
    ) -> None:
        """Initialize the tracker."""
        super().__init__(coordinator)
        self.hass = hass
        self._cat_uid = cat_uid
        self._cat_name = cat_name
        self._attr_unique_id = f"{cat_uid}_tracker"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, cat_uid)},
            "name": cat_name,
            "manufacturer": "Feelloo",
            "model": "Cat Tracker",
        }
        self._entity_picture: str | None = None

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._entity_picture = await _async_resolve_entity_picture(self.hass, self._cat_name)

    @property
    def name(self) -> str:
        """Return the name of the tracker.

        Home Assistant generates the entity_id by slugifying this name,
        e.g. device_tracker.{cat_name_slug}.
        """
        return self._cat_name

    def _get_cat(self) -> dict | None:
        """Get the cat data from coordinator."""
        for cat in self.coordinator.cats:
            if cat.get("_id") == self._cat_uid:
                return cat
        return None

    @property
    def source_type(self) -> SourceType:
        """Return the source type."""
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Return latitude."""
        cat = self._get_cat()
        if not cat:
            return None
        geo = (cat.get("geolocation") or {}).get("last_geolocation") or {}
        lat = geo.get("latitude")
        if lat is None:
            return None
        try:
            lat = float(lat)
            if not -90 <= lat <= 90 or not math.isfinite(lat):
                return None
            return lat
        except (ValueError, TypeError):
            return None

    @property
    def longitude(self) -> float | None:
        """Return longitude."""
        cat = self._get_cat()
        if not cat:
            return None
        geo = (cat.get("geolocation") or {}).get("last_geolocation") or {}
        lng = geo.get("longitude")
        if lng is None:
            return None
        try:
            lng = float(lng)
            if not -180 <= lng <= 180 or not math.isfinite(lng):
                return None
            return lng
        except (ValueError, TypeError):
            return None

    @property
    def location_accuracy(self) -> int | None:
        """Return the gps accuracy."""
        cat = self._get_cat()
        if not cat:
            return None
        geo = (cat.get("geolocation") or {}).get("last_geolocation") or {}
        accuracy = geo.get("precision_meter")
        if accuracy is None:
            return None
        try:
            accuracy = float(accuracy)
            if not (0 <= accuracy <= 10000) or not math.isfinite(accuracy):
                return None
            return int(accuracy)
        except (ValueError, TypeError, OverflowError):
            return None

    @property
    def entity_picture(self) -> str | None:
        """Return the entity picture if a local image exists."""
        return self._entity_picture

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:cat"

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes."""
        cat = self._get_cat()
        if not cat:
            return {}

        geo = (cat.get("geolocation") or {}).get("last_geolocation") or {}
        return {
            "last_seen": geo.get("date_time"),
            "precision_meter": geo.get("precision_meter"),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator.

        Force a state update so the map marker refreshes even when
        coordinates have not changed (precision/signal may have).
        """
        cat = self._get_cat()
        if cat:
            geo = (cat.get("geolocation") or {}).get("last_geolocation") or {}
            _LOGGER.debug(
                "Device tracker update for %s: lat=%s, lng=%s",
                self._cat_name,
                geo.get("latitude"),
                geo.get("longitude"),
            )
            self.hass.add_job(self._async_refresh_entity_picture)
        self.async_write_ha_state()

    async def _async_refresh_entity_picture(self) -> None:
        """Refresh entity picture if it changed."""
        new_picture = await _async_resolve_entity_picture(self.hass, self._cat_name)
        if new_picture != self._entity_picture:
            self._entity_picture = new_picture
            self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self._get_cat() is not None
