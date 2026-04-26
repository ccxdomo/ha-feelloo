"""DataUpdateCoordinator for Feelloo."""

from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    FIREBASE_API_KEY,
    FIREBASE_SIGNIN_URL,
    FIREBASE_REFRESH_URL,
    BASE_URL,
    CATS_UPDATE_INTERVAL,
    ACTIVITY_UPDATE_INTERVAL,
    TERRITORY_UPDATE_INTERVAL,
    TOKEN_REFRESH_INTERVAL,
    CONF_EMAIL,
    CONF_PASSWORD,
    ENDPOINT_CATS,
    ENDPOINT_ACTIVITY,
    ENDPOINT_TERRITORY_PATHS,
    ENDPOINT_TERRITORY,
    ENDPOINT_RING,
    ENDPOINT_PETITE_SOURIS,
)

_LOGGER = logging.getLogger(__name__)


class FeellooAuthManager:
    """Manages Firebase authentication and shared API session for Feelloo."""

    def __init__(self, email: str, password: str) -> None:
        """Initialize the auth manager."""
        self._email = email
        self._password = password
        self._id_token: str | None = None
        self._refresh_token: str | None = None
        self._session = aiohttp.ClientSession()

    async def async_shutdown(self) -> None:
        """Close the shared session."""
        await self._session.close()

    async def _async_login(self) -> None:
        """Authenticate with Firebase and get tokens."""
        url = f"{FIREBASE_SIGNIN_URL}?key={FIREBASE_API_KEY}"
        payload = {
            "email": self._email,
            "password": self._password,
            "returnSecureToken": True,
        }
        try:
            async with self._session.post(url, json=payload) as resp:
                if resp.status != 200:
                    raise UpdateFailed(f"Firebase login failed: {resp.status}")
                data = await resp.json()
                self._id_token = data.get("idToken")
                self._refresh_token = data.get("refreshToken")
                if not self._id_token:
                    raise UpdateFailed("Firebase login returned no idToken")
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Firebase login error: {err}") from err

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
            async with self._session.post(url, data=payload) as resp:
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
        except aiohttp.ClientError as err:
            _LOGGER.warning("Token refresh error: %s, falling back to login", err)
            await self._async_login()

    async def async_ensure_token(self) -> None:
        """Ensure we have a valid token before making API calls."""
        if not self._id_token:
            await self._async_login()

    async def async_get_token(self) -> str:
        """Get a valid id token."""
        await self.async_ensure_token()
        if not self._id_token:
            raise UpdateFailed("No valid token available")
        return self._id_token

    async def async_refresh_and_get_token(self) -> str:
        """Refresh token and return new id token."""
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
            async with self._session.request(method, url, headers=headers, json=json_payload, params=params) as resp:
                if resp.status == 401:
                    _LOGGER.debug("Received 401, refreshing token and retrying")
                    token = await self.async_refresh_and_get_token()
                    headers["Authorization"] = f"Bearer {token}"
                    async with self._session.request(method, url, headers=headers, json=json_payload, params=params) as resp2:
                        if resp2.status == 401:
                            raise UpdateFailed("API request failed after token refresh")
                        resp2.raise_for_status()
                        if resp2.status == 204:
                            return None
                        return await resp2.json()
                resp.raise_for_status()
                if resp.status == 204:
                    return None
                return await resp.json()
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"API request error: {err}") from err


class FeellooMainCoordinator(DataUpdateCoordinator):
    """Coordinator for main cats data — polls /users/cats every 5 minutes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, auth: FeellooAuthManager) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.auth = auth
        self._cancel_token_refresh = None

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
        await self.async_config_entry_first_refresh()
        await self._async_setup_devices()

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        if self._cancel_token_refresh:
            self._cancel_token_refresh()
        await super().async_shutdown()

    async def _async_refresh_token_callback(self, now=None) -> None:
        """Callback to refresh the token periodically."""
        try:
            await self.auth.async_refresh_and_get_token()
        except UpdateFailed as err:
            _LOGGER.warning("Token refresh failed: %s", err)

    async def _async_update_data(self) -> dict:
        """Fetch cats data from /users/cats."""
        data = await self.auth.async_api_request("GET", ENDPOINT_CATS)
        cats = data if isinstance(data, list) else data.get("cats", [])
        return {"cats": cats}

    async def _async_setup_devices(self) -> None:
        """Register devices in the device registry."""
        dev_reg = async_get_device_registry(self.hass)
        cats = self.data.get("cats", []) if self.data else []
        for cat in cats:
            cat_uid = cat.get("_id")
            name = cat.get("profile", {}).get("name", "Unknown Cat")
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

    @property
    def cats(self) -> list[dict]:
        """Return the list of cats."""
        return self.data.get("cats", []) if self.data else []


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
        main_coordinator: FeellooMainCoordinator = self.hass.data[DOMAIN][self.entry.entry_id]["main"]
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
        main_coordinator: FeellooMainCoordinator = self.hass.data[DOMAIN][self.entry.entry_id]["main"]
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
