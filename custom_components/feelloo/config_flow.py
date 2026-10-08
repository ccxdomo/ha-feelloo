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
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_POLLING_ENABLED,
    CONF_POLLING_INTERVAL,
    CONF_POLLING_INTERVAL_ACTIVITY,
    CONF_POLLING_INTERVAL_ACTIVITY_WEEK,
    CONF_POLLING_INTERVAL_ACTIVITY_MONTH,
    CONF_POLLING_INTERVAL_TERRITORY,
    CONF_POLLING_INTERVAL_SESSION,
    POLLING_INTERVAL_MIN,
    POLLING_INTERVAL_MAX,
    FIREBASE_API_KEY,
    FIREBASE_SIGNIN_URL,
    get_polling_settings,
    get_secondary_polling_intervals,
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
        # Modern OptionsFlow (HA >= 2026.9) exposes a read-only `config_entry`
        # property resolved from hass.config_entries - no need to pass it here.
        return FeellooOptionsFlowHandler()


class FeellooOptionsFlowHandler(OptionsFlow):
    """Handle options flow for Feelloo."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        current_email = self.config_entry.data.get(CONF_EMAIL, "")
        current_enabled, current_interval = get_polling_settings(self.config_entry)
        current_secondary = get_secondary_polling_intervals(self.config_entry)

        if user_input is not None:
            new_email = user_input.get(CONF_EMAIL, current_email).strip().casefold()
            # Blank password = keep current credentials.
            new_password = user_input.get(CONF_PASSWORD, "")
            credentials_changed = new_email != current_email or bool(new_password)
            new_options = {
                **self.config_entry.options,
                CONF_POLLING_ENABLED: user_input.get(CONF_POLLING_ENABLED, current_enabled),
                CONF_POLLING_INTERVAL: user_input.get(CONF_POLLING_INTERVAL, current_interval),
                CONF_POLLING_INTERVAL_ACTIVITY: user_input.get(
                    CONF_POLLING_INTERVAL_ACTIVITY, current_secondary["activity"]
                ),
                CONF_POLLING_INTERVAL_ACTIVITY_WEEK: user_input.get(
                    CONF_POLLING_INTERVAL_ACTIVITY_WEEK, current_secondary["activity_week"]
                ),
                CONF_POLLING_INTERVAL_ACTIVITY_MONTH: user_input.get(
                    CONF_POLLING_INTERVAL_ACTIVITY_MONTH, current_secondary["activity_month"]
                ),
                CONF_POLLING_INTERVAL_TERRITORY: user_input.get(
                    CONF_POLLING_INTERVAL_TERRITORY, current_secondary["territory"]
                ),
                CONF_POLLING_INTERVAL_SESSION: user_input.get(
                    CONF_POLLING_INTERVAL_SESSION, current_secondary["session"]
                ),
            }

            if credentials_changed and not new_password:
                # Email changed without a password: credentials cannot be
                # validated, so refuse the submission.
                errors["base"] = "password_required"
            elif credentials_changed:
                valid, error_key = await _async_test_credentials(self.hass, new_email, new_password)
                if not valid:
                    errors["base"] = error_key or "invalid_auth"
                else:
                    # Update credentials and polling settings in one call.
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data={CONF_EMAIL: new_email, CONF_PASSWORD: new_password},
                        options=new_options,
                    )
                    # create_entry data is persisted by HA as the entry options
                    # (an empty dict would wipe them), so pass the merged options.
                    return self.async_create_entry(title=new_email, data=new_options)
            else:
                # Polling-only change: no credential validation, no entry.data change.
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    options=new_options,
                )
                return self.async_create_entry(title=new_email, data=new_options)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_EMAIL, default=current_email
                    ): str,
                    vol.Optional(CONF_PASSWORD, default=""): str,
                    vol.Optional(
                        CONF_POLLING_ENABLED, default=current_enabled
                    ): cv.boolean,
                    vol.Optional(
                        CONF_POLLING_INTERVAL, default=current_interval
                    ): vol.All(vol.Coerce(int), vol.Range(min=POLLING_INTERVAL_MIN, max=POLLING_INTERVAL_MAX)),
                    vol.Optional(
                        CONF_POLLING_INTERVAL_ACTIVITY, default=current_secondary["activity"]
                    ): vol.All(vol.Coerce(int), vol.Range(min=POLLING_INTERVAL_MIN, max=POLLING_INTERVAL_MAX)),
                    vol.Optional(
                        CONF_POLLING_INTERVAL_ACTIVITY_WEEK, default=current_secondary["activity_week"]
                    ): vol.All(vol.Coerce(int), vol.Range(min=POLLING_INTERVAL_MIN, max=POLLING_INTERVAL_MAX)),
                    vol.Optional(
                        CONF_POLLING_INTERVAL_ACTIVITY_MONTH, default=current_secondary["activity_month"]
                    ): vol.All(vol.Coerce(int), vol.Range(min=POLLING_INTERVAL_MIN, max=POLLING_INTERVAL_MAX)),
                    vol.Optional(
                        CONF_POLLING_INTERVAL_TERRITORY, default=current_secondary["territory"]
                    ): vol.All(vol.Coerce(int), vol.Range(min=POLLING_INTERVAL_MIN, max=POLLING_INTERVAL_MAX)),
                    vol.Optional(
                        CONF_POLLING_INTERVAL_SESSION, default=current_secondary["session"]
                    ): vol.All(vol.Coerce(int), vol.Range(min=POLLING_INTERVAL_MIN, max=POLLING_INTERVAL_MAX)),
                }
            ),
            errors=errors,
        )
