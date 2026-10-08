# Plan 047 — Implementation Plan (for the Coder)

Binding reference: `specs/047-polling-control/contracts/polling-control.md` (control points C1–C12, case table §5, entity surface §8, verification matrix §10). This plan orders the work; the contract defines it. No source code is modified by the Architect; the Coder implements against base `59e0361`.

## Task order and acceptance criteria

### T1 — `const.py`: settings constants + resolver
Add `CONF_POLLING_ENABLED`, `CONF_POLLING_INTERVAL`, `DEFAULT_POLLING_ENABLED`, `DEFAULT_POLLING_INTERVAL`, `POLLING_INTERVAL_MIN`, `POLLING_INTERVAL_MAX`, and `get_polling_settings(entry)` (contract §2.2 semantics: missing/non-bool/non-int/out-of-range → defaults; never raises).
**Accept:** importing const.py has no side effects; resolver pure function; default resolution `(True, 5)`.

### T2 — `coordinator.py`: main coordinator polling control
- C1: constructor resolves settings; `update_interval=timedelta(minutes=N) if enabled else None`; store `self.polling_enabled`, `self.polling_interval_minutes`, `self.last_successful_fetch = None`.
- C5: `async_apply_polling_settings(enabled, interval_minutes)` implementing the contract §5 case table exactly (store attributes → `_sync_fast_polling_timer()` → update `update_interval` if changed → forced debounced refresh only on enable/interval-change-while-enabled; no forced refresh on disable; full no-op when nothing changed).
- C3: gate `_sync_fast_polling_timer` on `not self.polling_enabled` (stop any running timer, info log, return).
- C4: set `self.last_successful_fetch = dt_util.now()` as last statement of successful `_async_update_data`; optional debug log at method entry.
- C11: `_async_setup_devices` also registers the hub device (identifiers `(DOMAIN, entry.entry_id)`, name "Feelloo", manufacturer "Feelloo", model "Account", config_entry_id).
**Accept:** with polling disabled, startup first refresh (:204) still runs; fast polling cannot start; token timer (:198) untouched; other five coordinators untouched.

### T3 — `__init__.py`: listener + credentials stash
- C8: add `"active_credentials": dict(entry.data)` to the entry's hass.data dict.
- C9: register `entry.async_on_unload(entry.add_update_listener(_async_update_listener))` after hass.data population.
- New module function `_async_update_listener` per contract §7.3: reload on credential change; otherwise `main.async_apply_polling_settings(*get_polling_settings(entry))`; tolerate missing hass.data entry (being torn down).
- Optional cleanup: unused `async_reload_entry` (:139) may be removed (non-breaking) — Coder's discretion.
**Accept:** options-only change → no reload (entities stay available, no "Setting up entry" in logs); credential change → entry reloads and rebuilds auth (V13).

### T4 — `config_flow.py`: extend options flow (C12)
Single init step with `vol.Optional` fields per contract §7.1 (email default current, password default "" = keep, `cv.boolean` for enabled, coerced int Range 1..1440 for interval). Submit logic: `password_required` error when email changed without password; validate credentials only when changed (`invalid_auth` on failure); single `async_update_entry` call merging options and (conditionally) data; `async_create_entry(title=email, data={})`.
**Accept:** polling-only edit needs no password and performs no Firebase call; credential edit still validated; invalid interval impossible via flow (schema bounds).

### T5 — Entities
- `switch.py`: `FeellooPollingSwitch` — plain `SwitchEntity`, CONFIG, hub device, unique_id `{uid}_polling_enabled`, translation key `polling_enabled`, icon `mdi:autorenew`; `is_on` from `get_polling_settings`; turn on/off = `async_apply_polling_settings` then persist options (contract §7.2 order: apply first, persist second).
- `number.py`: `FeellooPollingIntervalNumber` — plain `NumberEntity`, CONFIG, min 1 / max 1440 / step 1 / unit "min" / mode "box", icon `mdi:clock-outline`, unique_id `{uid}_polling_interval`, translation key `polling_interval`; `async_set_native_value` validates (int, bounds — mirror existing number entity style) then apply+persist.
- `button.py`: `FeellooRefreshButton` — `ButtonEntity`, no category, icon `mdi:refresh`, unique_id `{uid}_refresh_data`, translation key `refresh_data`; `async_press` per contract §6 (main first — `HomeAssistantError` on failure; then `asyncio.gather(..., return_exceptions=True)` over the five others, warn per exception).
- `sensor.py`: `FeellooLastUpdateSensor` — `CoordinatorEntity(main)`, DIAGNOSTIC, `device_class=TIMESTAMP`, translation key `last_update`, unique_id `{uid}_last_update`, hub device; `native_value = coordinator.last_successful_fetch`; attributes `polling_enabled`, `polling_interval_minutes`. Add alongside existing setup; the existing early-return when `main.cats is None` stays (documented edge: diagnostic sensor skipped in the zero-cat corner case).
**Accept:** entities appear on the "Feelloo" hub device; multi-account ids distinct; controls usable regardless of coordinator failure state; entities survive HA restart with same ids/states.

### T6 — Translations
`translations/en.json` + `translations/fr.json`: options strings (2 data labels, updated description, `password_required` error) and the four entity names — exact strings in contract §8.3.
**Accept:** options form and all four entity names render in both languages.

### T7 — Release metadata + docs
- `manifest.json` version → 1.8.0.
- `README.md`: new "Polling Control" section (settings surfaces, defaults, bounds, disable semantics incl. petite souris interplay + last-known-value + data-age sensor, manual button scope); add the four entities to the entity list; fix the Architecture coordinator table (six coordinators, main interval configurable).
**Accept:** docs match implemented behavior; no stale claims.

### T8 — Verification (contract §10 matrix V1–V14)
Run the manual matrix on the owner's live install with debug logging (`custom_components.feelloo`, `homeassistant.helpers.update_coordinator`). Record PASS/FAIL + observed notes per row, including:
- V2 straggler observation (verify against installed `update_coordinator.py`; the single sanctioned fallback is documented in contract §5.2);
- V14 listener vs auto-reload behavior of the running HA version.
**Accept:** all rows PASS (or carry an explicitly documented, contract-sanctioned note); record delivered to the Reviewer with the code.

### T9 — Petite Souris × polling interplay (owner addition 2026-10-08, contract §4.2)
- `const.py`: `PETITE_SOURIS_OVERRIDE_INTERVAL_MINUTES = 1` (== FAST_POLLING_INTERVAL).
- `coordinator.py`: transient `_ps_override` / `_ps_override_cancelled` flags; `petite_souris_override` property; internal `_set_effective_polling` (no forced refresh) and `_restore_user_polling_settings` (re-resolves `get_polling_settings(entry)` live); `_sync_fast_polling_timer` extended — engage override on set empty→non-empty, disengage + restore on non-empty→empty, reset the cancel latch when the mode ends, side timer suppressed during override; `async_apply_polling_settings` cancels the override on any manual call (before the idempotency early-return).
- `sensor.py`: diagnostic sensor exposes `petite_souris_override` (effective-state attributes).
- README/quickstart/contract/data-model updated for the interplay.
**Accept:** V15–V19 behavior; `entry.options` NEVER written by the override; override transitions perform no forced refresh; manual-wins with the cancelled latch (no re-engage while the mode stays active, re-engage after a full off/on); restart reconstruction from the API `programmed` state; polling switch/number behavior unchanged (they read the preference). *(Superseded in part by T10: the switch now shows the EFFECTIVE state while the override runs — command behavior unchanged.)*

### T10 — Override visibility on the polling switch (owner follow-up 2, 2026-10-08)
- `switch.py`: `is_on` reports the effective state during the §4.2 override (reads ON); dynamic icon (`mdi:clock-fast` while overridden, `mdi:autorenew` otherwise); `extra_state_attributes` = `saved_polling_enabled` / `saved_polling_interval_minutes` / `effective_polling_enabled` / `effective_polling_interval_minutes`; coordinator listener (`async_add_listener`) for live re-render on override transitions; entity-registry `translation_key` swap to `polling_enabled_override` via the supported `async_update_entity` API (guarded: skip when unregistered or user-renamed).
- `number.py`: `native_value` unchanged (saved preference); `effective_polling_interval_minutes` attribute + coordinator listener. *(Superseded by T11: `native_value` now displays the effective interval during the override; write path unchanged.)*
- `translations/en.json` + `fr.json`: `entity.switch.polling_enabled_override.name` (full parity).
- README/quickstart/contract/data-model updated for the visible-override behavior.
**Accept:** V20 matrix row; the OFF-during-override command semantics unchanged and visibly NOT a no-op (switch flips ON→OFF, polling stops); the last-update sensor's `petite_souris_override` attribute remains the single source of truth; labels exist in both languages.

### T11 — Number displays the effective interval (owner follow-up 3, 2026-10-08)
- `number.py`: `native_value` displays the EFFECTIVE interval while the §4.2 override runs (1 minute), otherwise the saved preference; attributes `saved_polling_interval_minutes` / `effective_polling_interval_minutes` / `petite_souris_override` (mirroring the switch's attribute naming); write path UNCHANGED (reads the SAVED enabled flag, persists only the user's input, the apply call cancels the override — manual wins).
- README.md + README_FR.md (both): the "keeps showing your saved preference" sentences replaced in both languages; quickstart updated.
**Accept:** V21 matrix row; write-during-override cannot corrupt the preference (harness-proved, including with a disabled preference); the number returns to the saved value automatically after mode end; attribute naming symmetrical with the switch.

## Notes for Reviewer

Check especially: no changes to the five secondary coordinators' `update_interval` lines (376/426/479/532/594); no availability-masking code added (contract §9 forbids it); disable never raises; `entry.data` shape unchanged; listener idempotence; options flow backward compatibility (credentials path); translations complete in both languages; unique_id scheme (entry.unique_id with entry_id fallback).