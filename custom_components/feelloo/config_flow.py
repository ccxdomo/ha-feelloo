"""Config flow for Feelloo integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigEntry, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    CONF_EMAIL,
    CONF_PASSWORD,
    FIREBASE_API_KEY,
    FIREBASE_SIGNIN_URL,
)

_LOGGER = logging.getLogger(__name__)

AUTH_TIMEOUT = aiohttp.ClientTimeout(total=30)

AUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def _async_test_credentials(hass, email: str, password: str) -> tuple[bool, str | None]:
    """Test Firebase credentials.
    
    Returns (success, error_key) where error_key is None on success,
    or 'cannot_connect', 'invalid_auth' on failure.
    """
    url = f"{FIREBASE_SIGNIN_URL}?key={FIREBASE_API_KEY}"
    payload = {
        "email": email,
        "password": password,
        "returnSecureToken": True,
    }
    session = async_get_clientsession(hass)
    try:
        async with session.post(url, json=payload, timeout=AUTH_TIMEOUT) as resp:
            if resp.status == 200:
                return True, None
            try:
                data = await resp.json()
                error = data.get("error", {}).get("message", "")
                _LOGGER.debug("Firebase auth error: %s", error)
            except Exception:
                error = ""
            if "INVALID_PASSWORD" in error or "EMAIL_NOT_FOUND" in error or "INVALID_EMAIL" in error:
                return False, "invalid_auth"
            return False, "cannot_connect"
    except asyncio.TimeoutError:
        _LOGGER.warning("Firebase auth timeout for %s", email)
        return False, "cannot_connect"
    except aiohttp.ClientError as err:
        _LOGGER.warning("Firebase auth connection error: %s", err)
        return False, "cannot_connect"


class FeellooConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Feelloo."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip().casefold()
            password = user_input[CONF_PASSWORD]

            valid, error_key = await _async_test_credentials(self.hass, email, password)
            if valid:
                await self.async_set_unique_id(email)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=email,
                    data={CONF_EMAIL: email, CONF_PASSWORD: password},
                )
            errors["base"] = error_key or "invalid_auth"

        return self.async_show_form(
            step_id="user",
            data_schema=AUTH_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> FeellooOptionsFlowHandler:
        """Get the options flow for this handler."""
        return FeellooOptionsFlowHandler(config_entry)


class FeellooOptionsFlowHandler(OptionsFlow):
    """Handle options flow for Feelloo."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip().casefold()
            password = user_input[CONF_PASSWORD]

            valid, error_key = await _async_test_credentials(self.hass, email, password)
            if valid:
                # Update config entry data with new credentials
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={CONF_EMAIL: email, CONF_PASSWORD: password},
                )
                return self.async_create_entry(title=email, data={})
            errors["base"] = error_key or "invalid_auth"

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_EMAIL, default=self.config_entry.data.get(CONF_EMAIL)
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )
