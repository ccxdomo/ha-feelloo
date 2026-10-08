"""Button platform for Feelloo."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FeellooMainCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Feelloo buttons."""
    main_coordinator: FeellooMainCoordinator = hass.data[DOMAIN][entry.entry_id]["main"]
    # Per-account refresh button (Spec 047), then one ring button per ringable cat.
    entities = [FeellooRefreshButton(entry)]
    for cat in main_coordinator.cats:
        cat_uid = cat.get("_id")
        cat_id = cat.get("cat_id")
        name = cat.get("profile", {}).get("name", "Unknown")
        can_ring = cat.get("gateway", {}).get("tag", {}).get("can_ring", False)
        if not cat_uid or cat_id is None or not can_ring:
            continue
        entities.append(FeellooRingButton(main_coordinator, cat_uid, cat_id, name))
    async_add_entities(entities)


class FeellooRingButton(CoordinatorEntity, ButtonEntity):
    """Button to ring the cat tag."""

    _attr_icon = "mdi:bell-ring"
    _attr_has_entity_name = True
    _attr_translation_key = "ring"

    def __init__(
        self,
        coordinator: FeellooMainCoordinator,
        cat_uid: str,
        cat_id: int,
        cat_name: str,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._cat_uid = cat_uid
        self._cat_id = cat_id
        self._attr_unique_id = f"{cat_uid}_ring"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, cat_uid)},
            "name": cat_name,
            "manufacturer": "Feelloo",
            "model": "Cat Tracker",
        }

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_ring_cat(self._cat_id)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        cat = None
        for c in self.coordinator.cats:
            if c.get("_id") == self._cat_uid:
                cat = c
                break
        if not cat:
            return False
        return cat.get("gateway", {}).get("tag", {}).get("can_ring", False)


class FeellooRefreshButton(ButtonEntity):
    """Button to refresh every Feelloo coordinator on demand."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh_data"
    _attr_icon = "mdi:refresh"

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the button."""
        self._entry = entry
        uid = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{uid}_refresh_data"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Feelloo",
            "manufacturer": "Feelloo",
            "model": "Account",
        }

    async def async_press(self) -> None:
        """Refresh all coordinators (works with polling enabled or disabled)."""
        data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if not data:
            raise HomeAssistantError("Feelloo integration data is not available")

        main = data["main"]

        # Main coordinator first: the other coordinators read main.cats during
        # their updates, so it must hold the freshest cat list. A genuine
        # failure must surface (do not swallow).
        await main.async_request_refresh()
        if not main.last_update_success:
            raise HomeAssistantError(f"Feelloo refresh failed: {main.last_exception}")

        # Refresh the remaining coordinators concurrently. Partial failures
        # are logged but do not fail the press — partial data is still useful.
        secondary = (
            ("activity", data["activity"]),
            ("activity_week", data["activity_week"]),
            ("activity_month", data["activity_month"]),
            ("territory", data["territory"]),
            ("session", data["session"]),
        )
        results = await asyncio.gather(
            *(coordinator.async_request_refresh() for _, coordinator in secondary),
            return_exceptions=True,
        )
        for (name, _), result in zip(secondary, results):
            if isinstance(result, BaseException):
                _LOGGER.warning(
                    "Manual refresh of the %s coordinator failed: %s", name, result
                )
