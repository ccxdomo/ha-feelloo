# Contract 047 — Polling Control (BINDING)

**Repo:** `ha-feelloo` (HACS custom component), branch `main`, pinned at commit `59e0361`, version `1.7.5`.
**Target release:** 1.8.0.
**Status:** BINDING for Coder and Reviewer. Any deviation must be justified in writing and approved by the orchestrator before implementation.
**Owner addition (2026-10-08, approved):** §4.2 (Petite Souris × polling interplay) extends this contract with a temporary 1-minute polling override while the mode is active. It supersedes §4.1's blanket suppression, amends C3/C5 and the sensor attributes (§8.2), amends V10 and adds matrix rows V15–V19. Everything else stands as originally specified.
**Owner follow-up 2 (2026-10-08, after live testing — option (b) chosen):** the override is now made VISIBLE on the polling switch (matrix V20; §4.2/§7.2 amendments): while the override runs, `is_on` reports the effective state (reads ON), the icon differs, saved/effective attributes are exposed, and the displayed name is swapped to the `(Petite Souris)` variant via the supported entity-registry `translation_key` update. Command semantics are UNCHANGED — turning the switch off during the override still cancels it.
**Owner follow-up 3 (2026-10-08, after live testing):** the interval NUMBER now mirrors the switch (matrix V21; §7.2 amendment): while the override runs, `native_value` displays the EFFECTIVE interval (1 minute) — the owner saw "5" while polling ran at 1 minute, the same dissonance follow-up 2 removed from the switch. The saved preference stays in the attributes (`saved_polling_interval_minutes`, `effective_polling_interval_minutes`, `petite_souris_override`), the write path still updates the SAVED preference (manual-wins, no corruption), and the number returns to the saved value when the mode ends.
**Owner follow-up 4 (2026-10-08, post-1.9.0 — naming option B):** the two main-coordinator controls' DISPLAY names are renamed — switch 'Automatic Polling' → **Tag auto-polling** (fr 'Polling automatique' → **Polling auto du tag**), number 'Polling Interval' → **Tag polling interval** (fr 'Intervalle de polling' → **Intervalle de polling du tag**); the override variant becomes the new base name + ' (Petite Souris)'. Rationale: the main fetch (`/users/cats` + `/users/cats/{cat_id}`) carries GPS position, LoRa signal strength, battery/charging state and presence — 'Tag' covers that accurately without the wordiness of 'cat data'. DISPLAY-ONLY: unique_ids, registry translation keys and existing installs' entity_ids are untouched (§8.2/§8.3 rows amended below; V3 label updated). The five secondary numbers (spec 048) keep their coordinator-scoped 'Polling Interval — …' names — each is explicitly tied to one coordinator and not ambiguous.

This contract defines the exact mechanisms, schemas, entity surface, and verification requirements for Spec 047: control of the Feelloo main coordinator's automatic polling (disable, change frequency, manual refresh), plus the last-known-value guarantee.

---

## 1. Scope

**In scope**
- The **main coordinator** (`FeellooMainCoordinator`, polling `/users/cats` + `/users/cats/{cat_id}`, default every 5 minutes) is the ONLY coordinator whose polling becomes configurable.
- New persisted settings: polling enabled/disabled, polling interval (minutes).
- One global manual-refresh button entity (per config entry), refreshing **all** coordinators.
- One diagnostic "last update" timestamp sensor (per config entry) so data age is visible in the UI.
- Settings surfaces: existing `FeellooOptionsFlowHandler` + configuration entities (switch + number).
- Last-known-value guarantee while polling is disabled.

**Out of scope / must NOT change**
- The five other coordinators keep their fixed `update_interval`: activity 15 m, activity_week 1 h, activity_month 6 h, territory 15 m, session 30 m (`coordinator.py` lines 376, 426, 479, 532, 594).
- The Firebase token refresh timer (50 m, `coordinator.py` line 198) **always keeps running**, even when polling is disabled. Justification: it is auth housekeeping, not data polling; manual refreshes (button, service) need a valid token to work. Disabling data polling must not break the ability to fetch on demand.
- No new HA service. No new platform (all new entities go on existing platforms).
- No changes to the `set_petite_souris` service, the petite souris switch behavior, or the ring button.
- No new HA minimum version *from the 047 mechanisms themselves* — all of them exist in HA 2024.1. **Amended (Reviewer follow-up, 2026-10-08):** `hacs.json` was nevertheless raised to `"homeassistant": "2024.12.0"` — the merged HA-2026.9 options-flow fix (commit `84dc85b`, preserved per this contract) requires the base `OptionsFlow` resolving `config_entry`, which first shipped in HA 2024.12.0 (2024.1–2024.11: no base property, no manager assignment → the options flow is broken there; 2024.12.0: resolving property). Source evidence recorded in `verification.md` §9.
- No config entry schema migration. Config entry `VERSION` stays `1`.

---

## 2. Settings schema and persistence

### 2.1 New constants (`custom_components/feelloo/const.py`)

```python
# Polling control (Spec 047)
CONF_POLLING_ENABLED = "polling_enabled"
CONF_POLLING_INTERVAL = "polling_interval"          # minutes (int)

DEFAULT_POLLING_ENABLED = True
DEFAULT_POLLING_INTERVAL = 5                         # minutes == CATS_UPDATE_INTERVAL
POLLING_INTERVAL_MIN = 1                            # minutes
POLLING_INTERVAL_MAX = 1440                         # minutes (24 h)
PETITE_SOURIS_OVERRIDE_INTERVAL_MINUTES = 1          # == FAST_POLLING_INTERVAL (§4.2)
```

### 2.2 Resolution helper (`const.py`, same file)

Add a pure helper (no HA imports; reads only `entry.options`):

```python
def get_polling_settings(entry) -> tuple[bool, int]:
    """Resolve polling settings from entry options with defensive defaults."""
```

Semantics (BINDING):
- `polling_enabled` missing → `DEFAULT_POLLING_ENABLED`. Present but not `bool` → `DEFAULT_POLLING_ENABLED`.
- `polling_interval` missing → `DEFAULT_POLLING_INTERVAL`. Not coercible to `int`, or outside `[POLLING_INTERVAL_MIN, POLLING_INTERVAL_MAX]` → **fall back to the default, not to the nearest bound**. Rationale: a corrupted/partially edited options dict must never produce a surprising cadence; the default reproduces today's behavior.
- Returns `(enabled: bool, interval_minutes: int)`.

Placement note: `const.py` is constants-only today; the helper is a deliberate exception because `config_flow.py` must not import `coordinator.py`, and every consumer (`__init__.py`, `coordinator.py`, `config_flow.py`, `switch.py`, `number.py`) already imports `const.py`. Do not create a new module for this.

### 2.3 Storage

- Settings live in `entry.options` (key/value per §2.1). Never in `entry.data` — `entry.data` remains credentials-only.
- Defaults for existing installs: no `polling_enabled` / `polling_interval` keys → resolution yields `(True, 5)` → behavior **identical to 1.7.5** until the owner changes something. No migration code.
- No `hass.storage`, no registry-based storage for these settings.

### 2.4 Bounds justification (documented, not re-litigated)

- **min 1 minute:** anything lower is abusive to the Feelloo cloud; the 1-minute fast-polling mode already exists as the explicit "real-time tracking" mode (petite souris).
- **max 1440 minutes (24 h):** location/battery data older than a day has little decision value; also bounds the worst-case "one straggler refresh" edge (§5.2).
- **default 5 minutes:** exactly today's `CATS_UPDATE_INTERVAL`.

---

## 3. Control points (exact, pinned to `59e0361`)

| # | File:line | What exists there | What changes |
|---|-----------|-------------------|--------------|
| C1 | `coordinator.py:192` | `update_interval=CATS_UPDATE_INTERVAL` in `FeellooMainCoordinator.__init__` (class at :176) | Constructor resolves `(enabled, interval_minutes)` via `get_polling_settings(entry)`; passes `update_interval=timedelta(minutes=interval_minutes) if enabled else None`; stores `self.polling_enabled`, `self.polling_interval_minutes` |
| C2 | `coordinator.py:204` | `await self.async_config_entry_first_refresh()` in `async_setup` | **Unchanged.** Initial fetch always happens on startup, even when polling is disabled |
| C3 | `coordinator.py:246` | `_sync_fast_polling_timer()` | **Amended (§4.2):** drives the Petite Souris polling override transitions (engage on set empty→non-empty, disengage on non-empty→empty); the side timer is NOT started while the override runs (the main `update_interval` already provides the 1-minute cadence) and is suppressed while polling is disabled (stop + info log). All existing call sites (startup restore, event handler, `_async_update_data` auto-sync) inherit |
| C4 | `coordinator.py:~274` | `FeellooMainCoordinator._async_update_data` | Add `self.last_successful_fetch = dt_util.now()` as the last statement before `return` (success path only — exceptions skip it); optional debug log at method entry |
| C5 | `coordinator.py` (new method on `FeellooMainCoordinator`) | — | `async_apply_polling_settings(enabled, interval_minutes)` per §5; **amended (§4.2):** any manual call while Petite Souris is active cancels the override (manual wins, §4.2 edge case 1) |
| C6 | `coordinator.py:198` | token refresh timer (50 m) | **Unchanged** — always runs |
| C7 | `__init__.py:31-36` | main coordinator construction | Unchanged signature; constructor reads options itself (C1) |
| C8 | `__init__.py:50-59` | `hass.data[DOMAIN][entry.entry_id]` population | Add key `"active_credentials": dict(entry.data)` (used by the update listener, §7.3) |
| C9 | `__init__.py` (new, near setup) | — | Register update listener: `entry.async_on_unload(entry.add_update_listener(_async_update_listener))` |
| C10 | `__init__.py:114` | `async_forward_entry_setups` | Unchanged |
| C11 | `coordinator.py` `_async_setup_devices` | registers per-cat devices | Additionally registers the hub device (§8.1) |
| C12 | `config_flow.py:109-149` | `FeellooOptionsFlowHandler.async_step_init` | Extended per §7 |

No other polling-related code may be touched. In particular, the five secondary coordinators' `update_interval` arguments (lines 376, 426, 479, 532, 594) are frozen as-is.

---

## 4. Disable/enable mechanism (BINDING)

HA ground truth this design relies on: a `DataUpdateCoordinator` schedules periodic refreshes only while `self.update_interval` is not `None`; `update_interval=None` (set at construction or later) means no periodic refresh is ever scheduled. Manual refreshes (`async_request_refresh()`, `async_refresh()`, `async_config_entry_first_refresh()`) work regardless of `update_interval`. This is stable, documented HA behavior available in 2024.1.

- **Disable:** `FeellooMainCoordinator` runs with `update_interval = None` → no periodic refresh of `/users/cats` is scheduled. The fast-polling timer (petite souris, 1 min) is additionally suppressed by the C3 gate. Token refresh (C6) continues.
- **Enable:** `update_interval = timedelta(minutes=interval_minutes)` → normal scheduling.
- **Startup with polling disabled:** `async_setup()` still runs `async_config_entry_first_refresh()` (C2) → entities start with fresh data, then no timer is scheduled (the coordinator's reschedule no-ops on `None`). Requirement "initial fetch must still happen on startup" is satisfied by construction (C1+C2), no extra code.
- **Disable/enable is a runtime setting**: applied by C5 (config entities / listener) and by C1 (startup). Never by entry removal, never by raising errors, never by making `_async_update_data` fail.

### 4.1 Petite Souris interplay (original 1.8.0 decision — SUPERSEDED 2026-10-08)

Original decision: with polling disabled, the fast-polling timer must NOT run, even if petite souris was activated (from the HA switch or already programmed in the Feelloo app); the switch still worked (API POST went through), only local 1-minute tracking was suppressed.

**Superseded by the owner's approved addition (§4.2):** a mode that cannot track is pointless, so an active petite souris mode now temporarily RE-ENABLES 1-minute polling instead of being silently suppressed. The original suppression survives only as the post-manual-control state (the user explicitly changed polling settings while the mode was active — §4.2 edge case 1), where it remains the correct, observable behavior (info log).

### 4.2 Petite Souris × polling control (owner addition, 2026-10-08 — BINDING)

Petite Souris inherently needs frequent polling: without it the mode cannot track the cat. An active mode is therefore treated as a **temporary override** of the main coordinator's polling settings.

**Mechanism (BINDING):**
- The override engages when the petite souris cat set (`_fast_polling_active`) transitions empty → non-empty, and disengages when it transitions non-empty → empty. All existing mutation sites inherit this: the switch event handler, the `set_petite_souris` service path (via the API-state auto-sync in `_async_update_data` — the service does not fire the bus event), server-side expiry detection (same auto-sync), and the startup restore in `async_setup`.
- While engaged: the main coordinator's `update_interval` is `PETITE_SOURIS_OVERRIDE_INTERVAL_MINUTES` (1 minute == `FAST_POLLING_INTERVAL`), enabled. The legacy fast-polling side timer is NOT started (it would duplicate the 1-minute fetches); a running one is stopped.
- Engagement/disengagement set state only — **never a forced refresh**: every transition path is mediated by a fetch (switch/service paths refresh after their POST; the auto-sync runs inside a fetch; startup runs the first refresh), and HA's post-fetch rescheduling picks the new `update_interval` up naturally, cancelling any pending timer in the process (verified in `update_coordinator.py` 2026.9.0: `_async_refresh` unsubscribes the pending timer first and reschedules after completion from the current interval — so there is no dead window and no stale straggler).
- `async_apply_polling_settings` (any manual change: polling switch, interval number, options flow, update listener) **cancels the override** — edge case 1 below.

**Where the remembered value lives (BINDING, owner requirement 4):** the user's real preference lives ONLY in `entry.options` (`polling_enabled` / `polling_interval`), and the override never writes to it. "Restoration" therefore never reads a snapshot: when the mode ends, settings are re-resolved live via `get_polling_settings(entry)`, so preference changes made while the mode was active are honored. The only override state is two transient, in-memory coordinator flags — `_ps_override` (override engaged) and `_ps_override_cancelled` (manual-control latch, edge case 1) — plus the observable `petite_souris_override` attribute on the diagnostic sensor.

**Edge cases (BINDING resolutions):**

1. **Manual polling change while the mode is active — manual wins.** Any user-initiated polling change (switch toggle, number set, options flow submission, listener apply) cancels the override immediately and applies the user's settings as-is. Justification (least surprising): an explicit user command must never be silently reverted by an automatic boost — a polling switch that flips itself back would be the definition of surprising; it is also the safe direction (worst case tracking pauses until the user re-enables, instead of the API being hammered after an explicit stop). The `_ps_override_cancelled` latch prevents re-engagement on subsequent fetches while the mode is still active server-side; it resets when the mode fully ends, so a later off/on cycle re-engages the boost. Consequences: with polling left enabled, the legacy fast-polling side timer keeps providing 1-minute tracking (the mode still works); with polling disabled, local tracking stops (info log) while the mode's API commands keep working.
2. **Activated while polling was already enabled.** The override engages the same way (uniform semantics: "mode active ⇒ main polls every minute"); the user's configured interval is not clobbered because the override never writes `entry.options` — when the mode ends, the interval is restored by re-resolving the preference.
3. **Activated twice / duration extended / multiple cats.** Engagement is idempotent (transition-guarded): a second activation, a duration extension (API POST with new hours), or a second cat changes nothing while the override is engaged. The override spans "any cat programmed": it engages on the first activation and disengages only when the last cat deactivates (mirroring the side-timer semantics).
4. **Server-side expiry.** Expiry is detected by the API-state auto-sync in `_async_update_data` (`programmed` flips to false) and triggers the identical restoration as a manual deactivation. Because the override keeps 1-minute fetches running, expiry is observed within ~1 minute — this is precisely why the mode must re-enable polling when the preference is disabled (a fully-off integration could not even notice the mode had ended).
5. **Home Assistant restart while the mode is active.** Choice (stated): nothing is persisted for the override. After the startup first refresh, the existing API-state restore repopulates `_fast_polling_active`; the empty → non-empty transition re-engages the override. The "remembered pre-mode state" survives by construction — it IS the user's `entry.options` preference, which was never modified. A mid-mode credential reload behaves the same (fresh coordinator, same reconstruction).

**Observable surfaces:** info logs on engage/disengage/cancel; the diagnostic sensor's `petite_souris_override` attribute. **Amended (owner follow-up 2, 2026-10-08):** the polling switch now makes the override visible itself — `is_on` reports the effective state (reads ON during the boost; the state label must not falsely read as a plain "off" while data flows), a distinct icon (`mdi:clock-fast` vs `mdi:autorenew`), saved/effective attributes (`saved_polling_enabled`, `saved_polling_interval_minutes`, `effective_polling_enabled`, `effective_polling_interval_minutes`), and the "(Petite Souris)" name variant (`entity.switch.polling_enabled_override`, en+fr; renamed with the base name by owner follow-up 4 — now "Tag auto-polling (Petite Souris)" / "Polling auto du tag (Petite Souris)") swapped through the supported `entity_registry.async_update_entity(translation_key=...)` API — HA switch states are binary and `Entity.name`/`Entity.translation_key` are cached properties resolved once (frontend renders registered names from the registry), so the registry update is the only live label channel; the swap is skipped when the entity is unregistered or renamed by the user. The interval number keeps showing the saved preference and exposes `effective_polling_interval_minutes`; the sensor's `petite_souris_override` attribute remains the single source of truth for "is the override running". Both config entities re-render on every coordinator update and entry update so override transitions are visible live.

---

## 5. Runtime application: `async_apply_polling_settings`

New method on `FeellooMainCoordinator` (control point C5):

```python
async def async_apply_polling_settings(self, enabled: bool, interval_minutes: int) -> None:
    """Apply polling settings at runtime (no restart)."""
```

Behavior (BINDING, case table):

| Case | update_interval | Forced refresh? | Rationale |
|------|----------------|-----------------|-----------|
| enabled, interval changed (or enable) | `timedelta(minutes=N)` | **Yes** — `await self.async_request_refresh()` | Applies the new cadence immediately (~debounce 10 s) instead of waiting out the old pending timer; also gives the user fresh data right after enabling |
| disable | `None` | **No** | No point fetching again seconds after the last fetch; see straggler note |
| disabled, interval changed | unchanged (`None`) | No | Interval is stored (`self.polling_interval_minutes`) and used on next enable |

Common rules:
- Always store `self.polling_enabled` and `self.polling_interval_minutes` first, then call `self._sync_fast_polling_timer()` so the C3 gate re-evaluates (e.g., disable while petite souris active stops the fast timer; enable may restart it if petite souris is active).
- If the computed `update_interval` is unchanged, skip both the assignment and the forced refresh (idempotent no-op).
- `async_request_refresh` is debounced (default ~10 s) — acceptable; document in README.

### 5.1 Mid-flight reschedule semantics

Setting `self.update_interval` while a periodic refresh is pending: HA reschedules from the pending refresh's completion (`_async_refresh` → `_schedule_refresh` reads the current `update_interval`). The forced refresh in the "enable/interval-change" cases flushes this path immediately.

### 5.2 Bounded straggler on disable (accepted edge)

After setting `update_interval = None` without a forced refresh, at most **one** already-scheduled periodic refresh may still fire (within at most the previously configured interval, ≤ 24 h worst case; ≤ 5 min in the default case), after which nothing further is scheduled. This is functionally compliant (no continued polling after that single event) and is accepted. The Coder MUST verify the actual behavior against the installed HA's `homeassistant/helpers/update_coordinator.py` and document the observed outcome in the verification record. The ONLY acceptable fallback if the straggler proves disruptive: also force one debounced refresh on disable (one immediate fetch, then clean stop). Any other approach (monkey-patching HA internals, accessing `_unsub_refresh`) is forbidden.

---

## 6. Manual refresh button (BINDING)

New entity in `button.py`: `FeellooRefreshButton(ButtonEntity)` — one per config entry, attached to the hub device.

**Scope resolution (final reading): the button refreshes ALL coordinators.** The owner's "global" phrasing is about entity granularity ("one button that refreshes, not one per cat"), not about which coordinator to touch. Coherence argument: disabling was scoped to the main coordinator because that is the chatty poll (5 m); the other coordinators (15 m–6 h) are unaffected by this spec. For a manual button, the user's intent is "make my Feelloo data current NOW" — a button that refreshed only the main coordinator would leave activity/territory/session sensors visibly stale for up to 15 m / 1 h / 6 h. Cost is a handful of GETs per press. Therefore: press → refresh main, then refresh all five other coordinators.

`async_press` (BINDING):
1. Look up `hass.data[DOMAIN][entry.entry_id]`. If missing → `HomeAssistantError`.
2. `await main.async_request_refresh()` wrapped so a failure raises `HomeAssistantError` (genuine auth/network failure must surface — do not swallow).
3. `await asyncio.gather(*(c.async_request_refresh() for c in [activity, activity_week, activity_month, territory, session]), return_exceptions=True)`; log a warning per exception, do NOT raise (partial refresh is still useful).
4. Order matters: main first because the other coordinators' `_async_update_data` read `main.cats`.
5. Rapid double-press is safe: each coordinator's debouncer coalesces.

Manual refresh works identically whether polling is enabled or disabled (`async_request_refresh` is independent of `update_interval`). The existing `set_petite_souris` service's internal `async_request_refresh` keeps working with polling disabled — explicit user actions always fetch.

---

## 7. Settings surfaces

### 7.1 Options flow (`config_flow.py`, C12) — extend, do not break

`FeellooOptionsFlowHandler.async_step_init` becomes:

Schema:
```python
vol.Optional(CONF_EMAIL, default=current_email): str,
vol.Optional(CONF_PASSWORD, default=""): str,          # blank = keep current
vol.Optional(CONF_POLLING_ENABLED, default=current_enabled): cv.boolean,
vol.Optional(CONF_POLLING_INTERVAL, default=current_interval):
    vol.All(vol.Coerce(int), vol.Range(min=POLLING_INTERVAL_MIN, max=POLLING_INTERVAL_MAX)),
```

Submit logic (BINDING):
1. `new_email = input.get(CONF_EMAIL, current).strip().casefold()`; `new_password = input.get(CONF_PASSWORD, "")`.
2. `credentials_changed = (new_email != current_email) or bool(new_password)`.
3. If `credentials_changed` and `not new_password` → error `password_required`, redisplay (new translation key).
4. If `credentials_changed` → validate with the existing `_async_test_credentials`; failure → existing `invalid_auth` error, redisplay.
5. On success: one single call — `hass.config_entries.async_update_entry(entry, data={CONF_EMAIL, CONF_PASSWORD} if credentials_changed else unchanged, options={**entry.options, CONF_POLLING_ENABLED: …, CONF_POLLING_INTERVAL: …})` — then `async_create_entry(title=email, data={})`.
6. Polling-only submission (blank password, unchanged email) performs NO credential validation and NO `entry.data` change.

Compatibility contract with the existing flow: entering new email+password still validates against Firebase and updates `entry.data` — identical outcome to 1.7.5. Making the password optional-with-blank-default is an additive convenience (required so polling-only edits don't demand the password); it does not remove any capability.

### 7.2 Configuration entities

Two entities, each: plain `SwitchEntity`/`NumberEntity` (NOT `CoordinatorEntity` — the control must remain usable even if the coordinator currently has `last_update_success=False`), `_attr_has_entity_name = True`, attached to the hub device (§8.1), entity category `EntityCategory.CONFIG`.

**Switch `FeellooPollingSwitch`:**
- `unique_id = f"{uid}_polling_enabled"` where `uid = entry.unique_id or entry.entry_id` (config flow sets unique_id to the casefolded email → stable across reinstall, distinct per account).
- `is_on` — **amended (owner follow-up 2, 2026-10-08):** reports the EFFECTIVE polling state: while the §4.2 override runs it reads ON (polling is factually running at 1 minute) even when the saved preference is disabled; otherwise it reads the persisted value via `get_polling_settings(entry)[0]`. Rationale (owner's live-test feedback): a control that reads "off" while data keeps flowing is misleading. HA switch states are binary — no third state exists — so the effective state keeps the label truthful, and the override nuance is carried by the icon + attributes + name variant (§4.2 observable surfaces).
- `async_turn_on/off`: (a) apply live — `await coordinator.async_apply_polling_settings(enabled, current_interval)`; (b) persist — `hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_POLLING_ENABLED: enabled})`. Apply first, persist second. Persisting fires the update listener (§7.3) which re-applies idempotently. **Unchanged by follow-up 2:** turning the switch OFF during the override still cancels the boost (manual wins, §4.2 edge case 1) — it is NOT a no-op: polling stops and the switch visibly flips to OFF.

**Number `FeellooPollingIntervalNumber`:**
- `unique_id = f"{uid}_polling_interval"`; `native_min_value=1`, `native_max_value=1440`, `native_step=1`, `native_unit_of_measurement="min"`, `mode="box"` (repo convention from `petite_souris_duration`).
- `native_value` — **amended (owner follow-up 3, 2026-10-08):** mirrors the switch's effective-state display: while the §4.2 override runs, the value shown is the EFFECTIVE interval (1 minute); otherwise it reads `get_polling_settings(entry)[1]` (the saved preference), and it returns to the saved value automatically when the mode ends. Rationale: the owner's live test showed the number displaying 5 while polling ran at 1 minute — the same dissonance follow-up 2 removed from the switch. The saved preference is always visible via the attributes (`saved_polling_interval_minutes`, `effective_polling_interval_minutes`, `petite_souris_override` — a display mirror of the coordinator's single override flag; the Last Update sensor remains the reference). **Write-path safety (requirement 3, logic unchanged):** `async_set_native_value` reads the enabled flag from the SAVED preference (never the effective override state), persists only the user's input into `entry.options` (which the override never writes), and the apply call cancels the override per the validated manual-wins semantics — so a write during the override updates the preference without corrupting it and cannot fight the override.
- `async_set_native_value`: validate integer within bounds (mirror the existing number entity's validation style), then apply live + persist exactly like the switch. While polling is disabled the value is stored and takes effect on next enable (§5 case table).

### 7.3 Update listener (`__init__.py`, new module function)

```python
async def _async_update_listener(hass, entry) -> None:
```
- Registered per entry via `entry.async_on_unload(entry.add_update_listener(_async_update_listener))` in `async_setup_entry` (C9). HA removes it automatically on unload.
- Logic:
  1. `data = hass.data.get(DOMAIN, {}).get(entry.entry_id)`; if missing → return (entry being torn down).
  2. If `dict(entry.data) != data["active_credentials"]` → credentials changed → `await hass.config_entries.async_reload(entry.entry_id)` and return. This reproduces today's credentials behavior (rebuild `FeellooAuthManager` with the new password) even though the integration now registers a listener.
  3. Otherwise → options-only change → `await data["main"].async_apply_polling_settings(*get_polling_settings(entry))`. No reload: no entity blip, no Firebase re-login.

**HA-version defensive note (for Coder/Reviewer):** whether HA 2024.1 auto-reloads listener-less integrations on options updates does not need to be assumed — this design is correct under both semantics. With the listener registered, listeners run instead of an automatic reload (primary expectation). If the running HA version also schedules a reload on options updates, the outcome is still correct (startup re-reads options at C1) at the cost of a brief reload blip; the listener apply is idempotent. The Coder must verify which behavior is observed on the target install and record it in the verification notes. On the credentials path, if both the automatic reload and the listener reload fire, HA tolerates the duplicate reload (guarded by entry state) — acceptable.

---

## 8. Entity and device surface

### 8.1 Hub device (new, one per config entry)

Registered in `_async_setup_devices` alongside cat devices:
- `identifiers = {(DOMAIN, entry.entry_id)}`, `config_entry_id = entry.entry_id`
- `name = "Feelloo"`, `manufacturer = "Feelloo"`, `model = "Account"`

Created unconditionally (even with zero cats), before platforms load (`async_setup()` runs before `async_forward_entry_setups`).

### 8.2 New entities (all attached to the hub device)

| Entity | Platform/class | unique_id | Category | Translation key | Icon |
|--------|----------------|-----------|----------|-----------------|------|
| Tag auto-polling toggle  *(renamed, follow-up 4)* | `switch.py` `FeellooPollingSwitch` | `{uid}_polling_enabled` | CONFIG | `switch.polling_enabled` | `mdi:autorenew` |
| Tag polling interval  *(renamed, follow-up 4)* | `number.py` `FeellooPollingIntervalNumber` | `{uid}_polling_interval` | CONFIG | `number.polling_interval` | `mdi:clock-outline` |
| Refresh data | `button.py` `FeellooRefreshButton` | `{uid}_refresh_data` | none (primary) | `button.refresh_data` | `mdi:refresh` |
| Last update | `sensor.py` `FeellooLastUpdateSensor` | `{uid}_last_update` | DIAGNOSTIC | `sensor.last_update` | `device_class: TIMESTAMP` |

`uid = entry.unique_id or entry.entry_id`. **Amended (owner follow-up 4, 2026-10-08):** the first two rows' display names are renamed (en 'Tag auto-polling' / 'Tag polling interval'; fr 'Polling auto du tag' / 'Intervalle de polling du tag') — display-only, unique_ids and translation keys unchanged; existing installs' entity_ids never change, fresh installs generate from the new names (e.g. `switch.feelloo_tag_auto_polling`). `FeellooLastUpdateSensor` is a `CoordinatorEntity` on the main coordinator: `native_value = coordinator.last_successful_fetch` (C4, may be `None` → "unknown" before first success), `extra_state_attributes = {"polling_enabled": …, "polling_interval_minutes": …, "petite_souris_override": …}` read from the coordinator's runtime attributes — these reflect the **effective** state (during the §4.2 override they show the temporary 1-minute cadence), while the polling switch and number show the user's saved preference. Default `CoordinatorEntity.available` is kept (diagnostic truthfulness: it goes unavailable on a genuine refresh failure — that is desirable and does not affect the last-known-value guarantee, which concerns the DATA entities, §9).

Multi-account: every entity is per config entry; unique_ids are email-based → no collisions between accounts.

### 8.3 Translations (en.json + fr.json, both required)

- `options.step.init.description`: mention credentials + polling.
- `options.step.init.data`: `polling_enabled`, `polling_interval` labels.
- `options.error`: new `password_required`.
- `entity.switch.polling_enabled`, `entity.number.polling_interval`, `entity.button.refresh_data`, `entity.sensor.last_update`.

Exact strings:

| Key | en | fr |
|-----|----|----|
| options.step.init.data.polling_enabled | Enable automatic polling | Activer le polling automatique |
| options.step.init.data.polling_interval | Polling interval (minutes) | Intervalle de polling (minutes) |
| options.error.password_required | Password is required when changing the email address. | Le mot de passe est requis pour changer l'adresse e-mail. |
| entity.switch.polling_enabled | **Amended (follow-up 4):** Tag auto-polling | **Amended (follow-up 4):** Polling auto du tag |
| entity.switch.polling_enabled_override *(added follow-up 2; renamed with the base name by follow-up 4)* | Tag auto-polling (Petite Souris) | Polling auto du tag (Petite Souris) |
| entity.number.polling_interval | **Amended (follow-up 4):** Tag polling interval | **Amended (follow-up 4):** Intervalle de polling du tag |
| entity.button.refresh_data | Refresh Data | Actualiser les données |
| entity.sensor.last_update | Last Update | Dernière mise à jour |

Follow the repo convention: translations only in `translations/{en,fr}.json` (there is no `strings.json` — do not add one).

### 8.4 Version and docs (release requirements)

- `manifest.json` `"version"`: `1.7.5` → `"1.8.0"` (user-facing features → minor bump; repo history follows this). Git tag `v1.8.0` per repo convention (`v1.7.5` etc.).
- `README.md`: new "Polling Control" section (entities, options flow, defaults, bounds, what disable means, petite souris interplay, last-known-value guarantee); add the 4 new entities to the entity list; fix the Architecture coordinator table to the actual six coordinators and note the main interval is configurable. (The current table claims three coordinators — doc drift to fix in this release.)

---

## 9. Last-known-value rule (BINDING)

**Verified current behavior (base `59e0361`):** on a refresh failure the coordinator keeps its last `self.data` and flips `last_update_success=False`. Availability today per platform:
- main sensors (`FeellooSensorBase.available = _get_cat() is not None`): keep values, stay available;
- petite souris switch and ring button (custom `available`): keep values, stay available;
- binary sensors, device tracker, duration number (`super().available and …`): go unavailable.

**Rule:** with polling DISABLED there are no scheduled refreshes, hence no refresh failures, hence `last_update_success` stays `True` and ALL entities keep their last known values and availability — automatically. **No availability-masking code may be added.** Specifically:
1. Disabling must never be implemented by raising errors or clearing `coordinator.data` (both would cause unavailability or value loss).
2. The genuine unavailability path must remain intact: an `UpdateFailed` on any refresh (startup, manual button, or while polling is enabled) still flips `last_update_success=False` and coordinator-gated entities (binary sensors, device tracker, duration number) still become unavailable. `ConfigEntryAuthFailed` still surfaces for re-auth.
3. Data age in the UI: the `FeellooLastUpdateSensor` timestamp freezes at the last successful fetch; the `polling_enabled` attribute explains why. README documents this.

---

## 10. Verification procedure and test matrix

The repo has **no test infrastructure** (no `tests/`, no pytest/requirements — verified). Do not create a test framework in this spec. Verification is a documented manual procedure on the owner's live HA + real account (read-only observations; one optional reversible network-interrupt test).

Logging setup (all cases): enable `logger` for `custom_components.feelloo: debug` and `homeassistant.helpers.update_coordinator: debug`. The coordinators log `Finished fetching feelloo_main data in … seconds` per fetch — this is the polling heartbeat to observe.

**Procedure / matrix (all rows required, record PASS/FAIL + observed notes):**

| # | Case | Steps | Expected |
|---|------|-------|----------|
| V1 | Default upgrade path | Install 1.8.0 over 1.7.5 with no options set; watch logs 15 min | 5-minute cadence unchanged (V-default identical to 1.7.5); 4 new entities + hub device present; no reload blips |
| V2 | Disable via options flow | Options → set polling off, blank password, submit | No credential validation call; entities keep values; after the bounded straggler (≤1 fetch, ≤5 min default) zero periodic main fetches; diagnostic sensor timestamp frozen; binary sensors + tracker stay available |
| V3 | Disable via config switch | Toggle "Tag auto-polling" off | Same outcome as V2; no entity-wide unavailable blip (no entry reload observed in logs); instant state feedback |
| V4 | Re-enable via switch | Toggle on | One main fetch within ~10 s (debounce), then cadence resumes at configured interval |
| V5 | Change interval live | Set number 5→10 with polling on | One fetch within ~10 s, then 10-minute cadence; no restart, no reload, all entity states continuous |
| V6 | Interval via options flow | Options → 10, submit | Applied on flow completion; credentials untouched; works without password entry |
| V7 | Manual button (polling on) | Press "Refresh Data" | Six `Finished fetching feelloo_*` log lines (main + 5 others); diagnostic timestamp updates |
| V8 | Manual button (polling off) | Press button | Main + all five coordinators fetch once; diagnostic timestamp updates; polling stays off afterwards (no timer starts) |
| V9 | Petite souris + polling on | Turn petite souris ON | Existing behavior preserved: 1-minute fast polling timer runs |
| V10 | Petite souris + polling OFF (**amended by §4.2**) | With polling disabled, turn petite souris ON | API POST succeeds (switch state reflects server); **temporary 1-minute polling override engages** (info log; main fetches run every minute despite the disabled preference); no side timer started; `entry.options` untouched; manual button still available. Post-manual-control suppression is covered by V17 |
| V11 | Restart with polling disabled | Restart HA | Startup first refresh runs (entities populated, diagnostic timestamp = boot time), then zero periodic fetches (logs); options persisted |
| V12 | Genuine failure path (reversible) | With polling ON, briefly cut WAN (~30 s), force refresh via button | Coordinator-gated entities (binary sensor, device tracker, duration number) go unavailable — failure must still surface; main sensors keep last values; restore WAN, press button → all recover |
| V13 | Credentials flow still works | Options → new email + password | Validated against Firebase; entry reloads; coordinators rebuilt with new auth (same as 1.7.5) |
| V14 | HA behavior note | During V3/V5, record whether an entry reload occurred | Records which listener/auto-reload semantics the running HA exhibits; either outcome acceptable per §7.3; document observed |
| V15 | Petite souris ON with polling disabled (§4.2) | With polling disabled, turn petite souris ON (switch, service, or app) | Info log "temporary 1-minute polling override engaged"; main fetch cadence = 1 minute; `entry.options` still shows disabled; sensor `petite_souris_override=true` and attributes show the effective 1-minute cadence; no side timer |
| V16 | Petite souris OFF restores state (§4.2) | Turn petite souris OFF (after V15) | Info log "polling settings restored"; polling disabled again (zero periodic fetches after ≤1 straggler); options unchanged throughout; diagnostic timestamp freezes again |
| V17 | Manual change during mode (§4.2 edge 1) | While petite souris active: (a) toggle polling OFF, then (b) re-enable or set the interval | (a) Override cancelled (log), polling stops, no re-engage on subsequent fetches, mode API commands still work; (b) manual settings apply; with polling enabled the legacy side timer resumes 1-minute tracking; a petite souris off/on cycle re-engages the boost |
| V18 | Mode expiry with polling disabled (§4.2 edge 4) | Program petite souris (short duration) with polling disabled; wait for expiry | 1-minute cadence continues until expiry is detected (≤~1 min late); restoration identical to V16 |
| V19 | Restart while petite souris active (§4.2 edge 5) | Restart HA with the mode active and polling preference disabled | Startup first refresh runs; override re-engages from the cloud's programmed state (info log); options untouched; when the mode later ends, polling is disabled again |
| V20 | Override visibility on the polling switch (owner follow-up 2) | With polling preference disabled, activate Petite Souris; then turn the polling switch OFF; then let the mode end | During the boost: the switch reads ON (effective state), shows the fast-clock icon, the "(Petite Souris)" label — renamed with the base name by follow-up 4: now "Tag auto-polling (Petite Souris)" / "Polling auto du tag (Petite Souris)" — and saved + effective attributes; turning it OFF cancels the boost and visibly flips the switch to OFF (not a no-op); when the mode ends the switch returns to the saved state automatically; the label renders in both en and fr |
| V21 | Number shows the effective interval (owner follow-up 3) | With polling preference 5 min, activate Petite Souris; optionally set the number during the boost; then let the mode end | During the boost: the number displays 1 (the effective interval), attributes carry saved (5) + effective (1) + the override flag; writing the number during the boost updates the SAVED preference and cancels the boost (display converges; polling stays off if the preference was disabled); after the mode ends the number returns to the saved value automatically |

Additional reviewer checks: translations render in en and fr; unique_ids stable across HA restart; hub device shows all 4 entities; no changes to the five secondary coordinators' intervals (verify by log cadence 15 m/15 m/30 m/1 h/6 h untouched).

**Data safety statement (explicit):** this feature performs no destructive or irreversible operation. It only adds local settings and read-only GET fetches identical to today's polling; the only write action in scope is updating the config entry options. V12 uses a temporary, fully reversible network interruption. No data migration, no deletion, no server-side state change.

---

## 11. Deliverable files for the Coder (from this spec set)

- `specs/047-polling-control/spec.md` — requirements and scope
- `specs/047-polling-control/plan.md` — implementation order and acceptance criteria
- `specs/047-polling-control/research.md` — codebase findings and HA behavior facts
- `specs/047-polling-control/data-model.md` — persisted/registry/translation model
- `specs/047-polling-control/quickstart.md` — owner-facing usage guide
- `specs/047-polling-control/contracts/polling-control.md` — this contract (BINDING)