# Plan 048 — Implementation Plan (for the Coder)

Binding reference: `specs/048-secondary-polling-intervals/contracts/secondary-polling.md` (control points C1–C16, §5 case table, §6 entity surface, §7 no-hiding rule, §8 strings, §9 traffic, §10 docs, §11 verification). This plan orders the work; the contract defines it. No source code is modified by the Architect; the Coder implements against base `4f32b05` (v1.8.0).

## Task order and acceptance criteria

### T1 — `const.py`: keys, defaults, registry dict, resolver
Add the five `CONF_POLLING_INTERVAL_*` keys, the five `DEFAULT_POLLING_INTERVAL_*` constants (values 15/60/360/15/30, comments tying each to its `*_UPDATE_INTERVAL` constant), `SECONDARY_POLLING_INTERVALS` (contract §2.1), and `get_secondary_polling_intervals(entry)` (contract §2.2 semantics: per-key missing / non-coercible / out-of-`[1, 1440]` → default, never the bound; strings coerce; floats truncate via `int()`; never raises; tolerates missing `options`). A private `_resolve_int_minutes` helper is permitted.
**Accept:** importing `const.py` has no side effects; resolver is pure; no-options resolution is exactly `{activity: 15, activity_week: 60, activity_month: 360, territory: 15, session: 30}`; the timedelta constants remain in the file.

### T2 — `coordinator.py`: base class + five subclass conversions
- C8: new `FeellooSecondaryCoordinator(DataUpdateCoordinator)` placed before `FeellooActivityCoordinator` — stores `entry`/`auth`, resolves `polling_interval_minutes` from `get_secondary_polling_intervals(entry)[key]`, passes `update_interval=timedelta(minutes=…)` to `super().__init__`, and implements `async_apply_polling_interval` per the §5 case table (store first; unchanged value → idempotent no-op; changed value → set `update_interval` + one `await self.async_request_refresh()`).
- C3–C7: the five subclasses (`coordinator.py:528/:578/:631/:684/:746`) become thin subclasses passing their key + name; their `_async_update_data` and getters are untouched; constructors keep the `(hass, entry, auth)` signature; docstrings note configurability with the default.
- If the change orphans the timedelta-constant imports in `coordinator.py`, remove the dead imports (document it — 047 deviation-#3 precedent); the constants stay in `const.py`.
**Accept:** with no options, each secondary's `update_interval` equals its original constant (`ACTIVITY_UPDATE_INTERVAL` etc. — harness H2 asserts this against the constants); the main coordinator is byte-identical (grep: `async_apply_polling_settings`, `_sync_fast_polling_timer`, `_ps_override`, `:206` constructor all untouched).

### T3 — `__init__.py`: listener extension
- C9: `_async_update_listener` (:146) — after the existing main apply (:162), resolve `get_secondary_polling_intervals(entry)` and `await data[key].async_apply_polling_interval(resolved[key])` for each of the five keys in fixed order. Tolerate a missing coordinator key defensively (skip with warning) — teardown races.
**Accept:** options-only change → all five intervals applied live, no reload (no "Setting up entry" log); credentials change → entry still reloads; a re-fired listener is harmless (idempotent no-ops).

### T4 — `number.py`: the five entities
- C10: new `FeellooSecondaryPollingIntervalNumber(NumberEntity)` per contract §6.1 — plain entity, CONFIG, hub device, `unique_id = f"{uid}_{option_key}"`, translation key = option key, bounds 1/1440/step 1/"min"/box, icon `mdi:clock-outline`, `native_value` from the resolver, no extra attributes, validation mirroring `FeellooPollingIntervalNumber` (reject non-numeric/non-integer/out-of-bounds), apply-then-persist order, entry-update listener in `async_added_to_hass`.
- `async_setup_entry`: instantiate five in fixed order (activity, activity_week, activity_month, territory, session), fetching each coordinator from `hass.data[DOMAIN][entry.entry_id][key]`; skip-with-warning if missing.
**Accept:** five entities appear on the Feelloo hub device with stable ids; controls usable regardless of coordinator failure state; set-value path applies before persisting (harness H4 order check); existing number entities unchanged.

### T5 — `sensor.py`: the Last Update attribute
- C11: `FeellooLastUpdateSensor.extra_state_attributes` (:954+ class) gains `"secondary_polling_intervals": get_secondary_polling_intervals(self._entry)`; the three existing attributes are unchanged. The existing entry-update listener already re-renders on option changes.
**Accept:** attribute present and follows option changes; no other sensor code touched (no `available` changes anywhere — contract §1/§7).

### T6 — `config_flow.py`: five new fields
- C12: `async_step_init` schema gains five `vol.Optional` fields with defaults from `get_secondary_polling_intervals(self.config_entry)` and `vol.All(vol.Coerce(int), vol.Range(min=POLLING_INTERVAL_MIN, max=POLLING_INTERVAL_MAX))`; `new_options` (:134) merges the five keys via `user_input.get(KEY, current)`; the description key set is updated. The handler stays **no-arg** — no constructor argument (HA ≥ 2026.9 read-only `config_entry`; merged PR #2 must not regress).
**Accept:** 9-field form; polling-only submission performs no Firebase POST and no `entry.data` write; blank-password/email-unchanged path intact; `password_required` and `invalid_auth` paths intact; `create_entry(data=new_options)` (merged options — 047 deviation #1 preserved); invalid intervals impossible via the flow (schema bounds).

### T7 — Translations
`translations/en.json` + `translations/fr.json`: the five `options.step.init.data` labels, the updated `options.step.init.description`, and the five `entity.number.*` names — exact strings from contract §8, full key parity between languages.
**Accept:** options form and all five entity names render in both languages (parity check).

### T8 — Release metadata + docs
- `manifest.json` → `1.9.0` (tag `v1.9.0` at release time; do not tag during implementation).
- README.md **and** README_FR.md per contract §10 checklist: Features bullet; Architecture table secondary rows ("Configurable (default …)"); five settings-table rows; rewrite the "keep their fixed cadence" bullet (README.md :90 / FR :92); the "Secondary polling intervals" subsection (recommended profile, traffic table §9.1 + honesty framing §9.3, restart-anchored-schedule note, session ≤ territory guidance, the no-hiding statement); five Numbers entity-list entries; Last Update sensor attribute mention. Requirements section unchanged.
**Accept:** every §10 item present in BOTH files; the traffic table's arithmetic matches contract §9.1/§9.2 exactly; no claim beyond contract §9.3's honesty clause (no battery/bandwidth/per-request-cost saving claims).

### T9 — Harness extension
- C16: extend `specs/047-polling-control/verification-harness.py` in place with suites H1–H8 (contract §11.1): resolver table per key; defaults preserved (against the timedelta constants); each interval applied + independence; no-restart application (listener + entity write order); options flow (9 fields, all three submit paths); entity surface (unique_ids/categories/bounds/fallback, Last Update attribute); **entity-set equality across four option sets** (the no-sensor-removed proof); 047 regression additions (secondary options never affect the main coordinator or the Petite-Souris override). Update the file docstring to note the 048 extension.
**Accept:** the harness runs green with exit code 0 — all H1–H8 checks AND all 137 pre-existing 047 checks; record the new total.

### T10 — Verification record
Produce `specs/048-secondary-polling-intervals/verification.md` (the contract §12 names it as a deliverable): environment statement, commands + outputs (`py_compile`, JSON parses, harness output with totals), the matrix L1–L11 with statuses (local-evidence rows marked LOCAL PASS, live rows marked PENDING LIVE with the exact observation each needs), the deviations list (if any, with justifications), and the data-safety statement.
**Accept:** all local rows closed with evidence; live rows carry concrete observation instructions; the record delivered to the Reviewer with the code.

## Notes for the Reviewer

Check especially:
- **Main coordinator freeze:** `coordinator.py` main class, `async_apply_polling_settings`, `_sync_fast_polling_timer`, `_ps_*` flags, `:206` constructor line, switch/number/button/main-sensor code — byte-identical to 4f32b05.
- **No sensor hiding anywhere:** no entity removed, no `available` property touched, no registry manipulation, no entity-category games on existing entities (contract §7); H7 entity-set equality green.
- **Defaults:** no options → the five secondary `update_interval`s equal the original constants (H2); config entry `VERSION` still 1; `entry.data` credentials-only.
- **Bounds discipline:** stored out-of-range/invalid values fall back to DEFAULTS (never clamped) in the resolver; the flow schema enforces `Range(1..1440)` at submission; the number entities validate before applying.
- **No-arg options flow handler** (HA 2026.9 read-only `config_entry` — merged PR #2 must not regress).
- **Apply-then-persist order** on the entity write path; options merged, never replaced; listener idempotent.
- **Translations parity** en/fr; unique_id scheme (`entry.unique_id` with `entry_id` fallback); instantiation order fixed.
- **Docs:** both READMEs complete per §10; traffic numbers match §9.1/§9.2; no overstated claims (§9.3).
- **Harness:** all checks green including the 137 047 checks; the 048 verification record states the true totals.