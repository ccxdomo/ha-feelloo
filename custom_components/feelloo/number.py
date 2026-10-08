"""Number platform for Feelloo Petite Souris duration."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_POLLING_INTERVAL,
    DOMAIN,
    POLLING_INTERVAL_MIN,
    POLLING_INTERVAL_MAX,
    SECONDARY_POLLING_INTERVALS,
    get_polling_settings,
    get_secondary_polling_intervals,
)
from .coordinator import FeellooMainCoordinator, FeellooSecondaryCoordinator

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
    # Per-account polling control (Spec 047), then the five secondary
    # polling interval numbers (Spec 048, fixed order), then one duration
    # entity per cat.
    entities.append(FeellooPollingIntervalNumber(main_coordinator, entry))
    for key in SECONDARY_POLLING_INTERVALS:
        coordinator = hass.data[DOMAIN][entry.entry_id].get(key)
        if coordinator is None:
            # Defensive: a missing coordinator (teardown race) must not
            # break entity setup for the others.
            _LOGGER.warning(
                "Coordinator %s missing for entry %s, skipping its polling interval number",
                key,
                entry.entry_id,
            )
            continue
        entities.append(FeellooSecondaryPollingIntervalNumber(coordinator, entry, key))
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
    """Number entity for the main coordinator polling interval (minutes).

    Displays the interval currently in force (owner follow-up 3): while the
    Petite Souris override runs, the value shown is the effective 1-minute
    cadence — mirroring the switch's effective-state display — and the
    number returns to the saved preference automatically when the mode
    ends. The saved preference always remains visible in the attributes.
    """

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
        """Return the interval currently in force (minutes).

        Mirrors the switch's effective-state display (owner follow-up 3):
        while the Petite Souris override runs, the value shown is the
        effective 1-minute cadence — the number must never display the
        saved preference while a different cadence is actually running.
        Otherwise it shows the saved preference, and it returns to it
        automatically when the mode ends.
        """
        if self._coordinator.petite_souris_override:
            return self._coordinator.polling_interval_minutes
        return get_polling_settings(self._entry)[1]

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the saved preference and the effective state.

        Mirrors the switch's attribute naming (owner follow-up 3) so the
        saved/effective pair reads identically on both config entities.
        petite_souris_override is a display mirror of the coordinator's
        single override flag — the Last Update sensor remains the
        reference surface for "is the override running".
        """
        return {
            "saved_polling_interval_minutes": get_polling_settings(self._entry)[1],
            "effective_polling_interval_minutes": (
                self._coordinator.polling_interval_minutes
            ),
            "petite_souris_override": self._coordinator.petite_souris_override,
        }

    async def async_added_to_hass(self) -> None:
        """Register listeners so the state follows changes made elsewhere."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._entry.add_update_listener(self._async_on_entry_update)
        )
        # Override transitions happen inside coordinator fetches; re-render
        # on coordinator updates so the displayed interval and attributes
        # stay fresh while the Petite Souris boost runs.
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Re-render after a coordinator update (override transitions)."""
        self.async_write_ha_state()

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

        # Write-path safety (owner follow-up 3): read the enabled flag from
        # the SAVED preference — never the effective override state — so a
        # manual write during an override updates the preference without
        # corrupting it. Only the user's input is persisted (the override
        # never writes entry.options), and the apply call cancels the
        # override per the validated manual-wins semantics, so the display
        # and reality converge immediately after a write.
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


class FeellooSecondaryPollingIntervalNumber(NumberEntity):
    """Number entity for a secondary coordinator's polling interval (minutes).

    Spec 048: one instance per secondary coordinator (activity,
    activity_week, activity_month, territory, session). Plain NumberEntity
    (NOT CoordinatorEntity) so the control stays usable even when the
    coordinator's last refresh failed. Saved == effective for secondaries
    (there is no override concept), so native_value reads the resolved
    options directly; no extra_state_attributes — the Last Update sensor
    carries the resolved dict for machine consumption. No switches (the
    owner rejected disabling) and no sensor hiding: slowing a coordinator
    never removes, hides, or blanks its entities.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:clock-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = POLLING_INTERVAL_MIN
    _attr_native_max_value = POLLING_INTERVAL_MAX
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "min"
    _attr_mode = "box"

    def __init__(
        self,
        coordinator: FeellooSecondaryCoordinator,
        entry: ConfigEntry,
        key: str,
    ) -> None:
        """Initialize the number entity."""
        self._coordinator = coordinator
        self._entry = entry
        self._key = key
        self._option_key = SECONDARY_POLLING_INTERVALS[key][0]
        self._attr_translation_key = self._option_key
        uid = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{uid}_{self._option_key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Feelloo",
            "manufacturer": "Feelloo",
            "model": "Account",
        }

    @property
    def native_value(self) -> int | None:
        """Return the resolved interval (saved == effective for secondaries)."""
        return get_secondary_polling_intervals(self._entry)[self._key]

    async def async_added_to_hass(self) -> None:
        """Register a listener so the state follows changes made elsewhere."""
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

        # Apply first (047 §7.2 order discipline), then persist; persisting
        # fires the update listener which re-applies idempotently.
        await self._coordinator.async_apply_polling_interval(interval)
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, self._option_key: interval},
        )
        self.async_write_ha_state()
