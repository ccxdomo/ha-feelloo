"""Switch platform for Feelloo Petite Souris."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
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
    """Set up Feelloo switch entities."""
    main_coordinator: FeellooMainCoordinator = hass.data[DOMAIN][entry.entry_id]["main"]
    entities = []
    for cat in main_coordinator.cats:
        cat_uid = cat.get("_id")
        cat_id = cat.get("cat_id")
        name = cat.get("profile", {}).get("name", "Unknown")
        if not cat_uid or cat_id is None:
            continue
        entities.append(FeellooPetiteSourisSwitch(main_coordinator, cat_uid, cat_id, name))
    async_add_entities(entities)


class FeellooPetiteSourisSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to enable/disable Petite Souris mode."""

    _attr_has_entity_name = True
    _attr_translation_key = "petite_souris"
    _attr_icon = "mdi:map-search"

    def __init__(
        self,
        coordinator: FeellooMainCoordinator,
        cat_uid: str,
        cat_id: int,
        cat_name: str,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._cat_uid = cat_uid
        self._cat_id = cat_id
        self._cat_name = cat_name
        self._attr_unique_id = f"{cat_uid}_petite_souris"
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

    def _get_duration(self) -> int:
        """Get the current duration value from the number entity."""
        # Look for the number entity in hass.states
        entity_id = f"number.{self._cat_name.lower().replace(' ', '_')}_petite_souris_duration"
        state = self.hass.states.get(entity_id)
        if state and state.state not in (None, "unavailable", "unknown"):
            try:
                return int(float(state.state))
            except (ValueError, TypeError):
                pass
        return 2  # Default fallback

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        cat = self._get_cat()
        if not cat:
            return None
        return cat.get("geolocation", {}).get("petite_souris", {}).get("programmed", False)

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra attributes."""
        cat = self._get_cat()
        if not cat:
            return {}
        return {
            "expiration_time": cat.get("geolocation", {}).get("petite_souris", {}).get("expiration_time"),
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._get_cat() is not None

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the switch on."""
        duration = self._get_duration()
        await self.coordinator.async_set_petite_souris(self._cat_id, duration)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""
        await self.coordinator.async_set_petite_souris(self._cat_id, 0)
        await self.coordinator.async_request_refresh()
