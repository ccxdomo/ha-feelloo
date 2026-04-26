"""Device tracker platform for Feelloo."""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
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
    """Set up Feelloo device trackers."""
    coordinator: FeellooCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for cat in coordinator.cats:
        cat_uid = cat.get("_id")
        name = cat.get("profile", {}).get("name", "Unknown")
        if not cat_uid:
            continue
        entities.append(FeellooDeviceTracker(coordinator, cat_uid, name))
    async_add_entities(entities)


class FeellooDeviceTracker(CoordinatorEntity, TrackerEntity):
    """Device tracker for a Feelloo cat."""

    _attr_has_entity_name = True
    _attr_translation_key = "tracker"

    def __init__(
        self,
        coordinator: FeellooCoordinator,
        cat_uid: str,
        cat_name: str,
    ) -> None:
        """Initialize the tracker."""
        super().__init__(coordinator)
        self._cat_uid = cat_uid
        self._cat_name = cat_name
        self._attr_unique_id = f"{cat_uid}_tracker"
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
    def source_type(self) -> SourceType:
        """Return the source type."""
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Return latitude."""
        cat = self._get_cat()
        if not cat:
            return None
        return cat.get("geolocation", {}).get("last_geolocation", {}).get("latitude")

    @property
    def longitude(self) -> float | None:
        """Return longitude."""
        cat = self._get_cat()
        if not cat:
            return None
        return cat.get("geolocation", {}).get("last_geolocation", {}).get("longitude")

    @property
    def location_accuracy(self) -> int:
        """Return the gps accuracy."""
        cat = self._get_cat()
        if not cat:
            return 0
        return cat.get("geolocation", {}).get("last_geolocation", {}).get("precision_meter", 0)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        cat = self._get_cat()
        if not cat:
            return False
        geo = cat.get("geolocation", {}).get("last_geolocation", {})
        return geo.get("latitude") is not None and geo.get("longitude") is not None
