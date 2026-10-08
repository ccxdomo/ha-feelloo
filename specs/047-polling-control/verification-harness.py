#!/usr/bin/env python3
"""Spec 047 — local verification harness for ha-feelloo.

The repo has no test infrastructure and no Home Assistant is installed on
this host. This harness stubs `homeassistant`, `aiohttp` and `voluptuous`
with faithful miniatures of the semantics verified from HA core 2026.9.0
source (helpers/update_coordinator.py, config_entries.py), imports every
touched module, and exercises the contract's logic requirements:

  - get_polling_settings resolver table (contract §2.2)
  - C1 constructor resolution + defaults == 1.7.5 behaviour
  - C2 startup first refresh with polling disabled
  - §4.2 Petite Souris polling override (engage/restore, manual-wins latch,
    side-timer suppression, restart reconstruction, live re-resolution)
  - C4 last_successful_fetch success-only semantics
  - C5 async_apply_polling_settings case table + §5.2 straggler bound
  - C8/C9 update listener (options live-apply vs credentials reload)
  - C12 options flow (polling-only, password_required, credentials paths)
  - §6 refresh button (main first, error surfacing, partial failures)
  - §7.2 config entities (apply-then-persist order, validation)
  - §8 entity surface (unique_ids, categories, diagnostic sensor)
  - §9 last-known-value structure (no refresh -> no failure -> available)

Run: python3 specs/047-polling-control/verification-harness.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import types
from datetime import datetime, timedelta, timezone

REPO = "/home/emc/.openclaw/workspace-codepilot/ha-feelloo"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond, note: str = "") -> None:
    ok = bool(cond)
    RESULTS.append((name, ok, note))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {note}" if note else ""))


# ---------------------------------------------------------------------------
# Stub modules (registered in sys.modules before importing the integration)
# ---------------------------------------------------------------------------

class _FakeHass:
    def __init__(self):
        self.data = {}
        self.bus = _FakeBus()
        self.config_entries = _FakeConfigEntries()
        self.device_registry = _FakeDeviceRegistry()
        self.entity_registry = _FakeEntityRegistry()
        self.interval_timers = []          # async_track_time_interval calls
        self.is_stopping = False
        self._session = _FakeSession()

    def create_task(self, coro):
        return asyncio.ensure_future(coro)


class _FakeBus:
    def __init__(self):
        self.listeners = {}

    def async_listen(self, event_type, handler):
        self.listeners.setdefault(event_type, []).append(handler)
        return lambda: self.listeners.get(event_type, []).remove(handler)

    def async_fire(self, event_type, data=None):
        for handler in self.listeners.get(event_type, []):
            handler(types.SimpleNamespace(data=data))


class _FakeConfigEntries:
    def __init__(self):
        self.updates = []      # (entry, kwargs)
        self.reloads = []      # entry_ids

    def async_update_entry(self, entry, **kwargs):
        self.updates.append((entry, kwargs))
        if "data" in kwargs:
            entry.data = dict(kwargs["data"])
        if "options" in kwargs:
            entry.options = dict(kwargs["options"])
        return True

    async def async_reload(self, entry_id):
        self.reloads.append(entry_id)


class _FakeDeviceRegistry:
    def __init__(self):
        self.devices = []

    def async_get_or_create(self, **kwargs):
        self.devices.append(kwargs)
        return kwargs


class _FakeIntervalTimer:
    def __init__(self, action, interval):
        self.action = action
        self.interval = interval
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class _FakeSession:
    def __init__(self):
        self.post_responses = []   # callable(url, json) -> _FakeResponse
        self.posted = []            # urls actually POSTed

    def post(self, url, json=None, data=None, timeout=None):
        self.posted.append(url)
        responder = self.post_responses.pop(0)
        return responder(url, json or data)


class _FakeResponse:
    def __init__(self, status, payload=None):
        self.status = status
        self._payload = payload or {}

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _async_get_clientsession(hass):
    return hass._session


def _async_track_time_interval(hass, action, interval):
    timer = _FakeIntervalTimer(action, interval)
    hass.interval_timers.append(timer)
    return timer.cancel


def _async_get_device_registry(hass):
    return hass.device_registry


class _FakeEntityRegistry:
    """Miniature of the entity registry: records translation_key updates."""

    def __init__(self):
        self.entries = {}
        self.updates = []

    def async_get(self, entity_id):
        return self.entries.get(entity_id)

    def async_update_entity(self, entity_id, **kwargs):
        self.updates.append((entity_id, dict(kwargs)))
        entry = self.entries.get(entity_id)
        if entry is not None:
            for key, value in kwargs.items():
                setattr(entry, key, value)


def _async_get_entity_registry(hass):
    return hass.entity_registry


# --- update_coordinator miniature (semantics verified from HA 2026.9.0) ----

class _FakePendingTimer:
    """Models the loop timer HA arms in _schedule_refresh."""

    def __init__(self, coordinator, interval):
        self.coordinator = coordinator
        self.interval = interval
        self.cancelled = False
        self.fired = 0

    async def fire(self):
        if self.cancelled:
            return
        self.fired += 1
        self.coordinator._pending_timer = None
        await self.coordinator._async_refresh()


class _FakeDataUpdateCoordinator:
    """Faithful miniature of HA 2026.9 DataUpdateCoordinator polling core.

    Verified against homeassistant/helpers/update_coordinator.py (2026.9.0):
    - update_interval is a plain settable property (no reschedule on set).
    - _schedule_refresh returns immediately when update_interval is None.
    - _async_refresh ends with _schedule_refresh (if listeners exist), so a
      pending timer may fire once after disable, then nothing is re-armed.
    - async_request_refresh never raises; failures flip last_update_success.
    """

    def __init__(self, hass, logger, *, name, update_interval=None):
        self.hass = hass
        self.logger = logger
        self.name = name
        self._update_interval = update_interval
        self.data = None
        self.last_update_success = True
        self.last_exception = None
        self._listeners = []
        self.refresh_count = 0
        self.first_refresh_called = False
        self._pending_timer = None

    @property
    def update_interval(self):
        return self._update_interval

    @update_interval.setter
    def update_interval(self, value):
        self._update_interval = value

    def async_add_listener(self, update_callback):
        self._listeners.append(update_callback)
        return lambda: self._listeners.remove(update_callback)

    def async_update_listeners(self):
        for cb in list(self._listeners):
            cb()

    def _schedule_refresh(self):
        if self._update_interval is None:
            return
        self._pending_timer = _FakePendingTimer(self, self._update_interval)

    async def _async_update_data(self):
        raise NotImplementedError

    async def _async_refresh(self):
        if self._pending_timer:
            self._pending_timer.cancelled = True
            self._pending_timer = None
        self.refresh_count += 1
        try:
            new_data = await self._async_update_data()
        except Exception as err:  # noqa: BLE001 — mirrors HA catch-all
            self.last_update_success = False
            self.last_exception = err
        else:
            self.data = new_data
            self.last_update_success = True
            self.last_exception = None
        if self._listeners:
            self._schedule_refresh()
        self.async_update_listeners()

    async def async_config_entry_first_refresh(self):
        self.first_refresh_called = True
        await self._async_refresh()

    async def async_request_refresh(self):
        await self._async_refresh()


class _FakeCoordinatorEntity:
    """Miniature of CoordinatorEntity: available == last_update_success."""

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.hass = None
        self._on_remove = []
        self.written_states = 0

    async def async_added_to_hass(self):
        pass

    def async_on_remove(self, cb):
        self._on_remove.append(cb)

    def async_write_ha_state(self):
        self.written_states += 1

    @property
    def available(self):
        return self.coordinator.last_update_success


class _Entity:
    """Tiny Entity base resolving _attr_* for the attributes we assert on."""

    _ATTRS = (
        "unique_id", "has_entity_name", "translation_key", "icon",
        "entity_category", "device_class", "native_unit_of_measurement",
        "native_min_value", "native_max_value", "native_step", "mode",
    )

    def __init__(self):
        self.hass = None
        self._on_remove = []
        self.written_states = 0

    async def async_added_to_hass(self):
        pass

    def async_on_remove(self, cb):
        self._on_remove.append(cb)

    def async_write_ha_state(self):
        self.written_states += 1

    def __getattr__(self, name):
        if name in _Entity._ATTRS:
            return getattr(self, f"_attr_{name}", None)
        # Real HA entities do not call super().__init__(); lazily create the
        # harness bookkeeping attributes on first access instead.
        if name == "written_states":
            self.written_states = 0
            return 0
        if name == "_on_remove":
            self._on_remove = []
            return []
        raise AttributeError(name)


def _callback(fn):
    return fn


# --- exceptions / constants ------------------------------------------------

class _HomeAssistantError(Exception):
    pass


class _ConfigEntryAuthFailed(_HomeAssistantError):
    pass


class _UpdateFailed(_HomeAssistantError):
    pass


class _EntityCategory:
    CONFIG = "config"
    DIAGNOSTIC = "diagnostic"


class _Platform:
    BINARY_SENSOR = "binary_sensor"
    SENSOR = "sensor"
    BUTTON = "button"
    DEVICE_TRACKER = "device_tracker"
    SWITCH = "switch"
    NUMBER = "number"


class _SensorDeviceClass:
    BATTERY = "battery"
    TIMESTAMP = "timestamp"


class _SensorStateClass:
    MEASUREMENT = "measurement"


# --- config flow machinery --------------------------------------------------

class _OptionsFlow:
    def __init__(self):
        self._config_entry = None
        self.hass = None

    @property
    def config_entry(self):
        return self._config_entry

    @config_entry.setter
    def config_entry(self, value):
        self._config_entry = value

    def async_show_form(self, step_id, data_schema=None, errors=None):
        return {"type": "form", "step_id": step_id, "data_schema": data_schema,
                "errors": errors or {}}

    def async_create_entry(self, title=None, data=None):
        return {"type": "create_entry", "title": title, "data": data}


class _ConfigFlow:
    VERSION = 1

    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.domain = domain

    def __init__(self):
        self.hass = None


class _ConfigEntry:
    pass


# --- voluptuous / aiohttp stubs ---------------------------------------------

class _Marker:
    def __init__(self, key, default=None):
        self.key = key
        self.default = default

    def __hash__(self):
        return hash(self.key)

    def __eq__(self, other):
        if isinstance(other, str):
            return self.key == other
        return isinstance(other, _Marker) and self.key == other.key


class _Required(_Marker):
    pass


class _Optional(_Marker):
    pass


class _All:
    def __init__(self, *validators):
        self.validators = validators


class _Coerce:
    def __init__(self, t):
        self.t = t


class _Range:
    def __init__(self, min=None, max=None):
        self.min = min
        self.max = max


class _Schema:
    def __init__(self, schema):
        self.schema = schema


class _ClientTimeout:
    def __init__(self, total=None):
        self.total = total


class _ClientError(Exception):
    pass


def _install_stubs() -> None:
    def module(name, **attrs):
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        sys.modules[name] = mod
        return mod

    module("homeassistant")
    module("homeassistant.core", HomeAssistant=_FakeHass, callback=_callback)
    module("homeassistant.config_entries", ConfigFlow=_ConfigFlow,
           ConfigEntry=_ConfigEntry, OptionsFlow=_OptionsFlow)
    module("homeassistant.data_entry_flow", FlowResult=dict)
    module("homeassistant.const", EntityCategory=_EntityCategory, Platform=_Platform)
    module("homeassistant.exceptions", HomeAssistantError=_HomeAssistantError,
           ConfigEntryAuthFailed=_ConfigEntryAuthFailed)
    module("homeassistant.helpers")
    module("homeassistant.helpers.config_validation",
           boolean=lambda v: v, positive_int=lambda v: int(v))
    module("homeassistant.helpers.aiohttp_client",
           async_get_clientsession=_async_get_clientsession)
    module("homeassistant.helpers.device_registry",
           async_get=_async_get_device_registry)
    module("homeassistant.helpers.entity_registry",
           async_get=_async_get_entity_registry)
    module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    module("homeassistant.helpers.event",
           async_track_time_interval=_async_track_time_interval)
    module("homeassistant.helpers.update_coordinator",
           DataUpdateCoordinator=_FakeDataUpdateCoordinator,
           CoordinatorEntity=_FakeCoordinatorEntity,
           UpdateFailed=_UpdateFailed)
    module("homeassistant.components")
    module("homeassistant.components.switch", SwitchEntity=_Entity)
    module("homeassistant.components.number", NumberEntity=_Entity)
    module("homeassistant.components.button", ButtonEntity=_Entity)
    module("homeassistant.components.sensor", SensorEntity=_Entity,
           SensorDeviceClass=_SensorDeviceClass,
           SensorStateClass=_SensorStateClass)
    module("homeassistant.util")
    module("homeassistant.util.dt",
           now=lambda: datetime.now(timezone.utc),
           utcnow=lambda: datetime.now(timezone.utc))
    module("aiohttp", ClientTimeout=_ClientTimeout, ClientError=_ClientError)
    module("voluptuous", Schema=_Schema, Required=_Required, Optional=_Optional,
           All=_All, Coerce=_Coerce, Range=_Range)

    sys.path.insert(0, REPO)


# ---------------------------------------------------------------------------
# Fakes for the integration's own objects
# ---------------------------------------------------------------------------

class FakeEntry:
    def __init__(self, data=None, options=None, unique_id=None, entry_id="test_entry_id"):
        self.data = dict(data or {})
        self.options = dict(options or {})
        self.unique_id = unique_id
        self.entry_id = entry_id
        self.pref_disable_polling = False
        self.update_listeners = []

    def add_update_listener(self, cb):
        self.update_listeners.append(cb)
        return lambda: self.update_listeners.remove(cb)

    def async_on_unload(self, cb):
        pass


class FakeAuth:
    """Scripted auth manager for the main coordinator."""

    def __init__(self, cats):
        self.cats = cats
        self.fail = False
        self.calls = []

    async def async_ensure_token(self):
        pass

    async def async_refresh_and_get_token(self):
        return "token"

    async def async_api_request(self, method, endpoint, json_payload=None, params=None):
        self.calls.append((method, endpoint))
        if self.fail:
            raise _UpdateFailed("scripted fetch failure")
        if endpoint == "/users/cats":
            return {"cats": self.cats}
        return {"detail": True}


class MockSecondary:
    def __init__(self, name, fail=False):
        self.name = name
        self.fail = fail
        self.refreshes = 0

    async def async_request_refresh(self):
        self.refreshes += 1
        if self.fail:
            raise RuntimeError(f"{self.name} fetch failed")


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


CATS = [{
    "_id": "cat_uid_1",
    "cat_id": 7,
    "profile": {"name": "Moustache"},
    "geolocation": {"petite_souris": {"programmed": False}},
}]


def make_coordinator(hass, entry, auth):
    sys.modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator  # noqa
    from custom_components.feelloo.coordinator import FeellooMainCoordinator
    coord = FeellooMainCoordinator(hass, entry, auth)
    # Model the CoordinatorEntity subscribers that always exist in production
    coord.async_add_listener(lambda: None)
    return coord


async def setup_coordinator(options=None, cats=None, unique_id="owner@example.com"):
    hass = _FakeHass()
    entry = FakeEntry(
        data={"email": "owner@example.com", "password": "secret"},
        options=options or {},
        unique_id=unique_id,
    )
    auth = FakeAuth(cats or CATS)
    coord = make_coordinator(hass, entry, auth)
    return hass, entry, auth, coord


# ---------------------------------------------------------------------------
# Test suites
# ---------------------------------------------------------------------------

def test_resolver():
    from custom_components.feelloo.const import (
        CATS_UPDATE_INTERVAL, DEFAULT_POLLING_ENABLED, DEFAULT_POLLING_INTERVAL,
        POLLING_INTERVAL_MAX, POLLING_INTERVAL_MIN, get_polling_settings,
    )

    def entry_with(options):
        return FakeEntry(options=options)

    check("resolver: no options -> (True, 5) == 1.7.5 defaults",
          get_polling_settings(entry_with({})) == (True, 5))
    check("resolver: default interval equals CATS_UPDATE_INTERVAL (5 min)",
          timedelta(minutes=get_polling_settings(entry_with({}))[1])
          == CATS_UPDATE_INTERVAL,
          f"DEFAULT_POLLING_INTERVAL={DEFAULT_POLLING_INTERVAL}")
    check("resolver: missing enabled -> default True", 
          get_polling_settings(entry_with({"polling_interval": 9}))[0] is True)
    check("resolver: enabled False preserved",
          get_polling_settings(entry_with({"polling_enabled": False})) == (False, 5))
    check("resolver: interval 10",
          get_polling_settings(entry_with({"polling_interval": 10})) == (True, 10))
    check("resolver: bounds min 1",
          get_polling_settings(entry_with({"polling_interval": POLLING_INTERVAL_MIN})) == (True, 1))
    check("resolver: bounds max 1440",
          get_polling_settings(entry_with({"polling_interval": POLLING_INTERVAL_MAX})) == (True, 1440))
    check("resolver: below min -> default (not clamped)",
          get_polling_settings(entry_with({"polling_interval": 0})) == (True, 5))
    check("resolver: above max -> default (not clamped)",
          get_polling_settings(entry_with({"polling_interval": 5000})) == (True, 5))
    check("resolver: numeric string coerced",
          get_polling_settings(entry_with({"polling_interval": "10"})) == (True, 10))
    check("resolver: garbage string -> default",
          get_polling_settings(entry_with({"polling_interval": "abc"})) == (True, 5))
    check("resolver: None -> default",
          get_polling_settings(entry_with({"polling_interval": None})) == (True, 5))
    check("resolver: non-bool enabled -> default",
          get_polling_settings(entry_with({"polling_enabled": "yes"})) == (True, 5),
          "present-but-not-bool falls back to DEFAULT_POLLING_ENABLED")
    check("resolver: both keys",
          get_polling_settings(entry_with({"polling_enabled": False,
                                           "polling_interval": 30})) == (False, 30))
    check("resolver: entry without options attribute",
          get_polling_settings(object()) == (True, DEFAULT_POLLING_ENABLED, )[:1] + (DEFAULT_POLLING_INTERVAL,))
    check("resolver: options None -> defaults",
          get_polling_settings(FakeEntry(options=None)) == (True, 5))


async def test_constructor():
    from custom_components.feelloo.const import CATS_UPDATE_INTERVAL
    hass, entry, auth, coord = await setup_coordinator(options={})
    check("C1: defaults -> update_interval == CATS_UPDATE_INTERVAL",
          coord.update_interval == CATS_UPDATE_INTERVAL)
    check("C1: defaults -> polling_enabled True, interval 5",
          (coord.polling_enabled, coord.polling_interval_minutes) == (True, 5))
    check("C4 init: last_successful_fetch starts None",
          coord.last_successful_fetch is None)

    hass, entry, auth, coord = await setup_coordinator(options={"polling_enabled": False})
    check("C1: disabled -> update_interval is None", coord.update_interval is None)
    check("C1: disabled -> interval still resolved/stored",
          coord.polling_interval_minutes == 5)

    hass, entry, auth, coord = await setup_coordinator(
        options={"polling_enabled": False, "polling_interval": 30})
    check("C1: disabled + interval 30 -> update_interval None, stored 30",
          coord.update_interval is None and coord.polling_interval_minutes == 30)

    hass, entry, auth, coord = await setup_coordinator(options={"polling_interval": 10})
    check("C1: enabled + interval 10 -> update_interval 10 min",
          coord.update_interval == timedelta(minutes=10))

    hass, entry, auth, coord = await setup_coordinator(
        options={"polling_enabled": False})
    # C2: startup first refresh still runs with polling disabled
    capture = LogCapture()
    logging.getLogger("custom_components.feelloo.coordinator").addHandler(capture)
    await coord.async_setup()
    check("C2: first refresh ran with polling disabled",
          coord.first_refresh_called and coord.data and coord.data["cats"],
          "async_config_entry_first_refresh executed, data populated")
    check("C1/C2: no pending periodic timer armed after startup (disabled)",
          coord._pending_timer is None)
    check("C11: hub device registered",
          any(d.get("identifiers") == {("feelloo", "test_entry_id")}
              and d.get("model") == "Account" for d in hass.device_registry.devices))
    check("C11: cat device still registered",
          any(d.get("identifiers") == {("feelloo", "cat_uid_1")}
              for d in hass.device_registry.devices))
    check("C4: last_successful_fetch set after successful first refresh",
          coord.last_successful_fetch is not None)
    check("C6: token refresh timer still armed despite polling disabled",
          any(t.interval == timedelta(minutes=50) and not t.cancelled
              for t in hass.interval_timers),
          "50-minute auth housekeeping keeps running")
    logging.getLogger("custom_components.feelloo.coordinator").removeHandler(capture)


async def test_petite_souris_override():
    """§4.2 owner addition: Petite Souris temporarily overrides polling.

    Covers matrix rows V15–V19 and all five contract edge cases.
    """
    from custom_components.feelloo.const import FAST_POLLING_INTERVAL
    from custom_components.feelloo.sensor import FeellooLastUpdateSensor

    def fast_timers(hass):
        return [t for t in hass.interval_timers
                if t.interval == FAST_POLLING_INTERVAL]

    def ps_cats(programmed=True, count=1):
        return [{
            "_id": f"cat_uid_{i + 1}", "cat_id": 7 + i,
            "profile": {"name": f"Cat {i + 1}"},
            "geolocation": {"petite_souris": {"programmed": programmed}},
        } for i in range(count)]

    capture = LogCapture()
    logging.getLogger("custom_components.feelloo.coordinator").addHandler(capture)

    # V15 / amended V10 / V19: mode programmed + polling preference disabled
    # -> the override engages (startup == restart reconstruction, same path)
    hass, entry, auth, coord = await setup_coordinator(
        options={"polling_enabled": False}, cats=ps_cats())
    await coord.async_setup()
    check("§4.2/V15: mode active + polling disabled -> override engages at 1 min",
          coord.petite_souris_override is True
          and coord.update_interval == timedelta(minutes=1)
          and coord.polling_enabled is True)
    check("§4.2/V10: NO side fast timer while the override runs",
          len(fast_timers(hass)) == 0)
    check("§4.2/req4: entry.options untouched (preference is the remembered state)",
          entry.options == {"polling_enabled": False})
    check("§4.2: engagement logged at info level",
          any("polling override engaged" in m for m in capture.records))
    check("§4.2/V19: startup first refresh ran (restart reconstruction)",
          coord.first_refresh_called and coord.data["cats"])

    # V16 / V18: mode end (here: expiry detected via fetch) restores the preference
    auth.cats = ps_cats(programmed=False)
    await coord.async_request_refresh()
    check("§4.2/V16+V18: mode end -> preference restored (disabled again)",
          coord.petite_souris_override is False
          and coord.update_interval is None
          and coord._fast_polling_active == set())
    check("§4.2: restoration logged at info level",
          any("polling settings restored" in m for m in capture.records))
    check("§4.2/req4: entry.options still untouched after restore",
          entry.options == {"polling_enabled": False})

    # V17: manual disable during the mode wins; latch prevents re-engagement
    auth.cats = ps_cats()
    await coord.async_request_refresh()          # re-activate the mode
    check("§4.2/V17 setup: mode re-activated -> override engaged again",
          coord.petite_souris_override is True
          and coord.update_interval == timedelta(minutes=1))
    engaged_logs = len([m for m in capture.records if "override engaged" in m])
    await coord.async_apply_polling_settings(False, 5)   # manual disable
    check("§4.2/V17a: manual disable wins -> override cancelled, polling off",
          coord.petite_souris_override is False
          and coord.update_interval is None)
    check("§4.2/V17a: cancellation logged at info level",
          any("override cancelled" in m for m in capture.records))
    await coord.async_request_refresh()          # fetch while mode still programmed
    check("§4.2/V17a: latch holds — no re-engage while the mode stays active",
          coord.petite_souris_override is False
          and coord.update_interval is None)
    check("§4.2/V17a: suppressed fast polling logged (disabled + mode active)",
          any("fast polling suppressed" in m for m in capture.records))
    auth.cats = ps_cats(programmed=False)
    await coord.async_request_refresh()          # mode ends -> latch resets
    check("§4.2/V17a: mode end after manual cancel -> stays disabled, latch reset",
          coord.update_interval is None
          and coord._ps_override_cancelled is False)
    auth.cats = ps_cats()
    await coord.async_request_refresh()          # off/on cycle re-engages
    check("§4.2/V17a: petite souris off/on re-engages the boost",
          coord.petite_souris_override is True
          and coord.update_interval == timedelta(minutes=1))
    check("§4.2/edge3: engagement is transition-guarded (no duplicate logs)",
          len([m for m in capture.records if "override engaged" in m])
          == engaged_logs + 1)

    # edge2 + V17b: enabled preference, uniform override, manual interval wins
    hass2, entry2, auth2, coord2 = await setup_coordinator(options={}, cats=ps_cats())
    await coord2.async_setup()
    check("§4.2/edge2: enabled preference + mode -> uniform override at 1 min",
          coord2.petite_souris_override is True
          and coord2.update_interval == timedelta(minutes=1)
          and entry2.options == {})
    base = coord2.refresh_count
    await coord2.async_apply_polling_settings(True, 45)
    check("§4.2/V17b: manual interval wins -> override cancelled, 45-min cadence",
          coord2.petite_souris_override is False
          and coord2.update_interval == timedelta(minutes=45)
          and coord2.refresh_count == base + 1)
    check("§4.2/V17b: legacy side timer resumes 1-minute tracking (mode active)",
          coord2._fast_polling_timer is not None)
    entry2.options = {"polling_interval": 45}    # user's real preference changed mid-mode
    auth2.cats = ps_cats(programmed=False)
    await coord2.async_request_refresh()
    check("§4.2/edge2: mode end restores the CHANGED preference (live re-resolution)",
          coord2.update_interval == timedelta(minutes=45)
          and coord2.petite_souris_override is False
          and coord2._fast_polling_timer is None)

    # edge3: multiple cats + steady-state fetches — one override, idempotent
    entry2.options = {}
    auth2.cats = ps_cats(count=2)
    await coord2.async_request_refresh()
    engage_count = len([m for m in capture.records if "override engaged" in m])
    check("§4.2/edge3: two cats programmed -> single override at 1 min",
          coord2.petite_souris_override is True
          and coord2.update_interval == timedelta(minutes=1)
          and len(coord2._fast_polling_active) == 2)
    await coord2.async_request_refresh()         # steady state: idempotent
    check("§4.2/edge3: steady-state fetch does not re-engage",
          len([m for m in capture.records if "override engaged" in m]) == engage_count
          and coord2.update_interval == timedelta(minutes=1))

    # §8.2: the diagnostic sensor shows the effective state + override flag
    sensor = FeellooLastUpdateSensor(coord2, entry2)
    check("§8.2+§4.2: sensor attributes show the effective 1-min override",
          sensor.extra_state_attributes == {"polling_enabled": True,
                                             "polling_interval_minutes": 1,
                                             "petite_souris_override": True})
    auth2.cats = ps_cats(programmed=False, count=2)
    await coord2.async_request_refresh()
    check("§8.2+§4.2: sensor attributes follow the restored preference",
          sensor.extra_state_attributes == {"polling_enabled": True,
                                             "polling_interval_minutes": 5,
                                             "petite_souris_override": False})

    # Switch event path also engages the override (fresh entry, no mode)
    hass3, entry3, auth3, coord3 = await setup_coordinator(
        options={"polling_enabled": False}, cats=ps_cats(programmed=False))
    await coord3.async_setup()
    check("§4.2: no mode at startup -> preference applied, no override",
          coord3.petite_souris_override is False
          and coord3.update_interval is None)
    hass3.bus.async_fire("feelloo_fast_polling", {"cat_id": 7, "enabled": True})
    check("§4.2: switch event engages the override",
          coord3.petite_souris_override is True
          and coord3.update_interval == timedelta(minutes=1))
    logging.getLogger("custom_components.feelloo.coordinator").removeHandler(capture)


async def test_override_visibility():
    """Owner follow-up 2: the Petite Souris override is visible on the switch.

    Matrix row V20 — the owner's exact test scenario: polling disabled,
    Petite Souris activated, the switch must not read as a plain "off".
    """
    from custom_components.feelloo.const import get_polling_settings
    from custom_components.feelloo.number import FeellooPollingIntervalNumber
    from custom_components.feelloo.switch import FeellooPollingSwitch

    def ps_cats2(programmed=True, count=1):
        return [{
            "_id": f"cat_uid_{i + 1}", "cat_id": 7 + i,
            "profile": {"name": f"Cat {i + 1}"},
            "geolocation": {"petite_souris": {"programmed": programmed}},
        } for i in range(count)]

    # The owner's scenario: preference disabled + mode active -> override engaged
    hass, entry, auth, coord = await setup_coordinator(
        options={"polling_enabled": False}, cats=ps_cats2())
    await coord.async_setup()
    check("V20: override engaged with disabled preference (owner scenario)",
          coord.petite_souris_override is True)

    sw = FeellooPollingSwitch(coord, entry)
    sw.hass = hass
    sw._attr_entity_id = "switch.feelloo_test_polling"
    hass.entity_registry.entries["switch.feelloo_test_polling"] = types.SimpleNamespace(
        translation_key="polling_enabled", name=None, original_name="Automatic Polling")
    await sw.async_added_to_hass()

    check("V20: switch reads ON during the override (effective state)",
          sw.is_on is True and get_polling_settings(entry)[0] is False,
          "state label truthful; saved preference stays disabled")
    check("V20: switch icon differs while overridden",
          sw.icon == "mdi:clock-fast" and sw.icon != "mdi:autorenew")
    check("V20: switch attributes expose saved preference AND effective state",
          sw.extra_state_attributes == {
              "saved_polling_enabled": False,
              "saved_polling_interval_minutes": 5,
              "effective_polling_enabled": True,
              "effective_polling_interval_minutes": 1,
          })
    check("V20: registry label swapped to the override variant",
          any(eid == "switch.feelloo_test_polling"
              and kw.get("translation_key") == "polling_enabled_override"
              for eid, kw in hass.entity_registry.updates))

    # The labels exist in both languages with full parity
    with open(f"{REPO}/custom_components/feelloo/translations/en.json") as fh:
        en = json.load(fh)
    with open(f"{REPO}/custom_components/feelloo/translations/fr.json") as fh:
        fr = json.load(fh)
    check("V20: override label present in en and fr (full parity)",
          en["entity"]["switch"]["polling_enabled_override"]["name"]
          == "Automatic Polling (Petite Souris)"
          and fr["entity"]["switch"]["polling_enabled_override"]["name"]
          == "Polling automatique (Petite Souris)")

    # Number: displays the effective interval (owner follow-up 3), preference in attributes
    num = FeellooPollingIntervalNumber(coord, entry)
    num.hass = hass
    await num.async_added_to_hass()
    check("V20/FU3: number displays the EFFECTIVE interval during the override",
          num.native_value == 1)
    check("V20/FU3: number attributes carry the saved preference + override flag",
          num.extra_state_attributes == {
              "saved_polling_interval_minutes": 5,
              "effective_polling_interval_minutes": 1,
              "petite_souris_override": True,
          })

    # OFF during the override: command semantics unchanged, NOT a no-op
    await sw.async_turn_off()
    check("V20: OFF during override cancels the boost (semantics unchanged)",
          coord.petite_souris_override is False
          and coord.update_interval is None)
    check("V20: the OFF command is visibly not a no-op (switch flips ON->OFF)",
          sw.is_on is False)
    check("V20: registry label restored after the manual cancel",
          hass.entity_registry.entries["switch.feelloo_test_polling"].translation_key
          == "polling_enabled"
          and any(kw.get("translation_key") == "polling_enabled"
                  for _, kw in hass.entity_registry.updates))
    check("V20: switch attributes back to normal after the cancel",
          sw.extra_state_attributes == {
              "saved_polling_enabled": False,
              "saved_polling_interval_minutes": 5,
              "effective_polling_enabled": False,
              "effective_polling_interval_minutes": 5,
          })

    # Re-engage, then let the mode end via a fetch: everything returns to normal
    auth.cats = ps_cats2(programmed=False)
    await coord.async_request_refresh()          # mode ends -> latch resets
    auth.cats = ps_cats2()
    await coord.async_request_refresh()           # re-engage via API-state sync
    check("V20: re-engaged override flips the switch back ON",
          coord.petite_souris_override is True and sw.is_on is True)
    check("V20: override icon and label return while re-engaged",
          sw.icon == "mdi:clock-fast"
          and hass.entity_registry.entries["switch.feelloo_test_polling"].translation_key
          == "polling_enabled_override")
    auth.cats = ps_cats2(programmed=False)
    await coord.async_request_refresh()           # mode ends -> restore
    check("V20: after restore the switch returns to normal",
          sw.is_on is False and sw.icon == "mdi:autorenew"
          and sw.extra_state_attributes == {
              "saved_polling_enabled": False,
              "saved_polling_interval_minutes": 5,
              "effective_polling_enabled": False,
              "effective_polling_interval_minutes": 5,
          }
          and hass.entity_registry.entries["switch.feelloo_test_polling"].translation_key
          == "polling_enabled")
    check("V20/FU3: number returns to the saved preference after restore",
          num.native_value == 5
          and num.extra_state_attributes == {
              "saved_polling_interval_minutes": 5,
              "effective_polling_interval_minutes": 5,
              "petite_souris_override": False,
          })


async def test_override_number_display():
    """Owner follow-up 3: the interval number shows the effective truth.

    Matrix row V21 — the owner's report: the number displayed 5 minutes
    while the override actually ran at 1 minute. The number now mirrors
    the switch's effective-state display, and the write path must update
    the SAVED preference without corruption while the override runs.
    """
    from custom_components.feelloo.number import FeellooPollingIntervalNumber

    def ps_cats3(programmed=True):
        return [{
            "_id": "cat_uid_1", "cat_id": 7,
            "profile": {"name": "Cat 1"},
            "geolocation": {"petite_souris": {"programmed": programmed}},
        }]

    # Preference enabled @ 5, override active -> the number displays 1 (effective)
    hass, entry, auth, coord = await setup_coordinator(options={}, cats=ps_cats3())
    await coord.async_setup()
    num = FeellooPollingIntervalNumber(coord, entry)
    num.hass = hass
    await num.async_added_to_hass()
    check("V21: during override the number displays the EFFECTIVE interval",
          coord.petite_souris_override is True and num.native_value == 1)
    check("V21: number attributes mirror the switch (saved/effective + override flag)",
          num.extra_state_attributes == {
              "saved_polling_interval_minutes": 5,
              "effective_polling_interval_minutes": 1,
              "petite_souris_override": True,
          })

    # Write path during the override: saved preference updated, override cancelled
    await num.async_set_native_value(10)
    check("V21: write during override updates the SAVED preference (no corruption)",
          entry.options.get("polling_interval") == 10
          and coord.petite_souris_override is False)
    check("V21: write during override cancels it; display converges to saved",
          num.native_value == 10 and coord.update_interval == timedelta(minutes=10))

    # Preference disabled + override active: display 1, write keeps polling off
    hass2, entry2, auth2, coord2 = await setup_coordinator(
        options={"polling_enabled": False}, cats=ps_cats3())
    await coord2.async_setup()
    num2 = FeellooPollingIntervalNumber(coord2, entry2)
    num2.hass = hass2
    await num2.async_added_to_hass()
    check("V21: disabled-preference override also displays the effective 1 min",
          coord2.petite_souris_override is True and num2.native_value == 1)
    await num2.async_set_native_value(15)
    check("V21: write during disabled-preference override keeps polling off",
          coord2.update_interval is None
          and entry2.options == {"polling_enabled": False, "polling_interval": 15}
          and num2.native_value == 15)

    # After the mode ends (no manual write): the number returns to the saved value
    hass3, entry3, auth3, coord3 = await setup_coordinator(options={}, cats=ps_cats3())
    await coord3.async_setup()
    num3 = FeellooPollingIntervalNumber(coord3, entry3)
    num3.hass = hass3
    await num3.async_added_to_hass()
    check("V21 setup: override active, number displays 1",
          num3.native_value == 1)
    auth3.cats = ps_cats3(programmed=False)
    await coord3.async_request_refresh()          # mode ends -> restore
    check("V21: after mode end the number returns to the saved preference",
          coord3.petite_souris_override is False and num3.native_value == 5
          and num3.extra_state_attributes == {
              "saved_polling_interval_minutes": 5,
              "effective_polling_interval_minutes": 5,
              "petite_souris_override": False,
          })


async def test_apply_settings_cases():
    # Case: enable/interval-change while enabled -> forced debounced refresh
    hass, entry, auth, coord = await setup_coordinator(options={})
    await coord.async_setup()
    base = coord.refresh_count
    await coord.async_apply_polling_settings(True, 10)
    check("C5: interval change while enabled -> update_interval updated",
          coord.update_interval == timedelta(minutes=10))
    check("C5: interval change while enabled -> one forced refresh",
          coord.refresh_count == base + 1)
    check("C5: new cadence armed after the forced refresh",
          coord._pending_timer is not None and coord._pending_timer.interval
          == timedelta(minutes=10))

    # Case: idempotent no-op
    base = coord.refresh_count
    await coord.async_apply_polling_settings(True, 10)
    check("C5: unchanged settings -> idempotent no-op",
          coord.refresh_count == base and coord.update_interval == timedelta(minutes=10))

    # Case: disable -> no forced refresh, interval None, straggler bounded (§5.2)
    base = coord.refresh_count
    pending = coord._pending_timer
    await coord.async_apply_polling_settings(False, 10)
    check("C5: disable -> update_interval None, no forced refresh",
          coord.update_interval is None and coord.refresh_count == base)
    check("§5.2: already-scheduled timer still pending after disable (straggler)",
          pending is not None and not pending.cancelled)
    if pending is not None:
        await pending.fire()   # the single straggler fetch
        check("§5.2: straggler fired exactly one refresh, nothing re-armed",
              coord.refresh_count == base + 1 and coord._pending_timer is None,
              "at most one fetch after disable, then zero periodic fetches")

    # Case: interval change while disabled -> stored, applied on next enable
    base = coord.refresh_count
    await coord.async_apply_polling_settings(False, 30)
    check("C5: interval change while disabled -> stored, update_interval stays None",
          coord.update_interval is None and coord.polling_interval_minutes == 30
          and coord.refresh_count == base)
    await coord.async_apply_polling_settings(True, 30)
    check("C5: enable uses the stored interval and refreshes",
          coord.update_interval == timedelta(minutes=30)
          and coord.refresh_count == base + 1)

    # V-default: defaults preserve current behaviour
    hass, entry, auth, coord = await setup_coordinator(options={})
    check("V1 structural: default entry resolves to enabled @ 5 min",
          coord.update_interval == timedelta(minutes=5) and coord.polling_enabled)


async def test_listener():
    from custom_components.feelloo import _async_update_listener

    hass, entry, auth, coord = await setup_coordinator(options={})
    hass.data.setdefault("feelloo", {})[entry.entry_id] = {
        "main": coord, "auth": auth,
        "active_credentials": dict(entry.data),
    }
    coord.async_apply_polling_settings = coord.async_apply_polling_settings
    applied = []
    orig = coord.async_apply_polling_settings

    async def spy(enabled, interval):
        applied.append((enabled, interval))

    coord.async_apply_polling_settings = spy

    # Options-only change -> live apply, no reload (V3/V5 semantics)
    entry.options = {"polling_enabled": False, "polling_interval": 10}
    await _async_update_listener(hass, entry)
    check("C9: options-only change -> live apply, no reload",
          applied == [(False, 10)] and hass.config_entries.reloads == [],
          f"applied={applied}")

    # Credentials change -> reload (V13 semantics)
    entry.data = {"email": "new@example.com", "password": "other"}
    await _async_update_listener(hass, entry)
    check("C9: credentials change -> entry reload, no apply",
          hass.config_entries.reloads == [entry.entry_id] and applied == [(False, 10)])

    # Torn-down entry -> silent return
    hass.data["feelloo"].pop(entry.entry_id)
    entry.data = {"email": "owner@example.com", "password": "secret"}
    await _async_update_listener(hass, entry)
    check("C9: missing hass.data (teardown) -> silent return",
          len(hass.config_entries.reloads) == 1)
    coord.async_apply_polling_settings = orig


async def test_button():
    from custom_components.feelloo.button import FeellooRefreshButton

    hass, entry, auth, coord = await setup_coordinator(options={})
    secondaries = {
        "activity": MockSecondary("activity"),
        "activity_week": MockSecondary("activity_week"),
        "activity_month": MockSecondary("activity_month"),
        "territory": MockSecondary("territory"),
        "session": MockSecondary("session", fail=True),
    }
    hass.data.setdefault("feelloo", {})[entry.entry_id] = {
        "main": coord, **secondaries,
    }
    button = FeellooRefreshButton(entry)
    button.hass = hass

    capture = LogCapture()
    logging.getLogger("custom_components.feelloo.button").addHandler(capture)

    # V8: press with polling disabled -> fetch happens, polling stays off
    await coord.async_apply_polling_settings(False, 5)
    coord._pending_timer = None
    base_main, base_sec = coord.refresh_count, secondaries["activity"].refreshes
    await button.async_press()
    check("§6/V8: button fetches main + all five coordinators with polling off",
          coord.refresh_count == base_main + 1
          and all(s.refreshes == base_sec + 1 for s in secondaries.values()))
    check("V8: polling stays off after the button fetch (no timer armed)",
          coord.update_interval is None and coord._pending_timer is None)
    check("§6: partial secondary failure logged, not raised",
          any("session coordinator failed" in m for m in capture.records))

    # V12-style: genuine main failure surfaces as HomeAssistantError
    from homeassistant.exceptions import HomeAssistantError  # stub
    auth.fail = True
    coord._pending_timer = None
    try:
        await button.async_press()
        raised = False
    except HomeAssistantError as exc:
        raised = True
    check("§6/V12: main refresh failure -> HomeAssistantError (not swallowed)",
          raised and not coord.last_update_success,
          "genuine failure still flips last_update_success")

    # Missing hass.data -> error
    hass.data["feelloo"].pop(entry.entry_id)
    try:
        await button.async_press()
        raised = True
    except HomeAssistantError:
        raised = True
    check("§6: missing integration data -> HomeAssistantError", raised)
    logging.getLogger("custom_components.feelloo.button").removeHandler(capture)


async def test_last_known_value():
    """§9: with polling off, no refreshes -> no failures -> everything stays
    available; a genuine failure still surfaces (V12 structure)."""
    from custom_components.feelloo.sensor import FeellooLastUpdateSensor

    hass, entry, auth, coord = await setup_coordinator(
        options={"polling_enabled": False})
    await coord.async_setup()
    sensor = FeellooLastUpdateSensor(coord, entry)
    check("§8.2: last update sensor available after startup (polling off)",
          sensor.available is True)
    check("§8.2: diagnostic sensor shows last_successful_fetch",
          sensor.native_value == coord.last_successful_fetch)
    check("§8.2: attributes expose runtime polling settings",
          sensor.extra_state_attributes == {"polling_enabled": False,
                                             "polling_interval_minutes": 5,
                                             "petite_souris_override": False})

    # Genuine failure path intact: auth failure flips last_update_success
    fetch_time = coord.last_successful_fetch
    auth.fail = True
    await coord.async_request_refresh()
    check("§9: genuine failure still flips last_update_success",
          coord.last_update_success is False)
    check("§9: coordinator-gated entities go unavailable on real failure",
          sensor.available is False)
    check("§9: last_successful_fetch frozen at last success (not cleared)",
          coord.last_successful_fetch == fetch_time)
    check("§9: data retained on failure (last known value)",
          coord.data.get("cats") is not None)

    # Recovery
    auth.fail = False
    await coord.async_request_refresh()
    check("§9: recovery restores availability and advances the timestamp",
          coord.last_update_success is True and sensor.available is True
          and coord.last_successful_fetch > fetch_time)


async def test_entities():
    from custom_components.feelloo.const import (
        POLLING_INTERVAL_MAX, POLLING_INTERVAL_MIN,
    )
    from custom_components.feelloo.number import FeellooPollingIntervalNumber
    from custom_components.feelloo.switch import FeellooPollingSwitch
    from custom_components.feelloo.sensor import FeellooLastUpdateSensor

    hass, entry, auth, coord = await setup_coordinator(
        options={}, unique_id="owner@example.com")
    hass.data.setdefault("feelloo", {})[entry.entry_id] = {"main": coord}
    applied = []

    async def apply_spy(enabled, interval):
        applied.append((enabled, interval))

    coord.async_apply_polling_settings = apply_spy

    sw = FeellooPollingSwitch(coord, entry)
    sw.hass = hass
    num = FeellooPollingIntervalNumber(coord, entry)
    num.hass = hass
    sens = FeellooLastUpdateSensor(coord, entry)

    check("§8.2: unique_ids use entry.unique_id",
          sw.unique_id == "owner@example.com_polling_enabled"
          and num.unique_id == "owner@example.com_polling_interval"
          and sens.unique_id == "owner@example.com_last_update")
    check("§7.2: categories CONFIG/CONFIG/DIAGNOSTIC",
          sw.entity_category == "config" and num.entity_category == "config"
          and sens.entity_category == "diagnostic")
    check("§7.2: number bounds/step/unit/mode",
          (num.native_min_value, num.native_max_value, num.native_step,
           num.native_unit_of_measurement, num.mode)
          == (POLLING_INTERVAL_MIN, POLLING_INTERVAL_MAX, 1, "min", "box"))
    check("§7.2: switch is_on reads persisted value (default True)",
          sw.is_on is True)
    check("§7.2: number native_value reads persisted value (default 5)",
          num.native_value == 5)

    # unique_id fallback for legacy entries without unique_id
    legacy = FakeEntry(entry_id="legacy_id")
    check("§8.2: legacy entry falls back to entry_id in unique_id",
          FeellooPollingSwitch(coord, legacy).unique_id == "legacy_id_polling_enabled")

    # Switch turn_off: apply first, persist second (order-verified)
    order_log = []

    async def apply_spy(enabled, interval):
        applied.append((enabled, interval))
        order_log.append("apply")

    coord.async_apply_polling_settings = apply_spy
    orig_update = hass.config_entries.async_update_entry

    def update_spy(entry_, **kwargs):
        order_log.append("update")
        return orig_update(entry_, **kwargs)

    hass.config_entries.async_update_entry = update_spy

    await sw.async_turn_off()
    upd_entry, upd_kwargs = hass.config_entries.updates[-1]
    check("§7.2: switch off -> live apply first, persist second",
          order_log[-2:] == ["apply", "update"]
          and applied[-1] == (False, 5),
          f"call order: {order_log[-2:]}")
    check("§7.2: switch off -> persists polling_enabled False to options only",
          upd_kwargs.get("options") == {"polling_enabled": False}
          and "data" not in upd_kwargs)
    await sw.async_turn_on()
    check("§7.2: switch on -> apply (True, interval) + persist True",
          order_log[-2:] == ["apply", "update"]
          and applied[-1] == (True, 5)
          and hass.config_entries.updates[-1][1].get("options")
          == {"polling_enabled": True})

    # Number validation (mirrors existing number entity style)
    for bad in (0, 1441, 2.5, 0.5, -1):
        try:
            await num.async_set_native_value(bad)
            ok = False
        except ValueError:
            ok = True
        check(f"§7.2: number rejects invalid value {bad}", ok)
    await num.async_set_native_value(10)
    upd_entry, upd_kwargs = hass.config_entries.updates[-1]
    check("§7.2: number 10 -> apply (True, 10) + persist interval 10",
          applied[-1] == (True, 10)
          and upd_kwargs.get("options") == {"polling_enabled": True,
                                            "polling_interval": 10},
          "options are merged, existing keys preserved")
    check("§7.2: number native_value follows persisted value",
          num.native_value == 10)

    # Entry-update listener sync (state follows options-flow changes)
    await sw.async_added_to_hass()
    await num.async_added_to_hass()
    before = sw.written_states
    await sw._async_on_entry_update(hass, entry)
    check("§7.2: entities write state when options change elsewhere",
          sw.written_states > before)


async def test_options_flow():
    from custom_components.feelloo.config_flow import FeellooOptionsFlowHandler
    from custom_components.feelloo.const import (
        POLLING_INTERVAL_MAX, POLLING_INTERVAL_MIN,
    )

    hass = _FakeHass()
    entry = FakeEntry(
        data={"email": "owner@example.com", "password": "secret"},
        options={"polling_enabled": True, "polling_interval": 5},
        unique_id="owner@example.com")
    flow = FeellooOptionsFlowHandler()
    flow.hass = hass
    flow.config_entry = entry

    # Form schema contains the new fields with correct defaults
    result = await flow.async_step_init(None)
    schema = result["data_schema"].schema          # {marker: validator}
    markers = {m.key: m for m in schema}          # field name -> marker
    validators = {m.key: v for m, v in schema.items()}
    keys = set(markers)
    check("C12: form shows email/password/polling_enabled/polling_interval",
          keys == {"email", "password", "polling_enabled", "polling_interval"})
    check("C12: password defaults to blank (keep current)",
          markers["password"].default == "")
    check("C12: polling defaults resolve from current options",
          markers["polling_enabled"].default is True
          and markers["polling_interval"].default == 5)
    range_validator = next(v for v in validators["polling_interval"].validators
                           if isinstance(v, _Range))
    check("C12: interval schema bounds are 1..1440 (min/max coercion)",
          range_validator.min == POLLING_INTERVAL_MIN
          and range_validator.max == POLLING_INTERVAL_MAX)

    # Polling-only submission: no validation, no entry.data change
    posted_before = len(hass._session.posted)
    updates_before = len(hass.config_entries.updates)
    result = await flow.async_step_init({
        "email": "owner@example.com", "password": "",
        "polling_enabled": False, "polling_interval": 10,
    })
    upd_entry, upd_kwargs = hass.config_entries.updates[-1]
    check("C12: polling-only -> create_entry with merged options",
          result["type"] == "create_entry"
          and result["data"] == {"polling_enabled": False, "polling_interval": 10})
    check("C12: polling-only -> options persisted, entry.data untouched",
          upd_kwargs.get("options") == {"polling_enabled": False,
                                        "polling_interval": 10}
          and "data" not in upd_kwargs)
    check("C12: polling-only -> NO credential validation call",
          len(hass._session.posted) == posted_before
          and len(hass.config_entries.updates) == updates_before + 1,
          "no Firebase POST performed")

    # Email change without password -> password_required, nothing persisted
    updates_before = len(hass.config_entries.updates)
    result = await flow.async_step_init({
        "email": "changed@example.com", "password": "",
        "polling_enabled": True, "polling_interval": 5,
    })
    check("C12: email change without password -> password_required error, no update",
          result["type"] == "form"
          and result["errors"].get("base") == "password_required"
          and len(hass.config_entries.updates) == updates_before)

    # Credentials change -> validated, data + options both written
    def ok_response(url, payload):
        return _FakeResponse(200, {"idToken": "x"})

    hass._session.post_responses.append(ok_response)
    result = await flow.async_step_init({
        "email": "changed@example.com", "password": "newpass",
        "polling_enabled": False, "polling_interval": 10,
    })
    upd_entry, upd_kwargs = hass.config_entries.updates[-1]
    check("C12: credentials change -> create_entry",
          result["type"] == "create_entry")
    check("C12: credentials change -> Firebase validation performed",
          len(hass._session.posted) > 0)
    check("C12: credentials change -> entry.data updated with new credentials",
          upd_kwargs.get("data") == {"email": "changed@example.com",
                                      "password": "newpass"})
    check("C12: credentials change -> polling options still merged",
          upd_kwargs.get("options") == {"polling_enabled": False,
                                        "polling_interval": 10})
    check("C12: create_entry data == merged options (no options wipe)",
          result["data"] == {"polling_enabled": False, "polling_interval": 10})

    # Invalid credentials -> invalid_auth, nothing persisted
    def bad_response(url, payload):
        return _FakeResponse(400, {"error": {"message": "INVALID_PASSWORD"}})

    hass._session.post_responses.append(bad_response)
    entry.data = {"email": "owner@example.com", "password": "secret"}
    result = await flow.async_step_init({
        "email": "owner@example.com", "password": "wrongpass",
        "polling_enabled": True, "polling_interval": 5,
    })
    check("C12: invalid credentials -> invalid_auth error, no update",
          result["type"] == "form" and result["errors"].get("base") == "invalid_auth")


async def main():
    _install_stubs()

    # Import smoke test: every touched module imports against the stubs
    import custom_components.feelloo as feelloo_init  # noqa: F401
    import custom_components.feelloo.const  # noqa: F401
    import custom_components.feelloo.coordinator  # noqa: F401
    import custom_components.feelloo.config_flow  # noqa: F401
    import custom_components.feelloo.switch  # noqa: F401
    import custom_components.feelloo.number  # noqa: F401
    import custom_components.feelloo.button  # noqa: F401
    import custom_components.feelloo.sensor  # noqa: F401
    check("IMPORT: all 8 touched modules import cleanly", True)

    test_resolver()
    await test_constructor()
    await test_petite_souris_override()
    await test_override_visibility()
    await test_override_number_display()
    await test_apply_settings_cases()
    await test_listener()
    await test_button()
    await test_last_known_value()
    await test_entities()
    await test_options_flow()

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n=== {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed ===")
    if failed:
        for name, _, note in failed:
            print(f"  FAILED: {name} {note}")
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(main())