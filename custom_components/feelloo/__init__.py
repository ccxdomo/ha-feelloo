"""The Feelloo integration."""

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import FeellooAuthManager, FeellooMainCoordinator, FeellooActivityCoordinator, FeellooTerritoryCoordinator, FeellooSessionCoordinator, FeellooActivityWeekCoordinator, FeellooActivityMonthCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.SWITCH,
    Platform.NUMBER,
]

SERVICE_SET_PETITE_SOURIS = "set_petite_souris"
SERVICE_SCHEMA = vol.Schema({
    vol.Required("cat_id"): cv.positive_int,
    vol.Required("duration_hours"): vol.All(vol.Coerce(int), vol.Range(min=0, max=72)),
})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Feelloo from a config entry."""
    auth = FeellooAuthManager(entry.data["email"], entry.data["password"])

    # Main coordinator — polls /users/cats every 5 min
    main_coordinator = FeellooMainCoordinator(hass, entry, auth)
    await main_coordinator.async_setup()

    # Create all coordinators first
    activity_coordinator = FeellooActivityCoordinator(hass, entry, auth)
    territory_coordinator = FeellooTerritoryCoordinator(hass, entry, auth)
    activity_week_coordinator = FeellooActivityWeekCoordinator(hass, entry, auth)
    activity_month_coordinator = FeellooActivityMonthCoordinator(hass, entry, auth)
    session_coordinator = FeellooSessionCoordinator(hass, entry, auth)

    # Populate hass.data BEFORE first refresh so coordinators can reference each other
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "auth": auth,
        "main": main_coordinator,
        "activity": activity_coordinator,
        "activity_week": activity_week_coordinator,
        "activity_month": activity_month_coordinator,
        "territory": territory_coordinator,
        "session": session_coordinator,
    }

    # Now safe to do first refresh — all coordinators are in hass.data
    for coordinator_name, coordinator in [
        ("activity", activity_coordinator),
        ("territory", territory_coordinator),
        ("activity_week", activity_week_coordinator),
        ("activity_month", activity_month_coordinator),
        ("session", session_coordinator),
    ]:
        try:
            await coordinator.async_config_entry_first_refresh()
        except Exception:
            _LOGGER.warning("%s coordinator failed first refresh, will retry on next interval", coordinator_name)

    # Register service
    async def handle_set_petite_souris(call) -> None:
        """Handle the set_petite_souris service call."""
        cat_id = call.data["cat_id"]
        duration_hours = call.data["duration_hours"]
        await main_coordinator.async_set_petite_souris(cat_id, duration_hours)
        await main_coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_PETITE_SOURIS,
        handle_set_petite_souris,
        schema=SERVICE_SCHEMA,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if data:
            await data["auth"].async_shutdown()
            await data["main"].async_shutdown()
            await data["activity"].async_shutdown()
            await data["activity_week"].async_shutdown()
            await data["activity_month"].async_shutdown()
            await data["territory"].async_shutdown()
            await data["session"].async_shutdown()
        hass.services.async_remove(DOMAIN, SERVICE_SET_PETITE_SOURIS)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
