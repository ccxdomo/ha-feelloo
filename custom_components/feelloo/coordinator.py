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
    CATS_UPDATE_INTERVAL,
    ACTIVITY_UPDATE_INTERVAL,
    ACTIVITY_WEEK_UPDATE_INTERVAL,
    ACTIVITY_MONTH_UPDATE_INTERVAL,
    TERRITORY_UPDATE_INTERVAL,
    SESSION_UPDATE_INTERVAL,
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
    """Coordinator for main cats data — polls /users/cats every 5 minutes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, auth: FeellooAuthManager) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.auth = auth
        self._cancel_token_refresh = None
        self._cancel_fast_polling_listen = None
        self._fast_polling_active: set[int] = set()
        self._fast_polling_timer: callable | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_main",
            update_interval=CATS_UPDATE_INTERVAL,
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
        """Start or stop the fast polling timer based on active cats."""
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
        
        return {"cats": enriched_cats}

    async def _async_setup_devices(self) -> None:
        """Register devices in the device registry."""
        dev_reg = async_get_device_registry(self.hass)
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


class FeellooActivityCoordinator(DataUpdateCoordinator):
    """Coordinator for activity data — polls /users/cats/{cat_id}/activity every 15 minutes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, auth: FeellooAuthManager) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.auth = auth

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_activity",
            update_interval=ACTIVITY_UPDATE_INTERVAL,
        )

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


class FeellooActivityWeekCoordinator(DataUpdateCoordinator):
    """Coordinator for weekly activity data — polls every hour."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, auth: FeellooAuthManager) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.auth = auth

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_activity_week",
            update_interval=ACTIVITY_WEEK_UPDATE_INTERVAL,
        )

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


class FeellooActivityMonthCoordinator(DataUpdateCoordinator):
    """Coordinator for monthly activity data — polls every 6 hours."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, auth: FeellooAuthManager) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.auth = auth

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_activity_month",
            update_interval=ACTIVITY_MONTH_UPDATE_INTERVAL,
        )

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


class FeellooTerritoryCoordinator(DataUpdateCoordinator):
    """Coordinator for territory data — polls /users/cats/{cat_id}/territory/paths every 15 minutes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, auth: FeellooAuthManager) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.auth = auth

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_territory",
            update_interval=TERRITORY_UPDATE_INTERVAL,
        )

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


class FeellooSessionCoordinator(DataUpdateCoordinator):
    """Coordinator for territory session details — polls every 30 minutes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, auth: FeellooAuthManager) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.auth = auth

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_session",
            update_interval=SESSION_UPDATE_INTERVAL,
        )

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
