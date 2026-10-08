"""Switch platform for Feelloo Petite Souris."""

from __future__ import annotations

import asyncio

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import CONF_POLLING_ENABLED, DOMAIN, get_polling_settings
from .coordinator import FeellooMainCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Feelloo switch entities."""
    main_coordinator: FeellooMainCoordinator = hass.data[DOMAIN][entry.entry_id]["main"]
    # Per-account polling control (Spec 047), then one petite souris switch per cat.
    entities = [FeellooPollingSwitch(main_coordinator, entry)]
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
        self._lock = asyncio.Lock()

    def _get_cat(self) -> dict | None:
        """Get the cat data from coordinator."""
        for cat in self.coordinator.cats:
            if cat.get("_id") == self._cat_uid:
                return cat
        return None

    def _get_duration(self) -> int:
        """Get the current duration value from the number entity."""
        er = async_get_entity_registry(self.hass)
        entity_id = er.async_get_entity_id(
            "number", DOMAIN, f"{self._cat_uid}_petite_souris_duration"
        )
        if entity_id is None:
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

    async def _async_call_petite_souris(self, duration_hours: int) -> None:
        """Call the Petite Souris API via coordinator and handle 204 No Content explicitly."""
        try:
            await self.coordinator.async_set_petite_souris(self._cat_id, duration_hours)
            await self.coordinator.async_request_refresh()
        except UpdateFailed as exc:
            raise HomeAssistantError(f"Erreur Petite Souris: {exc}") from exc

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the switch on."""
        async with self._lock:
            duration = self._get_duration()
            if not (1 <= duration <= 72):
                raise HomeAssistantError(
                    f"Durée Petite Souris invalide: {duration}h (doit être entre 1 et 72h)"
                )
            await self._async_call_petite_souris(duration)
            # Only emit fast polling after successful POST
            self.hass.bus.async_fire("feelloo_fast_polling", {
                "cat_id": self._cat_id,
                "enabled": True,
            })

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""
        async with self._lock:
            await self._async_call_petite_souris(0)
            # Only emit fast polling after successful POST
            self.hass.bus.async_fire("feelloo_fast_polling", {
                "cat_id": self._cat_id,
                "enabled": False,
            })


class FeellooPollingSwitch(SwitchEntity):
    """Switch to enable/disable automatic polling of the main coordinator."""

    _attr_has_entity_name = True
    _attr_translation_key = "polling_enabled"
    _attr_icon = "mdi:autorenew"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FeellooMainCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the switch."""
        self._coordinator = coordinator
        self._entry = entry
        uid = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{uid}_polling_enabled"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Feelloo",
            "manufacturer": "Feelloo",
            "model": "Account",
        }

    @property
    def is_on(self) -> bool:
        """Return true if automatic polling is enabled."""
        return get_polling_settings(self._entry)[0]

    async def async_added_to_hass(self) -> None:
        """Register a listener so the state follows option changes made elsewhere."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._entry.add_update_listener(self._async_on_entry_update)
        )

    async def _async_on_entry_update(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Write state after options changed through another surface."""
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Enable automatic polling."""
        await self._async_set_polling(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable automatic polling."""
        await self._async_set_polling(False)

    async def _async_set_polling(self, enabled: bool) -> None:
        """Apply the change live, then persist it to the entry options."""
        _, interval_minutes = get_polling_settings(self._entry)
        # Apply first (contract 047 §7.2): the change takes effect even while
        # the persist call races; persisting fires the update listener which
        # re-applies idempotently.
        await self._coordinator.async_apply_polling_settings(enabled, interval_minutes)
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_POLLING_ENABLED: enabled},
        )
        self.async_write_ha_state()
