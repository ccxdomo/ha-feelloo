"""The Feelloo integration."""

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    DOMAIN,
    SECONDARY_POLLING_INTERVALS,
    get_polling_settings,
    get_secondary_polling_intervals,
)
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
    auth = FeellooAuthManager(hass, entry.data["email"], entry.data["password"])

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
        # Credentials snapshot (Spec 047): lets the update listener tell
        # credential changes (reload) apart from options-only changes.
        "active_credentials": dict(entry.data),
    }

    # Options/credentials change listener (Spec 047): polling settings are
    # applied live; only a genuine credential change reloads the entry.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

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
        except UpdateFailed as exc:
            _LOGGER.warning(
                "%s coordinator failed first refresh, will retry on next interval",
                coordinator_name,
                exc_info=exc,
            )

    # Register service only once
    if not hass.services.has_service(DOMAIN, SERVICE_SET_PETITE_SOURIS):
        async def handle_set_petite_souris(call) -> None:
            """Handle the set_petite_souris service call."""
            cat_id = call.data["cat_id"]
            duration_hours = call.data["duration_hours"]
            
            # Find the coordinator for this cat
            target_entry = None
            domain_data = hass.data.get(DOMAIN, {})
            if not isinstance(domain_data, dict):
                _LOGGER.error("hass.data[%s] is not a dict: %s", DOMAIN, type(domain_data))
                raise HomeAssistantError("Internal error: Feelloo data corrupted")
            
            for entry_id, data in domain_data.items():
                if not isinstance(data, dict):
                    continue
                main = data.get("main")
                if main:
                    valid_cat_ids = {c.get("cat_id") for c in main.cats if isinstance(c.get("cat_id"), int)}
                    if cat_id in valid_cat_ids:
                        target_entry = main
                        break
            
            if target_entry is None:
                raise HomeAssistantError(f"Cat {cat_id} not found in any Feelloo account")
            
            await target_entry.async_set_petite_souris(cat_id, duration_hours)
            await target_entry.async_request_refresh()

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
        
        # Only remove service if no entries remain
        if not hass.data.get(DOMAIN):
            hass.services.async_remove(DOMAIN, SERVICE_SET_PETITE_SOURIS)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry updates.

    A credential change reloads the entry so a new auth manager is built
    with the updated credentials (same outcome as pre-1.8.0). Any other
    change is an options-only change: polling settings are applied live,
    without a reload, so entities keep their values and availability.
    The live apply is idempotent, so it is safe if it fires more than once.
    """
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not data:
        # Entry is being torn down — nothing to apply.
        return
    if dict(entry.data) != data["active_credentials"]:
        await hass.config_entries.async_reload(entry.entry_id)
        return
    await data["main"].async_apply_polling_settings(*get_polling_settings(entry))

    # Secondary polling intervals (Spec 048): apply each coordinator's
    # resolved interval live, in the fixed order. Unchanged values are
    # idempotent no-ops, so a re-fired listener is harmless. A missing
    # coordinator (teardown race) is skipped defensively.
    resolved_secondary = get_secondary_polling_intervals(entry)
    for key in SECONDARY_POLLING_INTERVALS:
        coordinator = data.get(key)
        if coordinator is None:
            _LOGGER.warning("Coordinator %s missing while applying polling intervals", key)
            continue
        await coordinator.async_apply_polling_interval(resolved_secondary[key])


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
