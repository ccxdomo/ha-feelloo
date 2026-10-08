"""Number platform for Feelloo Petite Souris duration."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_POLLING_INTERVAL,
    DOMAIN,
    POLLING_INTERVAL_MIN,
    POLLING_INTERVAL_MAX,
    get_polling_settings,
)
from .coordinator import FeellooMainCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Feelloo number entities."""
    try:
        main_coordinator: FeellooMainCoordinator = hass.data[DOMAIN][entry.entry_id]["main"]
    except (KeyError, TypeError):
        _LOGGER.error("Main coordinator missing for entry %s", entry.entry_id)
        return

    entities = []
    # Per-account polling control (Spec 047), then one duration entity per cat.
    entities.append(FeellooPollingIntervalNumber(main_coordinator, entry))
    for cat in main_coordinator.cats or []:
        if not isinstance(cat, dict):
            continue
        cat_uid = cat.get("_id")
        name = (cat.get("profile") or {}).get("name", "Unknown")
        if not isinstance(cat_uid, str) or not cat_uid:
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
        if self.coordinator.cats is None:
            return None
        for cat in self.coordinator.cats:
            if isinstance(cat, dict) and cat.get("_id") == self._cat_uid:
                return cat
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self._get_cat() is not None

    async def async_set_native_value(self, value: float) -> None:
        """Update the value with validation."""
        if not isinstance(value, (int, float)):
            raise ValueError(f"Duration must be numeric, got {type(value).__name__}")

        if not value.is_integer():
            raise ValueError("Duration must be a whole number of hours")

        duration = int(value)
        if duration < self._attr_native_min_value or duration > self._attr_native_max_value:
            raise ValueError(
                f"Duration must be between {self._attr_native_min_value} "
                f"and {self._attr_native_max_value} hours"
            )

        self._attr_native_value = duration
        self.async_write_ha_state()


class FeellooPollingIntervalNumber(NumberEntity):
    """Number entity for the main coordinator polling interval (minutes)."""

    _attr_has_entity_name = True
    _attr_translation_key = "polling_interval"
    _attr_icon = "mdi:clock-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = POLLING_INTERVAL_MIN
    _attr_native_max_value = POLLING_INTERVAL_MAX
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "min"
    _attr_mode = "box"

    def __init__(
        self,
        coordinator: FeellooMainCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the number entity."""
        self._coordinator = coordinator
        self._entry = entry
        uid = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{uid}_polling_interval"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Feelloo",
            "manufacturer": "Feelloo",
            "model": "Account",
        }

    @property
    def native_value(self) -> int | None:
        """Return the persisted polling interval in minutes."""
        return get_polling_settings(self._entry)[1]

    async def async_added_to_hass(self) -> None:
        """Register a listener so the state follows option changes made elsewhere."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._entry.add_update_listener(self._async_on_entry_update)
        )

    async def _async_on_entry_update(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Write state after options changed through another surface."""
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Update the value with validation."""
        if not isinstance(value, (int, float)):
            raise ValueError(f"Interval must be numeric, got {type(value).__name__}")

        if not value.is_integer():
            raise ValueError("Interval must be a whole number of minutes")

        interval = int(value)
        if interval < self._attr_native_min_value or interval > self._attr_native_max_value:
            raise ValueError(
                f"Interval must be between {self._attr_native_min_value} "
                f"and {self._attr_native_max_value} minutes"
            )

        enabled, _ = get_polling_settings(self._entry)
        # Apply first (contract 047 §7.2), then persist; persisting fires the
        # update listener which re-applies idempotently. While polling is
        # disabled the value is stored and takes effect on the next enable.
        await self._coordinator.async_apply_polling_settings(enabled, interval)
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_POLLING_INTERVAL: interval},
        )
        self.async_write_ha_state()
