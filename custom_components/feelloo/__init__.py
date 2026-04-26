"""The Feelloo integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import FeellooAuthManager, FeellooMainCoordinator, FeellooActivityCoordinator, FeellooTerritoryCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Feelloo from a config entry."""
    auth = FeellooAuthManager(entry.data["email"], entry.data["password"])

    # Main coordinator — polls /users/cats every 5 min
    main_coordinator = FeellooMainCoordinator(hass, entry, auth)
    await main_coordinator.async_setup()

    # Activity coordinator — polls /activity every 15 min
    activity_coordinator = FeellooActivityCoordinator(hass, entry, auth)
    try:
        await activity_coordinator.async_config_entry_first_refresh()
    except Exception:
        _LOGGER.warning("Activity coordinator failed first refresh, will retry on next interval")

    # Territory coordinator — polls /territory/paths every 15 min
    territory_coordinator = FeellooTerritoryCoordinator(hass, entry, auth)
    try:
        await territory_coordinator.async_config_entry_first_refresh()
    except Exception:
        _LOGGER.warning("Territory coordinator failed first refresh, will retry on next interval")

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "auth": auth,
        "main": main_coordinator,
        "activity": activity_coordinator,
        "territory": territory_coordinator,
    }

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
            await data["territory"].async_shutdown()
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
