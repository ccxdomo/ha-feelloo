# Research 047 — Codebase Findings (ha-feelloo @ 59e0361)

All findings verified by reading the repository directly. Line numbers refer to `custom_components/feelloo/` files at commit `59e0361` (v1.7.5).

## 1. Repo layout and conventions

- HACS custom component: `custom_components/feelloo/` (hacs.json: `content_in_root: false`, HA ≥ 2024.1.0, country FR, render_readme true).
- Platforms in `PLATFORMS` (`__init__.py:18`): BINARY_SENSOR, SENSOR, BUTTON, DEVICE_TRACKER, SWITCH, NUMBER — the new entities need **no new platform**.
- `manifest.json`: version 1.7.5, domain `feelloo`, config_flow true, no requirements/dependencies, iot_class `cloud_polling`.
- Translations: `translations/en.json`, `translations/fr.json` only (no `strings.json`). Entity names come from `entity.<platform>.<translation_key>` sections; options flow strings from `options.step.init`.
- Git conventions: conventional commits (`feat:`, `fix:`, `chore: bump version to X.Y.Z`), tags `v1.X.Y` (latest `v1.7.5`).
- **No test infrastructure**: no `tests/`, no pytest config, no requirements files (verified by search). → manual verification procedure (contract §10).
- Entity naming style: `_attr_has_entity_name = True` + `_attr_translation_key` + per-entity `unique_id = f"{id}_{key}"`; per-cat devices `identifiers = {(DOMAIN, cat_uid)}`, manufacturer Feelloo, model "Cat Tracker".
- README drift: the Architecture table documents **three** coordinators; the code has **six** (main, activity, activity_week, activity_month, territory, session). Fix included in this release's doc updates.

## 2. Coordinator architecture (coordinator.py)

| Coordinator | Class / line | `update_interval` line | Fixed interval (const.py) |
|-------------|--------------|----------------------|---------------------------|
| Main (cats) | `FeellooMainCoordinator` :176 | :192 | `CATS_UPDATE_INTERVAL` 5 min |
| Activity | :364 | :376 | `ACTIVITY_UPDATE_INTERVAL` 15 min |
| Activity week | :414 | :426 | 1 h |
| Activity month | :467 | :479 | 6 h |
| Territory | :520 | :532 | 15 min |
| Session | :582 | :594 | 30 min |

### 2.1 Main coordinator specifics (`FeellooMainCoordinator`)
- `async_setup()` :195: `auth.async_ensure_token()` → token refresh timer `async_track_time_interval(... TOKEN_REFRESH_INTERVAL 50 min)` :198 → fast-polling event listener (`feelloo_fast_polling` bus event) → **`await self.async_config_entry_first_refresh()` :204** → restore `_fast_polling_active` from API `programmed` state → `_sync_fast_polling_timer()` :215 → `_async_setup_devices()`.
- Fast polling: `_sync_fast_polling_timer` :246 starts/stops an `async_track_time_interval` timer at `FAST_POLLING_INTERVAL` (1 min) :250 calling `async_request_refresh`; driven by `_fast_polling_active` cat-id set; also auto-synced from API state inside `_async_update_data` :318. Event handler `_handle_fast_polling_event` reacts to the petite souris switch firing `feelloo_fast_polling` (switch.py).
- Token refresh callback (~:263) refreshes the Firebase idToken every 50 min; independent of data polling.
- `_async_update_data` :274: GET `/users/cats`, then per-cat GET `/users/cats/{cat_id}` enrichment; returns `{"cats": [...]}`. Raises `UpdateFailed` on bad payloads.
- `async_shutdown` :218: cancels token listener, fast-polling listener/timer, `super().async_shutdown()`.

### 2.2 hass.data layout (`__init__.py:50-59`)
`hass.data[DOMAIN][entry.entry_id]` = dict with keys `auth`, `main`, `activity`, `activity_week`, `activity_month`, `territory`, `session` (all seven created before any first refresh; secondary coordinators read `main.cats` from this dict during updates).

### 2.3 Setup/unload flow (`__init__.py`)
- `async_setup_entry`: create auth + main (main does its own first refresh inside `async_setup()` :32), create 5 secondary coordinators, populate `hass.data`, first-refresh the 5 secondaries in a loop (warning on `UpdateFailed`), register the `set_petite_souris` service once (guard `hass.services.has_service` :78), forward to platforms :114.
- `async_unload_entry` :117: unload platforms, shutdown all 7 objects, remove service if no entries remain.
- `async_reload_entry` :139 is a module function that is **not referenced anywhere** (no update listener registered anywhere in the integration) — dead code. Do not confuse it with the update-listener mechanism; leave it or remove it (Coder's discretion, optional, non-breaking).

## 3. Config flow (config_flow.py)

- `FeellooConfigFlow` :71, `VERSION = 1`, unique_id = casefolded email.
- `FeellooOptionsFlowHandler` :109, single `async_step_init` :116: schema requires email (default = current) + password (no default); validates credentials via `_async_test_credentials` (Firebase signInWithPassword); on success updates `entry.data` :129 and finishes. Options flow today never touches `entry.options`.
- Consequence today: changing credentials updates `entry.data`; the entry is rebuilt on the next setup path (HA's update semantics for listener-less integrations reload the entry), which is how the new password reaches a rebuilt `FeellooAuthManager`.

## 4. Availability / last-known-value behavior today (base 59e0361)

On a failed refresh, `DataUpdateCoordinator` keeps the previous `self.data` and sets `last_update_success=False`. Current entity overrides:

| Entity group | `available` implementation | Behavior on refresh failure |
|--------------|---------------------------|------------------------------|
| Main sensors (`FeellooSensorBase`) | `self._get_cat() is not None` | **Keeps last value, stays available** (custom override, ignores coordinator failure) |
| Binary sensors | `super().available and _get_cat() is not None` | Goes unavailable (`super().available` = `last_update_success`) |
| Device tracker | `super().available and _get_cat() is not None` | Goes unavailable |
| Petite souris switch | `_get_cat() is not None` | Stays available |
| Duration number | `super().available and _get_cat() is not None` | Goes unavailable |
| Ring button | cat present + `can_ring` | Stays available |

**Key inference for the design:** disabling polling via `update_interval=None` causes **no refreshes at all** → no failures → `last_update_success` stays `True` → **all** entities keep last known values and availability with zero availability-masking code. The owner's requirement 4 is satisfied structurally; the only forbidden implementation would be "disable by making updates fail" (which WOULD flip `last_update_success` and drop binary sensors/tracker to unavailable).

## 5. Home Assistant behavior facts (with confidence notes)

Grounded, stable facts the design relies on:
1. `DataUpdateCoordinator(update_interval=None)` never schedules periodic refreshes; manual `async_request_refresh()`/`async_refresh()`/`async_config_entry_first_refresh()` work regardless of `update_interval`. Stable documented behavior, available in HA 2024.1. → basis of C1/C2 and the button.
2. A pending scheduled refresh may fire once after `update_interval` is set to `None` mid-flight; after that, no further scheduling occurs (reschedule happens after each refresh reads the current `update_interval`). → the bounded-straggler edge, contract §5.2. **Coder must verify against the installed `homeassistant/helpers/update_coordinator.py`** (which file may be read directly in the HA installation) and record the observed behavior; contract allows exactly one fallback if needed (forced single refresh on disable).
3. `async_request_refresh` is debounced (default ~10 s cooldown) and coalesces concurrent requests — rapid double-press of the new button is safe; also why "apply changes" is observable within ~10 s.
4. `entry.add_update_listener(listener)` + `entry.async_on_unload(...)` register an options/data update listener, auto-removed on unload. With listeners registered, updates call the listener (this is the mechanism this design uses to apply polling changes without a reload, and to reload on credential changes). Confidence: high (documented API).

Version-sensitive point (explicitly handled): whether a listener-less integration ALSO gets an automatic reload on options/data updates in the target HA version. The design (contract §7.3) is correct under both semantics: listener path = smooth live apply; auto-reload path = entry rebuilt, startup re-reads options at C1 (same outcome, brief blip). V14 of the test matrix records which behavior is observed.

## 6. Decisions and rationale (Architect)

1. **Disable = `update_interval=None`** (not error-raising, not a no-op `_async_update_data`, not entry-level hacks). Cheapest, uses the coordinator's own contract, preserves last-known-value automatically, and `async_config_entry_first_refresh` still runs at startup (C2).
2. **Live apply method on the main coordinator** (`async_apply_polling_settings`) + forced debounced refresh only on enable/interval-change; none on disable (avoid pointless fetch; straggler accepted and bounded).
3. **Fast polling gated by the same setting** (C3 in `_sync_fast_polling_timer`, single choke point reached by all call sites). Fast polling is main-coordinator automatic polling; leaving it running would silently violate "disabled". Petite souris API actions still work; only local 1-min tracking stops.
4. **Token refresh keeps running** — auth housekeeping, needed by the manual button and petite souris commands; not data polling.
5. **Button refreshes all coordinators** (main first, then the other five concurrently, partial failures logged not raised; main failure raises `HomeAssistantError`). "Global" = one button for everything; justification in contract §6.
6. **Update listener + `active_credentials` stash**: listener distinguishes credential changes (reload, preserving today's behavior) from options-only changes (live apply, no reload). No assumptions about auto-reload semantics required.
7. **Config entities are plain entities, not CoordinatorEntities**: the polling control must be usable even when the coordinator is in a failed state; availability of the controls never depends on API health.
8. **Hub device** (identifiers `(DOMAIN, entry.entry_id)`, name "Feelloo", model "Account") hosts the 4 new entities — standard HA pattern for config/global entities; per-cat devices unchanged.
9. **unique_ids from `entry.unique_id`** (casefolded email; fallback `entry.entry_id`): stable across reinstall of the same account, collision-free across multiple accounts, consistent with the config flow.
10. **Interval stored in minutes as int**, bounds 1–1440, default 5, `mode="box"` per repo convention; invalid stored values fall back to defaults (defensive resolution), never crash startup.
11. **Options flow: password becomes `vol.Optional(default="")`** (blank = keep current) so polling-only edits don't demand the password; credentials are still validated whenever actually changed; `password_required` error added for email-change-without-password.
12. **Diagnostics timestamp sensor** (`last_successful_fetch` set at the end of a successful `_async_update_data`) — does not depend on HA's `last_update_success_time` (whose availability varies by version), keeps the data-age surface self-contained; carries `polling_enabled`/`polling_interval_minutes` attributes.

## 7. Open questions — resolved

- Button scope (main only vs all): **all coordinators** — see §6.5 and contract §6.
- Does disable also stop petite souris fast polling: **yes** — see §6.3.
- Should disable stop token refresh: **no** — see §6.4.
- Straggler fetch after disable: accepted, bounded (≤1 fetch, ≤ previous interval), verification row V2; single sanctioned fallback documented.
- Test framework: none exists; manual procedure with matrix instead (contract §10).

## 8. Addendum (2026-10-08 — owner addition supersedes §6.3)

The owner's approved addition (Petite Souris × polling interplay, contract §4.2) supersedes decision §6.3 above: an active petite-souris mode now temporarily overrides polling to 1 minute instead of being suppressed. The suppression survives only as the post-manual-control state (the user explicitly changed polling settings while the mode was active).

Verified facts reused by the new design:
- `_async_refresh` unsubscribes the pending scheduled timer at its start and reschedules after completion from the CURRENT interval — so a mid-fetch interval change (the auto-sync engagement path) applies with no dead window, no forced refresh, and no stale straggler.
- The API-state auto-sync inside `_async_update_data` is the single choke point that also covers the `set_petite_souris` SERVICE path (the service does not fire the `feelloo_fast_polling` bus event — only the switch does) and server-side expiry; driving the override transitions from `_sync_fast_polling_timer` (called by every mutation site) therefore covers all activation/deactivation paths.
- `Debouncer` cooldown is 10 s (`REQUEST_REFRESH_DEFAULT_COOLDOWN`), relevant only to the manual `async_apply_polling_settings` path — the override path performs no refreshes at all.
- Minimum HA (Reviewer follow-up, 2026-10-08): the merged options-flow fix requires the base `OptionsFlow.config_entry` resolution, which first shipped in HA 2024.12.0 (2024.1–2024.11: no base property, no manager assignment — no-arg handlers break with `AttributeError`; 2024.12.0: resolving property + deprecated manual setter; 2025.1: `breaks_in_ha_version="2025.12"` on the setter; 2026.9: setter removed, read-only). `hacs.json` pin raised 2024.1.0 → 2024.12.0; every mechanism added by 047 itself predates 2024.1.
- Override visibility facts (owner follow-up 2, source-verified in 2026.9.0 `helpers/entity.py` + `helpers/entity_registry.py`): HA switch states are binary (no third state); `Entity.name` and `Entity.translation_key` are `@cached_property` resolved once, and the frontend renders registered entities' names from the entity REGISTRY (`translation_key` column, storage v1.9) — a dynamic in-entity key would never re-render (and would make registration nondeterministic). The supported live label channel is `entity_registry.async_update_entity(entity_id, translation_key=...)` (`RegistryEntry.name` = user rename guard). Icons (`icon` property) and `extra_state_attributes` re-render on every state write — so the visible override signal is carried by is_on=effective + icon + attributes + the registry label swap.
- Follow-up 3 (owner live test): the interval number displayed 5 while the override ran at 1 minute — the same dissonance the owner had just removed from the switch. Resolution: the number now displays the EFFECTIVE interval during the override (mirroring the switch's effective-state display), with the saved preference moved to symmetrical attributes (`saved_polling_interval_minutes` / `effective_polling_interval_minutes` / `petite_souris_override`). The write path needed NO logic change — verified safe by construction: the enabled flag is read from the SAVED preference (never the effective override state), only the user's input is persisted into `entry.options` (which the override never writes), and the apply call cancels the override per the validated manual-wins semantics.