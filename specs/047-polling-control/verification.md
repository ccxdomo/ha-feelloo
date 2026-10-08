# Verification Record 047 — Polling Control

**Release:** 1.8.0 (base `84dc85b` = merged `59e0361` + HA 2026.9 options-flow fix, contract pinned to `59e0361`)
**Coder session:** 2026-10-08 (updated same day with the owner-approved §4.2 addition)
**Contract reference:** `specs/047-polling-control/contracts/polling-control.md` §10 (matrix V1–V19), §4.2 (Petite Souris interplay), §5.2 (straggler), §7.3 (HA-behavior note)
**Owner addition (2026-10-08, approved):** the Petite Souris mode now temporarily overrides polling to 1 minute while active; implemented and verified in this same session (see §4.2 rows V15–V19 and the amended V10).
**Owner follow-up 2 (2026-10-08, after live testing — option (b)):** the override is now VISIBLE on the polling switch (matrix V20): effective state as the switch state, override icon, saved/effective attributes, and the "(Petite Souris)" name variant via the supported entity-registry `translation_key` update. Command semantics unchanged.

## 1. Environment statement (explicit)

- The repository has **no test infrastructure**: no `tests/`, no pytest config, no requirements files (verified). No test framework was created (contract §1: out of scope).
- No Home Assistant installation exists on the development host (Raspberry Pi, Python 3.13.5; `import homeassistant` fails, no pip). The owner's live HA (≥ 2026.9 per the merged options-flow fix) is the only environment where the live-log rows can be observed.
- Two verification methods were used instead, both recorded below:
  1. **HA core source verification** — fetched the actual `homeassistant/helpers/update_coordinator.py` (tags `2026.9.0`, `2026.10.0`, and `dev`) and `homeassistant/config_entries.py` (`dev`) from home-assistant/core on GitHub and verified every HA-behavior assumption the implementation relies on.
  2. **Local logic harness** — `specs/047-polling-control/verification-harness.py`: a standalone script that stubs `homeassistant`/`aiohttp`/`voluptuous` with faithful miniatures of the verified 2026.9 semantics, imports all 8 touched modules, and runs 129 assertions over the contract's mechanisms. Not a test framework: no pytest, no CI wiring, lives only in the spec directory as evidence.

## 2. Commands and outputs (local verification)

```
$ python3 -m py_compile custom_components/feelloo/const.py \
    custom_components/feelloo/coordinator.py custom_components/feelloo/__init__.py \
    custom_components/feelloo/config_flow.py custom_components/feelloo/switch.py \
    custom_components/feelloo/number.py custom_components/feelloo/button.py \
    custom_components/feelloo/sensor.py
PY_COMPILE OK

$ python3 -c "import json; [json.load(open(f)) for f in [en.json, fr.json, manifest.json]]"
JSON OK: translations/en.json / translations/fr.json / manifest.json  (manifest version = 1.8.0)

$ python3 specs/047-polling-control/verification-harness.py
=== 129/129 checks passed ===
```

The harness covers, with PASS lines for each: resolver table (17 cases incl. defaults == `(True, 5) == CATS_UPDATE_INTERVAL`), C1 constructor resolution (defaults/disabled/interval), C2 first refresh with polling disabled, C4 `last_successful_fetch` (set on success only, frozen on failure), C5 case table (forced refresh on enable/interval-change, none on disable, idempotent no-op, stored-while-disabled), §5.2 straggler (one pending fire then nothing re-armed), C6 token timer keeps running while disabled, C9 listener (options → live apply, credentials → reload, teardown silent), §6 button (main first + 5 secondaries, `HomeAssistantError` on main failure, partial-failure warning, missing-data error), §7.2 entities (apply-then-persist order verified, validation rejects 0/1441/2.5/0.5/-1, options merge, state-sync on entry update), §8.2 surface (unique_ids from `entry.unique_id` with `entry_id` fallback, CONFIG/CONFIG/DIAGNOSTIC categories, number bounds/step/unit/mode, hub device info), §9 last-known-value structure (no refresh → `last_update_success` stays true → available; genuine failure still flips it; data retained; recovery works), C12 options flow (schema fields + defaults + bounds; polling-only no-validation no-data-change; `password_required`; credentials validated; `invalid_auth`; `create_entry` data = merged options), and — for the §4.2 owner addition — the Petite Souris polling override (V15–V19 below: engage on activation/restart reconstruction, restore on expiry, manual-wins latch with off/on re-engage, side-timer suppression during the override, live re-resolution of a preference changed mid-mode, idempotent multi-cat engagement, sensor attribute surface, switch event path), and — for owner follow-up 2 — the override VISIBILITY suite (V20: effective-state `is_on`, override icon, saved/effective attributes, registry `translation_key` swap + restore, en/fr label parity, number's saved-preference + effective-interval attributes, OFF-during-override visibly not a no-op, full return to normal after restore).

**Harness history (Reviewer follow-up, 2026-10-08):** the first-pass harness ran 95 checks and passed 95/95 against the pre-§4.2 code; after the §4.2 code changes landed, that harness version still carried 5 stale expectations (old fast-polling-gate checks asserting the superseded mechanism, plus a 2-key attributes assertion) and produced 90/95 when the Reviewer re-ran it — stale expectations, not product bugs. It was rewritten in the same session to assert the §4.2 semantics (the stale checks replaced by 26 new ones). The harness in the tree now runs 129 checks (95 first pass; 113 after the §4.2 owner addition; 129 after owner follow-up 2 added the V20 visibility suite); the count quoted above is its true, current output (re-verified during this follow-up: 129/129, exit 0). No artifact in this spec set states a count the current harness does not produce.

## 3. HA source verification (§5.2 and §7.3 — findings)

Verified directly in `homeassistant/helpers/update_coordinator.py` (tags 2026.9.0 and 2026.10.0; identical in current `dev`):

1. **`update_interval` is a settable property** whose setter only stores the value (no rescheduling side effect) — `self.update_interval = …` in `async_apply_polling_settings` is valid at runtime.
2. **`_schedule_refresh` returns immediately when the interval is None** (`if self._update_interval_seconds is None: return`). Setting the interval to `None` therefore stops periodic polling.
3. **Straggler bound (§5.2): confirmed.** `_async_refresh` ends with `_schedule_refresh()` (in its `finally`, guarded by listeners), which re-reads the current interval. A refresh already scheduled before the disable fires **at most once**, after which nothing further is armed. Disabling mid-flight does not cancel the pending timer (the property setter touches nothing) — exactly the accepted edge. The harness reproduces this: one pending fire → exactly one refresh → no re-arm. **The sanctioned fallback (forced refresh on disable) was NOT needed.**
4. **`async_request_refresh` never raises** — failures are caught inside `_async_refresh` and flip `last_update_success`. This is why the refresh button checks `last_update_success` after awaiting and raises `HomeAssistantError` itself (contract §6 "wrapped so a failure raises").
5. **Debouncer cooldown is 10 s** (`REQUEST_REFRESH_DEFAULT_COOLDOWN = 10`) — matches the "~10 s" documented in README/contract.

Verified in `homeassistant/config_entries.py` (current `dev`, `OptionsFlowManager.async_finish_flow`):

6. **`async_create_entry(data=X)` in an options flow persists X as `entry.options`** (`async_update_entry(entry, options=result["data"])` whenever `result["data"] is not None`). A literal `create_entry(title=…, data={})` (contract §7.1 step 5) would **wipe the polling options** written a line earlier and re-trigger the listener with defaults — a self-defeating sequence. **Implemented deviation (documented, requires orchestrator sign-off):** `async_create_entry(title=email, data=new_options)` passes the merged options instead of `{}`. Net effect is identical to the contract's intent (options persisted, listener applies them, `async_update_entry` change-detection makes the second write a no-op); the only alternative reading (empty data = keep options) is contradicted by the source.
7. **`async_update_entry` fires update listeners only when something actually changed** (returns bool). This makes the double write in the options flow benign: exactly one listener fire per submission in each path.

**V14 note (which semantics the running HA exhibits):** with an update listener registered, options/data updates call the listener (`async_update_listeners`), not an automatic reload — this is the primary path implemented. If the running version also scheduled a reload, the outcome would still be correct (startup re-reads options) per contract §7.3. Live log observation (V3/V5: absence of "Setting up entry" blips) remains the owner-side confirmation.

## 4. Matrix V1–V20

Local-evidence rows are structural/logic verifications (harness + source). Rows marked **PENDING LIVE** need the owner's live HA + real account per contract §10; each lists exactly what to observe so the live run can close the row.

| # | Case | Status | Evidence / what to observe live |
|---|------|--------|-------------------------------|
| V1 | Default upgrade path | **LOCAL PASS** — PENDING LIVE (15-min log watch) | Resolver: no options → `(True, 5)`; constructor default `update_interval == CATS_UPDATE_INTERVAL` (harness); no migration code exists anywhere in the diff. Live: confirm 5-minute `Finished fetching feelloo_main` cadence, 4 new entities + hub device present, no reload blips. |
| V2 | Disable via options flow | **LOCAL PASS** — PENDING LIVE (log watch) | C5 disable: `update_interval=None`, no forced refresh; straggler: at most one pending fetch then zero periodic (harness §5.2 reproduction); polling-only flow performs no Firebase call and no `entry.data` write (harness C12). Live: options → off, blank password; then zero periodic main fetches after ≤1 straggler; diagnostic timestamp frozen; binary sensors + tracker stay available. |
| V3 | Disable via config switch | **LOCAL PASS** — PENDING LIVE | Switch: apply-first-then-persist verified in order (`['apply', 'update']`); listener applies without reload (harness C9). Live: instant state feedback; watch for absence of entry reload in logs. |
| V4 | Re-enable via switch | **LOCAL PASS** — PENDING LIVE | Enable case: one debounced forced refresh + cadence re-armed at configured interval (harness C5). Live: main fetch within ~10 s, then cadence resumes. |
| V5 | Change interval live | **LOCAL PASS** — PENDING LIVE | Interval-change-while-enabled: `update_interval` updated, one forced refresh, new cadence armed (harness). Live: 5→10 → fetch within ~10 s then 10-minute cadence, no restart/reload. |
| V6 | Interval via options flow | **LOCAL PASS** — PENDING LIVE | Polling-only submission persists options (no password, no validation, no data change) and the listener applies them (harness C12+C9). Live: options → 10, blank password → applied on completion. |
| V7 | Manual button (polling on) | **LOCAL PASS** — PENDING LIVE | Button press refreshes main then all five others (harness §6). Live: six `Finished fetching feelloo_*` lines; diagnostic timestamp updates. |
| V8 | Manual button (polling off) | **LOCAL PASS** — PENDING LIVE | Harness: press with polling disabled → main + 5 fetches, `update_interval` still `None`, no timer re-armed afterwards. Live: same observation. |
| V9 | Petite souris + polling on | **LOCAL PASS** — PENDING LIVE | Fast timer starts when polling enabled + petite souris programmed (harness C3, existing behavior preserved — gate code only runs when disabled). Live: 1-minute cadence. |
| V10 | Petite souris + polling OFF (**amended by §4.2**) | **LOCAL PASS** — PENDING LIVE | Harness: with polling disabled and petite souris programmed, the override engages (main interval 1 min, polling runs, `entry.options` untouched, info log, NO side timer — the main cadence does the fast polling). The original 1.8.0 suppression survives only post-manual-control (see V17). Live: switch reflects server state, info log present, 1-minute fetch cadence in logs, options flow still shows polling disabled, button still fetches. |
| V11 | Restart with polling disabled | **LOCAL PASS** — PENDING LIVE | Harness: `async_setup` runs the first refresh with polling disabled (data populated), then no pending periodic timer is armed; options are read from `entry.options` at construction. Live: restart → startup fetch, then zero periodic fetches; options persisted. |
| V12 | Genuine failure path | **LOCAL PASS** — PENDING LIVE (reversible WAN cut) | Harness: scripted fetch failure flips `last_update_success`, coordinator-gated entity (`FeellooLastUpdateSensor.available`) goes unavailable, `coordinator.data` retained (last known value), `last_successful_fetch` frozen, recovery restores. Button raises `HomeAssistantError`. Live: WAN cut ~30 s + button → binary sensors/tracker unavailable, main sensors keep values; restore → recover. |
| V13 | Credentials flow still works | **LOCAL PASS** — PENDING LIVE | Harness C12: email+password → Firebase POST validation, `entry.data` updated, polling options merged; listener path reloads on credentials change (C9). Live: options → new email + password → validated, entry reloads, coordinators rebuilt. |
| V14 | HA behavior note | **SOURCE-VERIFIED** — PENDING LIVE | See §3 items 6–7 above. Live: during V3/V5 record whether an entry reload occurred (expected: none — listener applies live). |
| V15 | Petite souris ON with polling disabled (§4.2) | **LOCAL PASS** — PENDING LIVE | Harness: override engages (1-min interval, no side timer, options untouched, info log); startup path == restart reconstruction. Live: info log + 1-minute fetch cadence; sensor `petite_souris_override=true`. |
| V16 | Petite souris OFF restores state (§4.2) | **LOCAL PASS** — PENDING LIVE | Harness: mode end → preference restored (disabled again / user interval), info log, options unchanged. Live: same + zero periodic fetches after restore-to-disabled. |
| V17 | Manual change during mode (§4.2 edge 1) | **LOCAL PASS** — PENDING LIVE | Harness: manual disable cancels the override (log), latch holds across subsequent fetches, off/on re-engages; manual interval change cancels + applies + legacy side timer resumes 1-min tracking. Live: switch/number/options-flow changes behave the same. |
| V18 | Mode expiry with polling disabled (§4.2 edge 4) | **LOCAL PASS** — PENDING LIVE | Harness: expiry == fetch-detected mode end → identical restoration (the override keeps 1-min fetches so expiry is seen within ~1 min). Live: program a short duration and observe the restoration log at expiry. |
| V19 | Restart while petite souris active (§4.2 edge 5) | **LOCAL PASS** — PENDING LIVE | Harness: fresh coordinator + programmed cat → startup first refresh → override re-engages; options untouched; end → restored disabled. Live: restart HA with the mode active and the disabled preference; confirm re-engagement log then restoration at mode end. |
| V20 | Override visibility on the polling switch (owner follow-up 2) | **LOCAL PASS** — PENDING LIVE | Harness: the owner's exact scenario (preference disabled + mode active) — switch reads ON (effective), icon `mdi:clock-fast`, attributes expose saved (False/5) + effective (True/1), registry label swapped to `polling_enabled_override`, label present in en + fr; OFF during the override cancels the boost and visibly flips the switch to OFF (not a no-op); after restore (re-engage then mode end via fetch) the switch, icon, attributes and registry label all return to normal. Live: confirm the UI shows ON + "(Petite Souris)" label + fast-clock icon during the boost, and that everything reverts at mode end. |

## 5. Reviewer checklist results (contract §10)

- Translations render in en and fr: all 8 exact strings from contract §8.3 present in both files (verified programmatically); both files parse as JSON.
- Unique IDs stable across HA restart: `entry.unique_id` (casefolded email, set by the config flow) with `entry.entry_id` fallback; registry state survives restarts by design. No random components.
- Hub device shows all 4 entities: hub device registered unconditionally in `_async_setup_devices` (identifiers `(DOMAIN, entry.entry_id)`, model "Account"); all four entities declare `device_info` with those identifiers (harness C11 + §8.2 checks).
- Five secondary coordinators untouched: `update_interval=ACTIVITY/ACTIVITY_WEEK/ACTIVITY_MONTH/TERRITORY/SESSION_UPDATE_INTERVAL` all still present verbatim (grep, now at lines 443/493/546/599/661 after the additive edits — content unchanged).
- No availability-masking code added: `grep` for `available` shows no new overrides on data entities; the only availability code added is nothing — the last-update sensor keeps the default `CoordinatorEntity.available` (contract §8.2 requirement) and the harness confirms a genuine failure still makes it unavailable.
- Disable never raises: `async_apply_polling_settings(False, …)` path verified no-raise; entities never clear data.
- `entry.data` shape unchanged: credentials-only; the only writer remains the options flow credentials path.
- §4.2 addition: `entry.options` is NEVER written by the override (harness asserts options equality through engage/restore); override transitions perform no forced refresh; the manual-wins latch prevents re-engagement while the mode stays active and resets at mode end; the sensor exposes `petite_souris_override`.

## 6. Known pre-existing edge observed while testing (out of scope, unchanged)

The 1.7.5 API-state auto-sync in `_async_update_data` only adds/discards cats **present in the response**: a cat removed from the account while in `_fast_polling_active` stays in the set (keeping the override/side timer alive) until a restart or another state change rebuilds it. This is pre-existing behavior, explicitly left untouched per the contract ("no other polling-related code may be touched"), and self-heals on restart. Recorded here because it surfaced while writing the V15–V19 harness tests.

## 7. Deviations from the contract (requiring orchestrator awareness)

1. **Options flow `create_entry` data (contract §7.1 step 5)** — contract says `async_create_entry(title=email, data={})`; implemented as `data=new_options` (the merged options). Rationale: HA persists the create_entry data as `entry.options` (source-verified, §3 item 6); the literal `{}` would wipe the settings and re-apply defaults via the listener. The implemented form achieves the contract's stated intent ("applied on flow completion") and is a no-op-safe double write because `async_update_entry` has change detection.
2. **Per-entity entry-update listeners** (additive, not in the contract): the polling switch, interval number, and last-update sensor register `entry.add_update_listener` in `async_added_to_hass` (removed via `async_on_remove`) and re-write their state when options change through another surface (options flow, REST API). Without this, a V6 change would apply correctly but the config entities would display stale values until restart. All mechanisms used exist in HA 2024.1; entities remain plain (not `CoordinatorEntity`); `is_on`/`native_value` still read the persisted options per contract §7.2. Verified harmless: listener writes are idempotent state writes.
3. **Unused `CATS_UPDATE_INTERVAL` import removed from coordinator.py** — the constant itself remains in const.py; only the now-dead import in coordinator.py was dropped (my C1 change made it unused). Non-breaking.

## 8. Data safety statement

No destructive or irreversible operation was performed or introduced. Local verification used only: file reads, `py_compile`, JSON parsing, pure-Python logic tests with stubbed dependencies (no network calls to Feelloo/Firebase from the harness — credential validation was stubbed), and public read-only fetches of HA core source from GitHub (update_coordinator.py 2026.9/2026.10/dev; config_entries.py 2024.1.0, 2024.6.0, 2024.9.0, 2024.11.0, 2024.12.0, 2025.1.0, 2025.7.0, 2026.1.0, 2026.8.0, 2026.9.0, dev). No credentials were read, logged, or modified; `entry.data` remains credentials-only. V12's live variant (temporary WAN cut) is left to the owner as a fully reversible step per contract §10.

## 9. HACS minimum version (Reviewer follow-up, 2026-10-08)

`hacs.json` declared `homeassistant: 2024.1.0`. Source-verified finding: the delivered options flow — which since merged commit `84dc85b` instantiates `FeellooOptionsFlowHandler()` with no argument and relies on the base `OptionsFlow` resolving `config_entry` — is **broken on 2024.1–2024.11 and works from 2024.12.0**:

- **2024.1.0 → 2024.11.0** (config_entries.py fetched for 2024.1.0, 2024.6.0, 2024.9.0, 2024.11.0): the base `OptionsFlow` defines no `config_entry` attribute or property — the only definition lives on the `OptionsFlowWithConfigEntry` compat class (set via `__init__`) — and `OptionsFlowManager.async_create_flow` never assigns `config_entry` to the handler. A no-arg handler raises `AttributeError` in `async_step_init`.
- **2024.12.0**: the base `OptionsFlow` gains the `config_entry` property resolving via `hass.config_entries.async_get_known_entry(self._config_entry_id)` where `_config_entry_id == self.handler == entry_id`; both supporting methods exist in this release. The no-arg handler works from here.
- **2025.1.0**: same property plus a deprecated manual setter (`breaks_in_ha_version="2025.12"`); our handler never uses the setter, so no deprecation noise on any version.
- **2026.9.0 / dev**: setter removed (read-only property, same resolution) — the merged fix's target version.

Everything else in the 047 implementation uses APIs that predate 2024.1: `entry.add_update_listener`/`async_on_unload`, `async_update_entry`, `DataUpdateCoordinator` `update_interval` assignment and debounced `async_request_refresh`, `EntityCategory`, `NumberEntity` native API, `ButtonEntity`, `CoordinatorEntity`, `async_track_time_interval`, device registry `async_get_or_create`. **Verdict: pin raised `hacs.json` → `"homeassistant": "2024.12.0"`** (README Requirements updated to match). The single constraint is the merged options-flow fix, which the 047 contract requires to be preserved; no 047 mechanism requires anything newer.