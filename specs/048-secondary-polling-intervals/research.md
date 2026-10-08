# Research 048 — Codebase Findings (ha-feelloo @ 4f32b05)

All findings verified by reading the repository at HEAD `4f32b05` (v1.8.0, tag `v1.8.0`, working tree clean, `main` in sync with `origin/main`). Line numbers refer to this commit.

## 1. Baseline evidence (recorded 2026-10-08)

- `git log -1`: `4f32b05 fix: the polling interval number now shows the effective cadence too`. Tags through `v1.8.0`. `manifest.json` version `1.8.0`. `hacs.json` requires HA ≥ 2024.12.0.
- `python3 specs/047-polling-control/verification-harness.py` → **137/137 checks passed** at this commit (re-run during this research as the regression baseline 048 must not break).
- No `secondary`/interval-related option keys exist yet anywhere in `custom_components/feelloo/` (grep-verified).

## 2. Coordinator architecture at 4f32b05

| Coordinator | Class / line | `update_interval` line | Interval (const.py) |
|-------------|--------------|------------------------|----------------------|
| Main (cats) | `FeellooMainCoordinator` :177 | :206 (resolved from options, 047) | configurable (default 5 min) |
| Activity | `FeellooActivityCoordinator` :528 | :540 | `ACTIVITY_UPDATE_INTERVAL` 15 min |
| Activity week | `FeellooActivityWeekCoordinator` :578 | :590 | `ACTIVITY_WEEK_UPDATE_INTERVAL` 1 h |
| Activity month | `FeellooActivityMonthCoordinator` :631 | :643 | `ACTIVITY_MONTH_UPDATE_INTERVAL` 6 h |
| Territory | `FeellooTerritoryCoordinator` :684 | :696 | `TERRITORY_UPDATE_INTERVAL` 15 min |
| Session | `FeellooSessionCoordinator` :746 | :758 | `SESSION_UPDATE_INTERVAL` 30 min |

Structural facts that shape the design:

- Each secondary constructor is five-lines-identical: stores `self.entry`, `self.auth`, then `super().__init__(hass, _LOGGER, name=f"{DOMAIN}_<key>", update_interval=<CONST>)`. The five `_async_update_data` are already near-duplicates (repo style tolerates duplication across coordinators). 048 adds a **shared base class** (contract C8) for the resolve/apply logic — the one place where copy-paste bugs (e.g. a missing no-op check) would otherwise hide — while leaving the fetch bodies untouched.
- All five secondaries read `hass.data[DOMAIN][entry.entry_id]["main"].cats` during updates (session additionally reads `territory.get_last_session(...)`). They are therefore structurally independent of the main coordinator's *polling state*: with main polling disabled they keep fetching for the last-known cat list (pre-existing 047 behaviour, unchanged). This becomes more relevant with 048: the "quiet profile" (main disabled + slow secondaries) is fully coherent.
- Token refresh (`TOKEN_REFRESH_INTERVAL` 50 min) runs on the main coordinator and always keeps running (~29 Firebase POSTs/day, `1440/50`). It targets `identitytoolkit.googleapis.com`, not the Feelloo API, and is **out of scope per 047 §1** — it is deliberately not counted in the 556 Feelloo-API baseline and 048 does not touch it.
- Startup: `__init__.py` awaits `async_config_entry_first_refresh()` for all five secondaries (:70–83 area) regardless of interval. With a 1440-minute cadence, the startup fetch *is* the day's fetch — a daily cadence is anchored at each HA start. Documented in the READMEs (contract §10): frequent restarts ⇒ more frequent fetches.
- The manual Refresh Data button (button.py) refreshes main, then gathers all five secondaries concurrently — territory and session refresh in parallel, so a session fetch may read territory data from just before territory's concurrent refresh completes. Pre-existing 1.8.0 behaviour; 048 changes nothing about it (recorded here because the recommended profile sets both to the same cadence; on-demand coherence is available via the button's sequential behavior only for main).

## 3. The 047 mechanism inventory 048 reuses (all verified at 4f32b05)

- `const.py`: `CONF_POLLING_ENABLED` :20, `CONF_POLLING_INTERVAL` :21, `POLLING_INTERVAL_MIN = 1` :25, `POLLING_INTERVAL_MAX = 1440` :26, `get_polling_settings` :55 — the defensive resolver whose semantics 048 mirrors per key (missing / non-bool / non-int / out-of-range → DEFAULT, never the nearest bound; `int()`-coercible strings accepted; floats truncate through `int()`, e.g. `15.9 → 15`).
- `__init__.py`: update listener registered :65; `_async_update_listener` :146 — credentials change → entry reload; options-only change → `await data["main"].async_apply_polling_settings(*get_polling_settings(entry))` :162. 048 extends exactly this function (contract C9); the listener's options-only path never reloads → no entity blip.
- `coordinator.py`: `async_apply_polling_settings` (:243 area) — the case table 048's `async_apply_polling_interval` mirrors: interval change while enabled → set `update_interval` + one debounced `async_request_refresh()` (flushes the pending old-cadence timer); unchanged value → idempotent no-op.
- `config_flow.py`: `async_get_options_flow` :110 returns a **no-arg** `FeellooOptionsFlowHandler()` (the HA-2026.9 read-only `config_entry` fix, merged PR #2 / commits `51c209e`+`84dc85b`); `async_step_init` :120; `new_options` merge :134; `async_create_entry(title=new_email, data=new_options)` :157/:164 (047 deviation #1: HA persists the create_entry `data` **as** `entry.options` — source-verified in 047 verification.md §3.6; an empty dict would wipe the options).
- `number.py`: `FeellooPollingIntervalNumber` :115 — plain `NumberEntity` (NOT `CoordinatorEntity`), `EntityCategory.CONFIG`, hub device, `unique_id = f"{uid}_polling_interval"`, box mode, 1–1440 min, apply-then-persist order, per-entity `entry.add_update_listener` re-render (047 deviation #2), validation rejecting non-numeric/non-integer/out-of-bounds.
- `sensor.py`: `FeellooLastUpdateSensor` :954 — DIAGNOSTIC, `native_value = coordinator.last_successful_fetch`, attributes `polling_enabled` / `polling_interval_minutes` / `petite_souris_override` (effective state), entry-update listener. 048 adds exactly one attribute (contract C11).
- Translations `en.json` / `fr.json`: `options.step.init` (description + 4 data labels + 2 errors), `entity.number.polling_interval`, `entity.switch.polling_enabled[_override]`, etc. — the structures the five new keys slot into.

## 4. Traffic baseline — measured and corrected arithmetic

Convention: **scheduled refresh cycles per day = 1440 / interval_minutes** (matches the orchestrator's measured baseline). One secondary refresh = one API GET per cat; one main refresh = 1 list GET + N detail GETs (N = cats).

| Coordinator | Default | Refreshes/day | Recommended (§3 of the contract) | Refreshes/day |
|-------------|---------|---------------|----------------------------------|---------------|
| Main (cats) | 5 min | 288 | per 047 (default 5 min = 288; disabled = 0) | 288 / 0 |
| Activity (day) | 15 min | 96 | 15 (default kept) | 96 |
| Activity week | 60 min | 24 | 1440 | 1 |
| Activity month | 360 min | 4 | 1440 | 1 |
| Territory | 15 min | 96 | 1440 | 1 |
| Session | 30 min | 48 | 1440 | 1 |
| **Secondary subtotal** | | **268** | | **100** |
| **Total (main default)** | | **556** | | **388** |
| **Total (main disabled)** | | | | **100** |

- Secondary reduction: `(268 − 100) / 268 = 62.7 %`. Total reduction with main at default: `168 / 556 = 30.2 %`; with main disabled: `456 / 556 = 82.0 %`.
- "Quiet profile" (activity also 1440, main disabled): secondary 5/day → total **5/day**, `(556 − 5) / 556 = 99.1 %`.
- **Correction to the briefing (recorded honestly):** the orchestrator's "slowing territory/session/activity_week yields roughly −47 % of the secondary traffic" could not be reproduced under any convention: (95 + 47 + 23)/268 = 61.6 %; adding month (−3) → 62.7 %. The contract's table (§9) uses the corrected figures. Likewise, the briefing's "combining with the main coordinator disabled brings the whole integration to a handful of requests per day" holds **only if the daily-activity coordinator is also slowed**: with the owner's-goal profile and main disabled the total is 100/day (activity still contributes 96), not single digits. The spec states this plainly — the "handful" belongs to the quiet profile (contract §9.3, honesty clause).
- Token refresh: `1440/50 ≈ 29` Firebase POSTs/day regardless of any setting — auth housekeeping, separate endpoint, not in the 556, unchanged (047 §1 precedent).

## 5. The contributor's fork (briefing input — not part of this repo)

Reifircax's fork (commit `e77bb3d`) implemented per-coordinator enable/disable flags plus hiding the associated sensors. The fork itself is not present in this repository — only their merged HA-2026.9 options-flow fix (PR #2) is. **No code from the fork is to be merged**; the owner reviewed the approach and rejected it (rejection rationale recorded as a binding rule: contract §7). Reifircax's PR #2 contribution remains credited and preserved.

## 6. Home Assistant behaviour facts (reused from 047's source verification — HA 2026.9.0 / 2026.10.0 / dev)

1. `DataUpdateCoordinator.update_interval` is a plain settable property; the setter does not reschedule (047 verification §3.1). Runtime assignment is valid.
2. A refresh already scheduled before an interval change may fire at most once at the OLD cadence, then the next timer arms at the current interval. `async_request_refresh` (debounced ~10 s, `REQUEST_REFRESH_DEFAULT_COOLDOWN`) cancels the pending timer inside `_async_refresh` and re-arms at the new cadence — the flush 047 uses on interval changes and 048 mirrors (contract §5).
3. `async_config_entry_first_refresh()` runs regardless of `update_interval` — startup fetches are unaffected by slow cadences.
4. With an update listener registered, options/data updates call the listener instead of an automatic reload; `async_update_entry` has change detection, so idempotent re-applies are harmless no-ops (047 verification §3.7). Options-only changes never reload → no entity blip.
5. Options flow: `async_create_entry(data=X)` persists X **as** `entry.options`; the base `OptionsFlow` exposes a read-only `config_entry` property resolving from `hass.config_entries` (2024.12+; read-only since 2026.9). The 048 flow work must not reintroduce a constructor argument (contract C12, hard rule).

## 7. Decisions and rationale (Architect)

1. **Reuse `POLLING_INTERVAL_MIN/MAX` (1–1440) for all five.** The briefing called them "MIN/MAX_UPDATE_INTERVAL_MINUTES"; the actual names are `POLLING_INTERVAL_MIN/MAX` (`const.py` :25–26) — reused unrenamed (renaming touches 047 code paths for zero benefit). 1440 covers the owner's "once a day" exactly. Allowing >1440 for the month coordinator (e.g. one fetch every several days) would save ≤ 0.67 requests/day (1/day → 1/3-day) — no observable benefit in exchange for a divergent per-key bound surface (resolver branches, per-entity maxes, per-field flow ranges). The Refresh Data button already provides arbitrarily fresh data on demand, and HA restarts re-anchor long cadences anyway (fact §2/§3). One shared range = one mental model, one validation path (contract §2.4).
2. **Defaults are the current constants; the resolver falls back to defaults, never to bounds.** Identical philosophy to 047 §2.2. The harness asserts the defaults structurally: `timedelta(minutes=DEFAULT_*) == ACTIVITY_UPDATE_INTERVAL` etc., so "defaults preserve today's behaviour exactly" is enforced against the very constants 1.8.0 shipped.
3. **Resolver returns a dict keyed by coordinator name** — `get_secondary_polling_intervals(entry) -> dict[str, int]` with keys `activity`, `activity_week`, `activity_month`, `territory`, `session` (matching the `hass.data` keys and coordinator names). Five settings make a tuple unwieldy; the keying enables the listener loop (C9) and the data-driven entity instantiation (C10) with zero per-key branching.
4. **Shared base class `FeellooSecondaryCoordinator`** instead of 5× duplicated resolve/apply code: one place for the apply semantics; additive change (one new class); subclass constructors keep the `(hass, entry, auth)` signature — call sites in `__init__.py` unchanged; the five `_async_update_data` bodies untouched. If the change orphans the now-unused timedelta-constant imports in `coordinator.py`, removing the dead imports follows the 047 precedent (047 deviation #3: documented, non-breaking); the constants stay in `const.py`.
5. **Entity surface: mirror 047 — five CONFIG numbers + options-flow fields (not options-flow-only).** 047 established the dual surface: settings are automatable from HA *and* editable in the flow. Making secondaries options-flow-only would leave main polling automatable but secondary polling not — an inconsistency nobody asked for. The traffic-tuning use case is exactly an automation target (speed territory up while watching the map, slow everything at night). Cost: five CONFIG-category numbers (off the main dashboard by category, no per-cat multiplication, no new platform). The implementation reuses the 047 number code path nearly verbatim → lowest implementation and review risk. No switches (the owner rejected disabling), no buttons (Refresh Data already refreshes all six coordinators), no services (contract §6.2).
6. **Key naming: `polling_interval_{activity|activity_week|activity_month|territory|session}`** — option key == translation key == unique_id suffix. Groups the whole polling family under one prefix in `entry.options`; zero collision with existing keys (grep-verified).
7. **No sensor hiding — binding prohibition.** Full rationale in contract §7: it would destroy the last-known-value guarantee 047 established, break automations/dashboards/history referencing the entity_ids, make staleness invisible (the opposite of the requirement), and add machinery where intervals alone achieve the goal. The harness's entity-set-equality suite (H7) is the executable refutation.
8. **Staleness visibility = existing surfaces only.** The Last Update sensor gains `secondary_polling_intervals` (the resolved dict; secondaries have no override concept, so saved == effective). Each entity's last-updated timestamp (HA built-in) shows its data age. No per-coordinator Last-Update sensors (out of scope; a possible future spec if the owner wants them).
9. **Recommended profile includes session = 1440 as a companion** to territory = 1440: the session coordinator fetches the detail of the latest *known* session, and that target only changes when territory refreshes — a 30-minute session cadence over a 1-day territory cadence would re-pull an identical payload ~48×/day. Guidance only: keep session ≤ territory for coherence; nothing enforces it (contract §3).
10. **Battery honesty.** The integration's read rate does not command the tag's reporting cadence — the tag→gateway→cloud chain is autonomous, and Petite Souris (which does change tag behaviour, server-side) is untouched by this spec. The spec and READMEs therefore state the battery concern as the *owner's motivation*, not as a claimed mechanical saving; the verifiable claim is the request count itself (contract §9.3).
11. **Doc anchors to update:** README.md :55–59 (architecture table rows), :83 (settings table), :90 ("All other coordinators keep their fixed cadence" — becomes false, rewritten), :207–209 (Numbers entity list), plus a Features bullet. README_FR.md :57, :85, :92, :209–211 mirrored. Both mandatory (contract §10).
12. **047 §1's frozen-cadence clause is superseded, with approval.** 047's contract froze the five secondary `update_interval` lines ("as-is" at 376/426/479/532/594 @ 59e0361; recorded verbatim at 443/493/546/599/661 in 1.8.0; now 540/590/643/696/758 after 047's additive edits). This spec IS the orchestrator approval that supersedes it. The 047 *harness* contains no check on those lines (the reviewer's verbatim-grep was a release-time check recorded in 047 verification.md §5), so the 137 existing checks stay valid through the 048 change — they remain the regression gate, extended in place (contract §11).

## 8. Open questions — resolved

- Entities vs options-flow-only: **both, mirroring 047** (§7.5).
- \>1440 minutes for the month coordinator: **rejected** (§7.1).
- Clamp to bound or fall back to default: **default, never the bound** (§7.2).
- Session recommendation: **1440 in the recommended profile; guidance session ≤ territory** (§7.9).
- One harness or a new file: **extend the 047 harness in place** — it is the repo's single harness and the task names it; the 048 verification record states the new total and the file's docstring notes the extension. Keeps one regression surface: the 047 checks keep running on every future change.
- Daily-cadence restart anchoring: **documented in the READMEs** (a 1440-min cadence is anchored at each HA start; frequent restarts mean more frequent fetches).
- Multi-cat accounting: **documented as a multiplier** (contract §9.1); the refresh-cycle convention matches the orchestrator's measured baseline.