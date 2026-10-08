"""Switch platform for Feelloo Petite Souris."""

from __future__ import annotations

import asyncio

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
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
    """Switch to enable/disable automatic polling of the main coordinator.

    Owner follow-up 2 (2026-10-08): while the Petite Souris override runs,
    the switch reports the EFFECTIVE state (on, 1-minute polling) — a
    control reading "off" while data keeps flowing would be misleading.
    The override is additionally made visible through a distinct icon, the
    "(Petite Souris)" name variant (entity-registry translation_key swap)
    and saved/effective attributes. Turning the switch off during the
    override still cancels it (manual wins, contract 047 §4.2) — the
    command semantics are unchanged.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "polling_enabled"
    _attr_entity_category = EntityCategory.CONFIG

    _BASE_ICON = "mdi:autorenew"
    _OVERRIDE_ICON = "mdi:clock-fast"
    _OVERRIDE_TRANSLATION_KEY = "polling_enabled_override"

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
        """Return true if polling is effectively running.

        Reports the effective state so the visible label never falsely
        reads "off" while data flows: while the Petite Souris override is
        active, polling runs (at 1 minute) even when the saved preference
        is disabled. The saved preference always remains visible in the
        attributes.
        """
        if self._coordinator.petite_souris_override:
            return True
        return get_polling_settings(self._entry)[0]

    @property
    def icon(self) -> str | None:
        """Return a distinct icon while the Petite Souris override runs."""
        if self._coordinator.petite_souris_override:
            return self._OVERRIDE_ICON
        return self._BASE_ICON

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the saved preference and the effective state."""
        saved_enabled, saved_interval = get_polling_settings(self._entry)
        return {
            "saved_polling_enabled": saved_enabled,
            "saved_polling_interval_minutes": saved_interval,
            "effective_polling_enabled": self._coordinator.polling_enabled,
            "effective_polling_interval_minutes": (
                self._coordinator.polling_interval_minutes
            ),
        }

    async def async_added_to_hass(self) -> None:
        """Track option changes and Petite Souris override transitions."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._entry.add_update_listener(self._async_on_entry_update)
        )
        # Override transitions happen inside coordinator fetches; re-render
        # on every coordinator update so the visible state stays truthful.
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self._async_sync_override_visibility()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Re-render after a coordinator update (override transitions)."""
        self._async_sync_override_visibility()

    async def _async_on_entry_update(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Write state after options changed through another surface."""
        self._async_sync_override_visibility()

    @callback
    def _async_sync_override_visibility(self) -> None:
        """Make the Petite Souris override visible on this switch.

        HA switch states are binary, so the override cannot be a third
        state: the state label stays truthful through is_on (effective
        state), and the override marker is carried by the icon, the
        saved/effective attributes, and the displayed name — swapped via
        the supported entity-registry translation_key update so the UI
        shows "Automatic Polling (Petite Souris)" while the boost runs.
        Skipped when the entity is unregistered or renamed by the user.
        """
        desired_key = (
            self._OVERRIDE_TRANSLATION_KEY
            if self._coordinator.petite_souris_override
            else "polling_enabled"
        )
        entity_id = getattr(self, "_attr_entity_id", None)
        if entity_id:
            registry = async_get_entity_registry(self.hass)
            entry = registry.async_get(entity_id)
            if (
                entry is not None
                and entry.translation_key != desired_key
                and entry.name is None
            ):
                # Never clobber a user-defined name; the translated variant
                # only applies while the integration names the entity.
                registry.async_update_entity(
                    entity_id, translation_key=desired_key
                )
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Enable automatic polling."""
        await self._async_set_polling(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable automatic polling.

        During a Petite Souris override this cancels the temporary boost
        (manual wins) and is NOT a no-op: polling stops and the switch
        visibly flips to off.
        """
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
        self._async_sync_override_visibility()
