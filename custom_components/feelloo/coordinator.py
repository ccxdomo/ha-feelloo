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
    TOKEN_REFRESH_INTERVAL,
    CONF_EMAIL,
    CONF_PASSWORD,
    ENDPOINT_CATS,
    ENDPOINT_ACTIVITY,
    ENDPOINT_RING,
)

_LOGGER = logging.getLogger(__name__)


class FeellooCoordinator(DataUpdateCoordinator):
    """Coordinator to manage Feelloo data fetching."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self._email = entry.data[CONF_EMAIL]
        self._password = entry.data[CONF_PASSWORD]
        self._id_token: str | None = None
        self._refresh_token: str | None = None
        self._session = aiohttp.ClientSession()
        self._cancel_token_refresh = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=CATS_UPDATE_INTERVAL,
        )

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        if self._cancel_token_refresh:
            self._cancel_token_refresh()
        await self._session.close()
        await super().async_shutdown()

    async def async_setup(self) -> None:
        """Set up the coordinator — called manually from __init__.py."""
        await self._async_login()
        self._cancel_token_refresh = async_track_time_interval(
            self.hass,
            self._async_refresh_token_callback,
            TOKEN_REFRESH_INTERVAL,
        )
        await self._async_setup_devices()

    async def _async_refresh_token_callback(self, now=None) -> None:
        """Callback to refresh the token periodically."""
        await self._async_refresh_token()

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

    async def _async_ensure_token(self) -> None:
        """Ensure we have a valid token before making API calls."""
        if not self._id_token:
            await self._async_login()

    async def _async_api_request(self, method: str, endpoint: str, json_payload: dict | None = None):
        """Make an authenticated API request to Feelloo."""
        await self._async_ensure_token()
        url = f"{BASE_URL}{endpoint}"
        headers = {"Authorization": f"Bearer {self._id_token}"}

        try:
            async with self._session.request(method, url, headers=headers, json=json_payload) as resp:
                if resp.status == 401:
                    _LOGGER.debug("Received 401, refreshing token and retrying")
                    await self._async_refresh_token()
                    headers["Authorization"] = f"Bearer {self._id_token}"
                    async with self._session.request(method, url, headers=headers, json=json_payload) as resp2:
                        if resp2.status == 401:
                            raise UpdateFailed("API request failed after token refresh")
                        resp2.raise_for_status()
                        return await resp2.json()
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"API request error: {err}") from err

    async def _async_update_data(self) -> dict:
        """Fetch cats data."""
        data = await self._async_api_request("GET", ENDPOINT_CATS)
        cats = data if isinstance(data, list) else data.get("cats", [])
        # Fetch activity for each cat (every 15 min logic handled by caching)
        now = dt_util.utcnow()
        for cat in cats:
            cat_id = cat.get("cat_id")
            last_activity = cat.get("_last_activity_fetch")
            if cat_id is not None and (last_activity is None or (now - last_activity).total_seconds() > ACTIVITY_UPDATE_INTERVAL.total_seconds()):
                try:
                    activity = await self._async_api_request("GET", ENDPOINT_ACTIVITY.format(cat_id=cat_id))
                    cat["_activity"] = activity
                    cat["_last_activity_fetch"] = now
                except UpdateFailed:
                    cat["_activity"] = cat.get("_activity")
                    cat["_last_activity_fetch"] = cat.get("_last_activity_fetch")
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
        """Trigger the ring on a cat's tag."""
        await self._async_api_request("POST", ENDPOINT_RING.format(cat_id=cat_id), json_payload={})

    @property
    def cats(self) -> list[dict]:
        """Return the list of cats."""
        return self.data.get("cats", []) if self.data else []
