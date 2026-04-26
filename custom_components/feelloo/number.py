"""Number platform for Feelloo Petite Souris duration."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FeellooMainCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Feelloo number entities."""
    main_coordinator: FeellooMainCoordinator = hass.data[DOMAIN][entry.entry_id]["main"]
    entities = []
    for cat in main_coordinator.cats:
        cat_uid = cat.get("_id")
        name = cat.get("profile", {}).get("name", "Unknown")
        if not cat_uid:
            continue
        entities.append(FeellooPetiteSourisDuration(main_coordinator, cat_uid, name))
    async_add_entities(entities)


class FeellooPetiteSourisDuration(CoordinatorEntity, NumberEntity):
    """Number entity for Petite Souris duration."""

    _attr_has_entity_name = True
    _attr_translation_key = "petite_souris_duration"
    _attr_icon = "mdi:timer"
    _attr_native_min_value = 1
    _attr_native_max_value = 72
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "h"
    _attr_mode = "box"

    def __init__(
        self,
        coordinator: FeellooMainCoordinator,
        cat_uid: str,
        cat_name: str,
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator)
        self._cat_uid = cat_uid
        self._attr_unique_id = f"{cat_uid}_petite_souris_duration"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, cat_uid)},
            "name": cat_name,
            "manufacturer": "Feelloo",
            "model": "Cat Tracker",
        }
        self._attr_native_value = 2

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

    async def async_set_native_value(self, value: float) -> None:
        """Update the value."""
        self._attr_native_value = int(value)
        self.async_write_ha_state()
