"""DataUpdateCoordinator for Feelloo."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import aiohttp
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    FIREBASE_API_KEY,
    FIREBASE_SIGNIN_URL,
    FIREBASE_REFRESH_URL,
    BASE_URL,
    TOKEN_REFRESH_INTERVAL,
    FAST_POLLING_INTERVAL,
    CONF_EMAIL,
    CONF_PASSWORD,
    ENDPOINT_CATS,
    ENDPOINT_CAT_DETAIL,
    ENDPOINT_ACTIVITY,
    ENDPOINT_TERRITORY_PATHS,
    ENDPOINT_TERRITORY,
    ENDPOINT_RING,
    ENDPOINT_PETITE_SOURIS,
    ENDPOINT_TERRITORY_PATH,
    PETITE_SOURIS_OVERRIDE_INTERVAL_MINUTES,
    get_polling_settings,
    get_secondary_polling_intervals,
)

_LOGGER = logging.getLogger(__name__)

API_TIMEOUT = aiohttp.ClientTimeout(total=30)


class FeellooAuthManager:
    """Manages Firebase authentication and shared API session for Feelloo."""

    def __init__(self, hass: HomeAssistant, email: str, password: str) -> None:
        """Initialize the auth manager."""
        self._hass = hass
        self._email = email
        self._password = password
        self._id_token: str | None = None
        self._refresh_token: str | None = None
        self._session = async_get_clientsession(hass)
        self._auth_lock = asyncio.Lock()

    async def async_shutdown(self) -> None:
        """Shutdown — nothing to do for shared session."""
        pass

    async def _async_login(self) -> None:
        """Authenticate with Firebase and get tokens."""
        url = f"{FIREBASE_SIGNIN_URL}?key={FIREBASE_API_KEY}"
        payload = {
            "email": self._email,
            "password": self._password,
            "returnSecureToken": True,
        }
        try:
            async with self._session.post(url, json=payload, timeout=API_TIMEOUT) as resp:
                if resp.status == 401:
                    raise ConfigEntryAuthFailed("Invalid Feelloo credentials")
                if resp.status != 200:
                    raise UpdateFailed(f"Firebase login failed: {resp.status}")
                data = await resp.json()
                self._id_token = data.get("idToken")
                self._refresh_token = data.get("refreshToken")
                if not self._id_token:
                    raise UpdateFailed("Firebase login returned no idToken")
        except (aiohttp.ClientError, ValueError) as err:
            raise UpdateFailed(f"Firebase login error: {err}") from err
        except asyncio.TimeoutError as err:
            raise UpdateFailed(f"Firebase login timeout: {err}") from err

    async def _async_refresh_token(self) -> None:
        """Refresh the Firebase idToken using refreshToken."""
        if not self._refresh_token:
            _LOGGER.debug("No refresh token, performing full login")
            await self._async_login()
            return

        url = f"{FIREBASE_REFRESH_URL}?key={FIREBASE_API_KEY}"
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }
        try:
            async with self._session.post(url, data=payload, timeout=API_TIMEOUT) as resp:
                if resp.status != 200:
                    _LOGGER.warning("Token refresh failed (%s), falling back to login", resp.status)
                    await self._async_login()
                    return
                data = await resp.json()
                self._id_token = data.get("id_token")
                self._refresh_token = data.get("refresh_token")
                if not self._id_token:
                    _LOGGER.warning("Token refresh returned no id_token, falling back to login")
                    await self._async_login()
        except (aiohttp.ClientError, ValueError) as err:
            _LOGGER.warning("Token refresh error: %s, falling back to login", err)
            await self._async_login()
        except asyncio.TimeoutError as err:
            _LOGGER.warning("Token refresh timeout: %s, falling back to login", err)
            await self._async_login()

    async def async_ensure_token(self) -> None:
        """Ensure we have a valid token before making API calls."""
        async with self._auth_lock:
            if not self._id_token:
                await self._async_login()

    async def async_get_token(self) -> str:
        """Get a valid id token."""
        async with self._auth_lock:
            if not self._id_token:
                await self._async_login()
            if not self._id_token:
                raise UpdateFailed("No valid token available")
            return self._id_token

    async def async_refresh_and_get_token(self) -> str:
        """Refresh token and return new id token."""
        async with self._auth_lock:
            await self._async_refresh_token()
            if not self._id_token:
                raise UpdateFailed("No valid token after refresh")
            return self._id_token

    async def async_api_request(self, method: str, endpoint: str, json_payload: dict | None = None, params: dict | None = None):
        """Make an authenticated API request using the shared session."""
        token = await self.async_get_token()
        url = f"{BASE_URL}{endpoint}"
        headers = {"Authorization": f"Bearer {token}"}
        if json_payload is not None:
            headers["Content-Type"] = "application/json"

        try:
            async with self._session.request(method, url, headers=headers, json=json_payload, params=params, timeout=API_TIMEOUT) as resp:
                if resp.status == 401:
                    _LOGGER.debug("Received 401, refreshing token and retrying")
                    token = await self.async_refresh_and_get_token()
                    headers["Authorization"] = f"Bearer {token}"
                    async with self._session.request(method, url, headers=headers, json=json_payload, params=params, timeout=API_TIMEOUT) as resp2:
                        if resp2.status == 401:
                            raise ConfigEntryAuthFailed("API request failed after token refresh")
                        resp2.raise_for_status()
                        if resp2.status == 204:
                            return None
                        return await resp2.json()
                resp.raise_for_status()
                if resp.status == 204:
                    return None
                return await resp.json()
        except (aiohttp.ClientError, ValueError) as err:
            raise UpdateFailed(f"API request error: {err}") from err
        except asyncio.TimeoutError as err:
            raise UpdateFailed(f"API request timeout: {err}") from err


class FeellooMainCoordinator(DataUpdateCoordinator):
    """Coordinator for main cats data — polls /users/cats (interval configurable, default 5 minutes)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, auth: FeellooAuthManager) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.auth = auth
        self._cancel_token_refresh = None
        self._cancel_fast_polling_listen = None
        self._fast_polling_active: set[int] = set()
        self._fast_polling_timer: callable | None = None
        # Petite souris polling override (Spec 047 owner addition): transient,
        # in-memory flags — never persisted. The user's real preference lives
        # in entry.options, which the override never touches, so it is always
        # the "remembered" pre-mode state and survives restarts by itself.
        self._ps_override = False
        self._ps_override_cancelled = False

        # Polling control (Spec 047): resolve persisted settings. When polling
        # is disabled the coordinator runs with update_interval=None, which
        # means HA never schedules a periodic refresh (the startup first
        # refresh and manual refreshes still work).
        self.polling_enabled, self.polling_interval_minutes = get_polling_settings(entry)
        self.last_successful_fetch = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_main",
            update_interval=timedelta(minutes=self.polling_interval_minutes) if self.polling_enabled else None,
        )

    async def async_setup(self) -> None:
        """Set up the coordinator."""
        await self.auth.async_ensure_token()
        self._cancel_token_refresh = async_track_time_interval(
            self.hass,
            self._async_refresh_token_callback,
            TOKEN_REFRESH_INTERVAL,
        )
        self._cancel_fast_polling_listen = self.hass.bus.async_listen("feelloo_fast_polling", self._handle_fast_polling_event)
        await self.async_config_entry_first_refresh()
        # Restore fast polling state from API data after first refresh
        for cat in self.cats:
            cat_id = cat.get("cat_id")
            if cat_id is None:
                continue
            programmed = cat.get("geolocation", {}).get("petite_souris", {}).get("programmed", False)
            if programmed:
                self._fast_polling_active.add(cat_id)
            else:
                self._fast_polling_active.discard(cat_id)
        self._sync_fast_polling_timer()
        await self._async_setup_devices()

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        if self._cancel_token_refresh:
            self._cancel_token_refresh()
        if self._cancel_fast_polling_listen:
            self._cancel_fast_polling_listen()
        self._stop_fast_polling_timer()
        await super().async_shutdown()

    async def async_apply_polling_settings(self, enabled: bool, interval_minutes: int) -> None:
        """Apply polling settings at runtime, without a restart.

        Case table (Spec 047 §5):
        - enable, or interval change while enabled: update_interval is set to
          the new cadence and one debounced refresh (~10 s) is requested so
          the new cadence (and fresh data) applies immediately instead of
          waiting out the previously scheduled timer.
        - disable: update_interval becomes None; no refresh is forced (at
          most one already-scheduled fetch may still run, then nothing).
        - interval change while disabled: the value is stored and applied on
          the next enable; update_interval stays None.
        A manual call while the Petite Souris override is running cancels the
        override: an explicit user action always wins over the mode's
        temporary 1-minute boost (Spec 047 §4.2, edge case 1). The boost will
        not re-engage until the mode is deactivated and activated again.
        """
        if self._fast_polling_active:
            # Petite Souris still active: any manual polling change takes
            # control back from the temporary boost.
            if self._ps_override:
                _LOGGER.info(
                    "Manual polling change while Petite Souris is active: "
                    "temporary 1-minute polling override cancelled"
                )
            self._ps_override = False
            self._ps_override_cancelled = True
        else:
            self._ps_override = False
            self._ps_override_cancelled = False

        self.polling_enabled = enabled
        self.polling_interval_minutes = interval_minutes
        # Re-evaluate the fast polling timer under the new setting: disabling
        # stops a running timer, enabling may restart one while petite souris
        # is active.
        self._sync_fast_polling_timer()

        new_update_interval = timedelta(minutes=interval_minutes) if enabled else None
        if self.update_interval == new_update_interval:
            # Nothing observable changes — idempotent no-op.
            return
        self.update_interval = new_update_interval
        if new_update_interval is not None:
            # Enable or live cadence change: flush the pending schedule now
            # (debounced) instead of waiting out the previous timer.
            await self.async_request_refresh()

    @property
    def petite_souris_override(self) -> bool:
        """Return whether the Petite Souris 1-minute polling override runs."""
        return self._ps_override

    def _set_effective_polling(self, enabled: bool, interval_minutes: int) -> None:
        """Set the effective polling state without forcing a refresh.

        Used by the Petite Souris override: its transitions always happen
        inside a fetch (API-state sync) or right after one (the switch and
        set_petite_souris service paths already refresh), so the
        post-fetch rescheduling in DataUpdateCoordinator picks the new
        interval up naturally — no re-entrant refresh is needed.
        """
        self.polling_enabled = enabled
        self.polling_interval_minutes = interval_minutes
        self.update_interval = timedelta(minutes=interval_minutes) if enabled else None

    def _restore_user_polling_settings(self) -> None:
        """Restore polling from the user's saved preference (entry.options).

        Re-resolved live instead of snapshot at activation time, so changes
        the user made to their preference while the mode was active are
        honored (Spec 047 §4.2).
        """
        enabled, interval_minutes = get_polling_settings(self.entry)
        self._set_effective_polling(enabled, interval_minutes)

    @callback
    def _handle_fast_polling_event(self, event) -> None:
        """Handle fast polling enable/disable events from switch."""
        data = event.data
        cat_id = data.get("cat_id")
        enabled = bool(data.get("enabled"))
        if cat_id is None:
            return
        try:
            cat_id = int(cat_id)
        except (ValueError, TypeError):
            _LOGGER.warning("Invalid cat_id in fast polling event: %s", cat_id)
            return
        if enabled:
            self._fast_polling_active.add(cat_id)
        else:
            self._fast_polling_active.discard(cat_id)
        self._sync_fast_polling_timer()

    def _sync_fast_polling_timer(self) -> None:
        """Re-evaluate fast polling and the Petite Souris polling override.

        Called whenever the petite souris cat set changes (switch event,
        API-state sync inside every fetch, startup restore) and whenever
        polling settings change.
        """
        mode_active = bool(self._fast_polling_active)

        # Petite Souris polling override (Spec 047 §4.2, owner addition):
        # the mode needs 1-minute tracking, so while any cat has it
        # programmed the main coordinator temporarily polls every minute
        # regardless of the user's preference. The preference is never
        # modified here — it lives in entry.options and is re-resolved when
        # the mode ends, so mid-mode preference changes are honored.
        if mode_active and not self._ps_override and not self._ps_override_cancelled:
            self._ps_override = True
            self._set_effective_polling(True, PETITE_SOURIS_OVERRIDE_INTERVAL_MINUTES)
            _LOGGER.info(
                "Petite Souris active: temporary %s-minute polling override engaged "
                "(the saved polling preference will be restored when the mode ends)",
                PETITE_SOURIS_OVERRIDE_INTERVAL_MINUTES,
            )
        elif not mode_active and self._ps_override:
            self._ps_override = False
            self._restore_user_polling_settings()
            _LOGGER.info(
                "Petite Souris ended: polling settings restored from the saved preference"
            )
        if not mode_active:
            # The mode fully ended: a later activation may engage the
            # override again.
            self._ps_override_cancelled = False

        # Fast polling side timer: redundant while the override provides the
        # 1-minute cadence through update_interval (it would only duplicate
        # fetches); suppressed entirely while polling is disabled.
        if not self.polling_enabled:
            # Fast polling IS main-coordinator automatic polling: while
            # polling is disabled no fast-polling timer may run, even if
            # petite souris is programmed (API commands still work; only
            # local 1-minute tracking is suppressed).
            if self._fast_polling_timer:
                _LOGGER.info(
                    "Automatic polling disabled: stopping fast polling timer"
                )
                self._fast_polling_timer()
                self._fast_polling_timer = None
            elif self._fast_polling_active:
                _LOGGER.info(
                    "Automatic polling disabled: fast polling suppressed for %s cats",
                    len(self._fast_polling_active),
                )
            return
        if self._ps_override:
            if self._fast_polling_timer:
                _LOGGER.debug(
                    "Fast polling timer stopped: the Petite Souris override "
                    "provides 1-minute polling"
                )
                self._fast_polling_timer()
                self._fast_polling_timer = None
            return
        if self._fast_polling_active and not self._fast_polling_timer:
            _LOGGER.debug("Starting fast polling timer for %s cats", len(self._fast_polling_active))
            self._fast_polling_timer = async_track_time_interval(
                self.hass,
                lambda now: self.hass.add_job(self.async_request_refresh),
                FAST_POLLING_INTERVAL,
            )
        elif not self._fast_polling_active and self._fast_polling_timer:
            _LOGGER.debug("Stopping fast polling timer")
            self._fast_polling_timer()
            self._fast_polling_timer = None

    def _stop_fast_polling_timer(self) -> None:
        """Stop the fast polling timer."""
        if self._fast_polling_timer:
            self._fast_polling_timer()
            self._fast_polling_timer = None
        self._fast_polling_active.clear()

    async def _async_refresh_token_callback(self, now=None) -> None:
        """Callback to refresh the token periodically."""
        try:
            await self.auth.async_refresh_and_get_token()
        except UpdateFailed as err:
            _LOGGER.warning("Token refresh failed: %s", err)

    async def _async_update_data(self) -> dict:
        """Fetch cats data from /users/cats, then enrich each with /users/cats/{cat_id}."""
        _LOGGER.debug("Main coordinator fetch starting")
        data = await self.auth.async_api_request("GET", ENDPOINT_CATS)
        
        if data is None:
            raise UpdateFailed("Empty response from /users/cats")
        
        if isinstance(data, list):
            cats = data
        elif isinstance(data, dict):
            cats = data.get("cats", [])
        else:
            raise UpdateFailed(f"Unexpected cats data type: {type(data)}")
        
        if not isinstance(cats, list):
            raise UpdateFailed(f"Unexpected cats list type: {type(cats)}")
        
        enriched_cats = []
        for cat in cats:
            if not isinstance(cat, dict):
                _LOGGER.warning("Skipping non-dict cat entry: %s", type(cat))
                continue
            cat_id = cat.get("cat_id")
            if cat_id is not None:
                try:
                    detail = await self.auth.async_api_request(
                        "GET", ENDPOINT_CAT_DETAIL.format(cat_id=cat_id)
                    )
                    if detail and isinstance(detail, dict):
                        cat.update(detail)
                except UpdateFailed as err:
                    _LOGGER.warning("Failed to fetch cat detail for %s: %s", cat_id, err)
            enriched_cats.append(cat)
        
        # Fast polling auto-stop: sync _fast_polling_active with real programmed state
        for cat in enriched_cats:
            cat_id = cat.get("cat_id")
            if cat_id is None:
                continue
            programmed = cat.get("geolocation", {}).get("petite_souris", {}).get("programmed", False)
            if programmed:
                self._fast_polling_active.add(cat_id)
            else:
                self._fast_polling_active.discard(cat_id)
        self._sync_fast_polling_timer()

        # Success path only: exceptions raised above skip this assignment,
        # so the diagnostic sensor freezes at the last successful fetch.
        self.last_successful_fetch = dt_util.now()
        return {"cats": enriched_cats}

    async def _async_setup_devices(self) -> None:
        """Register devices in the device registry."""
        dev_reg = async_get_device_registry(self.hass)
        # Hub device hosting the per-account control entities (Spec 047).
        # Registered unconditionally, even with zero cats.
        dev_reg.async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="Feelloo",
            manufacturer="Feelloo",
            model="Account",
        )
        cats = self.data.get("cats", []) if self.data else []
        for cat in cats:
            if not isinstance(cat, dict):
                continue
            cat_uid = cat.get("_id")
            profile = cat.get("profile")
            name = profile.get("name", "Unknown Cat") if isinstance(profile, dict) else "Unknown Cat"
            if cat_uid:
                dev_reg.async_get_or_create(
                    config_entry_id=self.entry.entry_id,
                    identifiers={(DOMAIN, cat_uid)},
                    name=name,
                    manufacturer="Feelloo",
                    model="Cat Tracker",
                )

    async def async_ring_cat(self, cat_id: int) -> None:
        """Trigger the ring on a cat's tag — GET toggle (press once = start, press again = stop)."""
        await self.auth.async_api_request("GET", ENDPOINT_RING.format(cat_id=cat_id))

    async def async_set_petite_souris(self, cat_id: int, duration_hours: int) -> None:
        """Set petite souris mode for a cat."""
        await self.auth.async_api_request(
            "POST",
            ENDPOINT_PETITE_SOURIS.format(cat_id=cat_id),
            json_payload={"duration_hours": duration_hours},
        )

    @property
    def cats(self) -> list[dict]:
        """Return the list of cats."""
        return self.data.get("cats", []) if self.data else []

    @property
    def cats_by_id(self) -> dict[str, dict]:
        """Return a dict of cats by UID for efficient lookup."""
        return {cat.get("_id"): cat for cat in self.cats if cat.get("_id")}


class FeellooSecondaryCoordinator(DataUpdateCoordinator):
    """Shared base for the five secondary coordinators (Spec 048).

    Resolves the polling interval from the config entry options — the
    default per coordinator equals the fixed cadence shipped in 1.8.0,
    so an install with no options stored behaves exactly as before — and
    supports applying a new interval live, without a restart or reload.
    Subclasses keep their own fetch bodies and getters; only the
    interval resolution and live-apply semantics live here, so they
    exist in exactly one place.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, auth: FeellooAuthManager, key: str) -> None:
        """Initialize the coordinator with its configurable interval."""
        self.entry = entry
        self.auth = auth
        self.polling_interval_minutes = get_secondary_polling_intervals(entry)[key]
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{key}",
            update_interval=timedelta(minutes=self.polling_interval_minutes),
        )

    async def async_apply_polling_interval(self, interval_minutes: int) -> None:
        """Apply this coordinator's interval at runtime (no restart).

        Case table (Spec 048 §5): an unchanged value is an idempotent
        no-op; a changed value sets the new cadence and requests one
        debounced refresh, which cancels the pending old-cadence timer
        inside the refresh so the new cadence arms immediately (at most
        one already-scheduled fetch could otherwise fire at the old
        cadence first — the bounded straggler). Never a reload for
        options-only changes. No interaction with the Petite-Souris
        override: that touches the main coordinator only, and secondaries
        keep their cadences while it runs.
        """
        self.polling_interval_minutes = interval_minutes
        new_update_interval = timedelta(minutes=interval_minutes)
        if self.update_interval == new_update_interval:
            # Nothing observable changes — idempotent no-op.
            return
        self.update_interval = new_update_interval
        await self.async_request_refresh()


class FeellooActivityCoordinator(FeellooSecondaryCoordinator):
    """Coordinator for activity data — polls /users/cats/{cat_id}/activity (interval configurable, default 15 minutes)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, auth: FeellooAuthManager) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, entry, auth, "activity")

    async def _async_update_data(self) -> dict:
        """Fetch activity data for all cats."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        main_coordinator = entry_data.get("main")
        if not main_coordinator:
            _LOGGER.warning("Missing main coordinator reference in activity update, skipping")
            return {"activities": {}}
        cats = main_coordinator.cats
        today = dt_util.now().strftime("%Y-%m-%d")
        activities = {}

        for cat in cats:
            cat_id = cat.get("cat_id")
            cat_uid = cat.get("_id")
            if cat_id is None or cat_uid is None:
                continue
            try:
                activity = await self.auth.async_api_request(
                    "GET",
                    ENDPOINT_ACTIVITY.format(cat_id=cat_id),
                    params={"period_type": "day", "start_date": today},
                )
                activities[cat_uid] = activity
            except UpdateFailed:
                activities[cat_uid] = None

        return {"activities": activities}

    def get_activity(self, cat_uid: str) -> dict | None:
        """Get activity data for a specific cat."""
        if not self.data:
            return None
        return self.data.get("activities", {}).get(cat_uid)


class FeellooActivityWeekCoordinator(FeellooSecondaryCoordinator):
    """Coordinator for weekly activity data — polls /users/cats/{cat_id}/activity weekly (interval configurable, default 60 minutes)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, auth: FeellooAuthManager) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, entry, auth, "activity_week")

    async def _async_update_data(self) -> dict:
        """Fetch weekly activity data for all cats."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        main_coordinator = entry_data.get("main")
        if not main_coordinator:
            _LOGGER.warning("Missing main coordinator reference in activity week update, skipping")
            return {"activities": {}}
        cats = main_coordinator.cats
        now = dt_util.now()
        # Get Monday of current week
        monday = now - timedelta(days=now.weekday())
        start_date = monday.strftime("%Y-%m-%d")
        activities = {}

        for cat in cats:
            cat_id = cat.get("cat_id")
            cat_uid = cat.get("_id")
            if cat_id is None or cat_uid is None:
                continue
            try:
                activity = await self.auth.async_api_request(
                    "GET",
                    ENDPOINT_ACTIVITY.format(cat_id=cat_id),
                    params={"period_type": "week", "start_date": start_date},
                )
                activities[cat_uid] = activity
            except UpdateFailed:
                activities[cat_uid] = None

        return {"activities": activities}

    def get_activity(self, cat_uid: str) -> dict | None:
        """Get weekly activity data for a specific cat."""
        if not self.data:
            return None
        return self.data.get("activities", {}).get(cat_uid)


class FeellooActivityMonthCoordinator(FeellooSecondaryCoordinator):
    """Coordinator for monthly activity data — polls /users/cats/{cat_id}/activity monthly (interval configurable, default 360 minutes)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, auth: FeellooAuthManager) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, entry, auth, "activity_month")

    async def _async_update_data(self) -> dict:
        """Fetch monthly activity data for all cats."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        main_coordinator = entry_data.get("main")
        if not main_coordinator:
            _LOGGER.warning("Missing main coordinator reference in activity month update, skipping")
            return {"activities": {}}
        cats = main_coordinator.cats
        now = dt_util.now()
        # First day of current month
        first_day = now.replace(day=1)
        start_date = first_day.strftime("%Y-%m-%d")
        activities = {}

        for cat in cats:
            cat_id = cat.get("cat_id")
            cat_uid = cat.get("_id")
            if cat_id is None or cat_uid is None:
                continue
            try:
                activity = await self.auth.async_api_request(
                    "GET",
                    ENDPOINT_ACTIVITY.format(cat_id=cat_id),
                    params={"period_type": "month", "start_date": start_date},
                )
                activities[cat_uid] = activity
            except UpdateFailed:
                activities[cat_uid] = None

        return {"activities": activities}

    def get_activity(self, cat_uid: str) -> dict | None:
        """Get monthly activity data for a specific cat."""
        if not self.data:
            return None
        return self.data.get("activities", {}).get(cat_uid)


class FeellooTerritoryCoordinator(FeellooSecondaryCoordinator):
    """Coordinator for territory data — polls /users/cats/{cat_id}/territory/paths (interval configurable, default 15 minutes)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, auth: FeellooAuthManager) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, entry, auth, "territory")

    async def _async_update_data(self) -> dict:
        """Fetch territory paths for all cats."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        main_coordinator = entry_data.get("main")
        if not main_coordinator:
            _LOGGER.warning("Missing main coordinator reference in territory update, skipping")
            return {"paths": {}}
        cats = main_coordinator.cats
        paths_data = {}

        for cat in cats:
            cat_id = cat.get("cat_id")
            cat_uid = cat.get("_id")
            if cat_id is None or cat_uid is None:
                continue
            try:
                paths = await self.auth.async_api_request(
                    "GET",
                    ENDPOINT_TERRITORY_PATHS.format(cat_id=cat_id),
                )
                if not isinstance(paths, list):
                    paths = paths.get("paths", []) if isinstance(paths, dict) else []
                paths_data[cat_uid] = paths
            except UpdateFailed:
                paths_data[cat_uid] = []

        return {"paths": paths_data}

    def get_paths(self, cat_uid: str) -> list[dict]:
        """Get territory paths for a specific cat."""
        if not self.data:
            return []
        return self.data.get("paths", {}).get(cat_uid, [])

    def get_last_session(self, cat_uid: str) -> dict | None:
        """Get the most recent territory session for a cat."""
        paths = self.get_paths(cat_uid)
        if not paths:
            return None
        sorted_paths = sorted(
            paths,
            key=lambda x: x.get("start_date", ""),
            reverse=True,
        )
        return sorted_paths[0] if sorted_paths else None


class FeellooSessionCoordinator(FeellooSecondaryCoordinator):
    """Coordinator for territory session details — polls /users/cats/{cat_id}/territory/paths/{session_id} (interval configurable, default 30 minutes)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, auth: FeellooAuthManager) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, entry, auth, "session")

    async def _async_update_data(self) -> dict:
        """Fetch territory session details for all cats."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        territory_coordinator = entry_data.get("territory")
        main_coordinator = entry_data.get("main")
        
        if not territory_coordinator or not main_coordinator:
            _LOGGER.warning("Missing coordinator reference in session update, skipping")
            return {"sessions": {}}
        
        cats = main_coordinator.cats
        sessions = {}

        for cat in cats:
            cat_id = cat.get("cat_id")
            cat_uid = cat.get("_id")
            if cat_id is None or cat_uid is None:
                continue

            last_session = territory_coordinator.get_last_session(cat_uid)
            if not last_session:
                sessions[cat_uid] = None
                continue

            session_id = last_session.get("session_id")
            if not session_id:
                sessions[cat_uid] = None
                continue

            try:
                detail = await self.auth.async_api_request(
                    "GET",
                    ENDPOINT_TERRITORY_PATH.format(cat_id=cat_id, session_id=session_id),
                )
                sessions[cat_uid] = detail
            except UpdateFailed:
                sessions[cat_uid] = None

        return {"sessions": sessions}

    def get_session(self, cat_uid: str) -> dict | None:
        """Get session detail for a specific cat."""
        if not self.data:
            return None
        return self.data.get("sessions", {}).get(cat_uid)
