# Contract 048 — Secondary Polling Intervals (BINDING)

**Repo:** `ha-feelloo` (HACS custom component), branch `main`, pinned at commit `4f32b05` (v1.8.0).
**Target release:** 1.9.0.
**Status:** BINDING for Coder and Reviewer. Any deviation must be justified in writing and approved by the orchestrator before implementation.
**Relationship to 047:** this contract implements the orchestrator-approved successor to 047 §1's frozen-cadence clause for the five secondary coordinators (superseding "the five other coordinators keep their fixed `update_interval`"). Everything 047 shipped is preserved; the 047 contract remains binding wherever not superseded here. The owner rejected the contributor fork's enable/disable + hide-sensors approach (`Reifircax/e77bb3d`, not in this repo, no code to merge); this contract implements his decision: intervals, never disabling, never hiding.

---

## 1. Scope

**In scope**
- Five per-coordinator interval settings (activity, activity_week, activity_month, territory, session) persisted in `entry.options`, applied to each coordinator's `update_interval`, effective without an HA restart.
- One resolver (`get_secondary_polling_intervals`), one shared base class for the five secondary coordinators, one live-apply method per coordinator.
- Five CONFIG number entities on the Feelloo hub device + five options-flow fields.
- One new attribute on the existing Last Update sensor.
- Translations (en + fr), READMEs (both), manifest version, harness extension, verification matrix.

**Out of scope / must NOT change**
- The main coordinator: all 047 mechanisms (constructor :206 resolution, `async_apply_polling_settings`, `_sync_fast_polling_timer`, `_ps_override`/`_ps_override_cancelled`, `PETITE_SOURIS_OVERRIDE_INTERVAL_MINUTES`, the polling switch/number/button, the Last Update sensor's existing attributes).
- The Firebase token refresh timer (50 min — auth housekeeping; ~29 POSTs/day; the 047 §1 precedent).
- Petite Souris semantics (switch, service, fast polling), the ring button, the Refresh Data button, `set_petite_souris`.
- Entity availability rules — **no availability-masking code may be added anywhere** (047 §9 extended to 048).
- **No enable/disable for secondaries. No sensor hiding of ANY kind (see §7). No >1440-minute cadences.** No new HA services, platforms, devices, or sensors. No config entry `VERSION` bump. No `hacs.json` change. No test framework.

## 2. Settings schema and persistence

### 2.1 New constants (`custom_components/feelloo/const.py`, placed with the 047 polling block)

```python
# Secondary polling intervals (Spec 048) — minutes (int), per coordinator.
# Reuse POLLING_INTERVAL_MIN / POLLING_INTERVAL_MAX (047) as the shared bounds.
CONF_POLLING_INTERVAL_ACTIVITY = "polling_interval_activity"
CONF_POLLING_INTERVAL_ACTIVITY_WEEK = "polling_interval_activity_week"
CONF_POLLING_INTERVAL_ACTIVITY_MONTH = "polling_interval_activity_month"
CONF_POLLING_INTERVAL_TERRITORY = "polling_interval_territory"
CONF_POLLING_INTERVAL_SESSION = "polling_interval_session"

DEFAULT_POLLING_INTERVAL_ACTIVITY = 15          # == ACTIVITY_UPDATE_INTERVAL
DEFAULT_POLLING_INTERVAL_ACTIVITY_WEEK = 60     # == ACTIVITY_WEEK_UPDATE_INTERVAL
DEFAULT_POLLING_INTERVAL_ACTIVITY_MONTH = 360   # == ACTIVITY_MONTH_UPDATE_INTERVAL
DEFAULT_POLLING_INTERVAL_TERRITORY = 15         # == TERRITORY_UPDATE_INTERVAL
DEFAULT_POLLING_INTERVAL_SESSION = 30           # == SESSION_UPDATE_INTERVAL

# key = hass.data / coordinator name -> (option key, default minutes)
SECONDARY_POLLING_INTERVALS = {
    "activity":        (CONF_POLLING_INTERVAL_ACTIVITY, DEFAULT_POLLING_INTERVAL_ACTIVITY),
    "activity_week":   (CONF_POLLING_INTERVAL_ACTIVITY_WEEK, DEFAULT_POLLING_INTERVAL_ACTIVITY_WEEK),
    "activity_month":  (CONF_POLLING_INTERVAL_ACTIVITY_MONTH, DEFAULT_POLLING_INTERVAL_ACTIVITY_MONTH),
    "territory":       (CONF_POLLING_INTERVAL_TERRITORY, DEFAULT_POLLING_INTERVAL_TERRITORY),
    "session":         (CONF_POLLING_INTERVAL_SESSION, DEFAULT_POLLING_INTERVAL_SESSION),
}
```

The five `timedelta` constants (`ACTIVITY_UPDATE_INTERVAL` etc.) **remain in const.py** — they document the shipped cadences and serve as the harness cross-check (`timedelta(minutes=DEFAULT_*) == <CONST>`). If the coordinator change orphans their imports in `coordinator.py`, removing the dead imports is the sanctioned cleanup (047 deviation-#3 precedent: documented, non-breaking); the constants themselves stay.

### 2.2 Resolver (`const.py`, next to `get_polling_settings`)

```python
def get_secondary_polling_intervals(entry) -> dict[str, int]:
    """Resolve the five secondary polling intervals (minutes) with defensive defaults."""
```

Semantics (BINDING, per key — the 047 §2.2 mirror):
- key missing → that coordinator's default;
- value not coercible to `int` (TypeError/ValueError, incl. `None`, `"abc"`, `"15.9"`) → **default**;
- value outside `[POLLING_INTERVAL_MIN, POLLING_INTERVAL_MAX]` → **default, never the nearest bound** — a corrupted or partially edited options dict must never produce a surprising cadence; the defaults reproduce 1.8.0 behaviour exactly;
- `int()`-coercible strings accepted (`"30"` → 30); floats truncate through `int()` (`15.9` → 15) — inherited 047 semantics, deliberately not diverged;
- returns the full five-key dict `{"activity": …, "activity_week": …, "activity_month": …, "territory": …, "session": …}`; never raises; tolerates an entry with no `options` attribute.

Placement: `const.py` is constants-only with the `get_polling_settings` exception; the same deliberate exception applies (config_flow must not import coordinator; every consumer already imports const). Do not create a new module. A private `_resolve_int_minutes` helper factoring the coercion is permitted.

### 2.3 Storage

- `entry.options` only (keys per §2.1). Never `entry.data` — it stays credentials-only.
- Existing installs: keys absent → defaults → **behaviour identical to 1.8.0**. No migration code, no config entry `VERSION`/`minor_version` change.

### 2.4 Bounds justification (documented, not re-litigated)

- **Reuse `POLLING_INTERVAL_MIN = 1` / `POLLING_INTERVAL_MAX = 1440` for all five** (actual constant names at const.py :25–26; the briefing's "MIN/MAX_UPDATE_INTERVAL_MINUTES" do not exist — reuse unrenamed). 1440 = "once a day" = the owner's stated goal, exactly.
- **>1440 for the month coordinator rejected:** going from 1/day to 1/every-3-days saves 0.67 requests/day — no observable benefit in exchange for a divergent per-key bound surface (resolver branches, per-entity maxes, per-field flow ranges). The Refresh Data button already provides arbitrarily fresh data on demand, and HA restarts re-anchor long cadences anyway (startup first refresh). One shared range = one mental model, one validation path.
- **min 1:** mirrors 047 (Petite Souris already runs 1-minute polling locally; nothing lower is justified).

## 3. Recommended settings (documented in the READMEs; NOT enforced in code)

| Coordinator | Recommended | Rationale |
|-------------|-------------|-----------|
| activity | 15 (default kept) | today's rest/calm/action percentages are the only secondary group that changes meaningfully hour-by-hour; not part of the owner's quote |
| activity_week | 1440 | owner's stated goal ("weekly activity once a day") |
| activity_month | 1440 | owner's stated goal ("monthly activity once a day") |
| territory | 1440 | owner's stated goal ("the territory likewise") |
| session | 1440 | companion: its fetch target (the latest *known* session) only changes when territory refreshes; a 30-min session cadence over a 1-day territory cadence would re-pull an identical payload ~48×/day |

Guidance only: keep session ≤ territory for coherence. Nothing enforces it; the settings are independent.

## 4. Control points (exact, pinned to `4f32b05`)

| # | File:line | What exists there | What changes |
|---|-----------|--------------------|--------------|
| C1 | `const.py:25-26` | `POLLING_INTERVAL_MIN/MAX` | **Unchanged** — reused as the shared bounds |
| C2 | `const.py` (047 polling block, after :27) | — | New keys/defaults/`SECONDARY_POLLING_INTERVALS` (§2.1) + resolver (§2.2) |
| C3 | `coordinator.py:528/:540` | `FeellooActivityCoordinator.__init__`, `update_interval=ACTIVITY_UPDATE_INTERVAL` | Subclass of the new base (C8); resolves via options; docstring notes configurability (default 15 min) |
| C4 | `coordinator.py:578/:590` | `FeellooActivityWeekCoordinator` | Same, key `activity_week` (default 60 min) |
| C5 | `coordinator.py:631/:643` | `FeellooActivityMonthCoordinator` | Same, key `activity_month` (default 360 min) |
| C6 | `coordinator.py:684/:696` | `FeellooTerritoryCoordinator` | Same, key `territory` (default 15 min) |
| C7 | `coordinator.py:746/:758` | `FeellooSessionCoordinator` | Same, key `session` (default 30 min) |
| C8 | `coordinator.py` (new class, before :528) | — | `FeellooSecondaryCoordinator(DataUpdateCoordinator)`: stores `entry`/`auth`; `polling_interval_minutes = get_secondary_polling_intervals(entry)[key]`; `super().__init__(hass, _LOGGER, name=…, update_interval=timedelta(minutes=…))`; `async_apply_polling_interval(interval_minutes)` per §5 |
| C9 | `__init__.py:146-162` | `_async_update_listener` applies the main settings only | After the main apply, loop `SECONDARY_POLLING_INTERVALS` in fixed order and `await data[key].async_apply_polling_interval(resolved[key])` (idempotent) |
| C10 | `number.py:115+` | `FeellooPollingIntervalNumber` | New `FeellooSecondaryPollingIntervalNumber` per §6; `async_setup_entry` instantiates it 5× in fixed order (activity, activity_week, activity_month, territory, session), defensive skip-with-warning if a coordinator is missing |
| C11 | `sensor.py:954+` (`FeellooLastUpdateSensor.extra_state_attributes`) | 3 attributes | Gains `"secondary_polling_intervals": get_secondary_polling_intervals(self._entry)`; existing attributes unchanged |
| C12 | `config_flow.py:120-166` | 4-field schema, merged `new_options`, no-arg handler | 9-field schema; five keys added to `new_options` (§7); handler stays **no-arg** (HA ≥ 2026.9 read-only `config_entry` — hard rule; do not reintroduce the bug fixed by merged PR #2) |
| C13 | `translations/en.json` + `translations/fr.json` | — | §8 exact strings, both languages |
| C14 | `manifest.json` | `"version": "1.8.0"` | `"version": "1.9.0"`; tag `v1.9.0` |
| C15 | `README.md` + `README_FR.md` | — | §10 doc requirements, both files |
| C16 | `specs/047-polling-control/verification-harness.py` | 137 checks (all green at 4f32b05) | Extended in place with the 048 suites (§11.1); the existing 137 checks keep passing |

No other polling-related code may be touched. Frozen in particular: `coordinator.py:206` (main constructor resolution), `async_apply_polling_settings`, `_sync_fast_polling_timer`, the `_ps_*` flags, `PETITE_SOURIS_OVERRIDE_INTERVAL_MINUTES`, the button/switch/main-number code, all `_async_update_data` bodies, and all entity `available` properties.

## 5. Live application: `async_apply_polling_interval` (case table, BINDING)

```python
async def async_apply_polling_interval(self, interval_minutes: int) -> None:
    """Apply this coordinator's interval at runtime (no restart)."""
```

| Case | `update_interval` | Forced refresh? |
|------|-------------------|-----------------|
| value unchanged | unchanged | **No** — idempotent no-op |
| value changed | `timedelta(minutes=interval_minutes)` | **Yes** — `await self.async_request_refresh()` (debounced ~10 s; cancels the pending old-cadence timer inside `_async_refresh` so the new cadence arms immediately) |

- Always store `self.polling_interval_minutes` first (even on the no-op path — harmless).
- Bounded straggler (047 §5.2 precedent): without the forced refresh, at most one already-scheduled fetch at the OLD cadence may fire before the new cadence arms; with the forced refresh the pending timer is cancelled. Either outcome is compliant.
- **Never a reload** for options-only changes: the listener path (C9) applies live; HA restarts re-resolve at construction. No entity blip.
- **No interaction with the Petite-Souris override:** the override touches the main coordinator only. Secondary applies proceed normally during an override; the five settings never read or write the override state.
- Works identically whether the main coordinator's polling is enabled or disabled (secondaries read `main.cats` from `hass.data`, which retains the last-known cat list).

## 6. Entity surface (BINDING)

### 6.1 One class, five instances: `FeellooSecondaryPollingIntervalNumber(NumberEntity)`

Parameterized by `(coordinator, entry, key)` where `key` ∈ the five `SECONDARY_POLLING_INTERVALS` names:
- **plain `NumberEntity`** (NOT `CoordinatorEntity`) — the control must remain usable even when the coordinator's last refresh failed (047 §7.2 rule);
- `_attr_has_entity_name = True`; `_attr_translation_key` = the option key (e.g. `polling_interval_activity`);
- `unique_id = f"{uid}_{option_key}"` with `uid = entry.unique_id or entry.entry_id` (legacy fallback verified by harness);
- `_attr_device_info` = the hub device (`identifiers = {(DOMAIN, entry.entry_id)}`, name "Feelloo", manufacturer "Feelloo", model "Account");
- `_attr_entity_category = EntityCategory.CONFIG`; icon `mdi:clock-outline`; `native_min_value = POLLING_INTERVAL_MIN` (1); `native_max_value = POLLING_INTERVAL_MAX` (1440); `native_step = 1`; `native_unit_of_measurement = "min"`; `_attr_mode = "box"`;
- `native_value` = `get_secondary_polling_intervals(entry)[key]` (saved == effective for secondaries; there is no override concept);
- **no `extra_state_attributes`** (nothing to distinguish; the Last Update sensor carries the dict);
- `async_set_native_value`: validate — numeric, whole, within bounds — mirroring `FeellooPollingIntervalNumber`'s style (`ValueError` otherwise), then **APPLY FIRST** `await coordinator.async_apply_polling_interval(interval)`, then **persist** `options={**entry.options, KEY: interval}` via `hass.config_entries.async_update_entry`, then write state. Persisting fires the listener (C9) which re-applies idempotently (047 §7.2 order discipline);
- `async_added_to_hass` registers `entry.add_update_listener(...)` (removed via `async_on_remove`) so the state follows changes made from other surfaces (047 deviation-#2 pattern).

### 6.2 Why entities AND the options flow (recommendation — binding)

Mirror 047's dual surface; do NOT keep these settings options-flow-only:
1. 047 established that polling settings are **automatable from HA** (dashboards, automations, scripts) *and* editable in the flow. Options-flow-only for secondaries would leave main polling automatable but secondary polling not — an inconsistency nobody asked for, and exactly the "second inconsistent mechanism" the spec forbids.
2. The traffic-tuning use case is an automation target: speed territory up while watching the map, slow everything at night, speed activity up when a cat is being monitored. Impossible options-flow-only.
3. Cost is low: five CONFIG-category numbers (off the main dashboard by category, no per-cat multiplication, no new platform — `NUMBER` is already in `PLATFORMS`).
4. The implementation reuses the 047 number code path nearly verbatim → lowest implementation and review risk, one review checklist.
- **No switches** (the owner rejected disabling; there is nothing to switch), **no buttons** (Refresh Data already refreshes all six coordinators on demand), **no services**.

### 6.3 Instantiation order (binding)

`activity`, `activity_week`, `activity_month`, `territory`, `session` — matching the `hass.data` population order, the button's tuple order, and the listener loop.

## 7. NO SENSOR HIDING (binding prohibition) — rejection of the contributor's approach

The contributor's fork hid each coordinator's sensors when its polling was disabled. **Rejected and prohibited:** Spec 048 must not remove, hide, disable, or mark unavailable ANY existing entity under ANY option combination. Rationale (recorded, binding):

1. **It destroys the last-known-value guarantee 047 established** (047 §9): with polling slowed (never off), no refresh failures occur, so `last_update_success` stays true and every entity naturally retains its value and availability. Hiding throws that away — the owner explicitly wants the data to keep flowing, not blanked out.
2. **It breaks consumers.** Automations, dashboards, templates, and long-term statistics referencing those entity_ids break or gap when entities are removed; re-adding them on re-enable churns the entity registry and history. Cadence changes break nothing.
3. **It makes staleness invisible — the opposite of the requirement.** An absent sensor cannot say "this data is 20 h old". 047's philosophy is that data age is *displayed* (the Last Update sensor, each entity's last-updated timestamp), never concealed. Slowed sensors stay alive with last-known values, and their age is visible by design.
4. **It adds machinery where none is needed.** Registry manipulation and state churn to achieve… fewer requests? Intervals alone achieve the traffic goal with strictly less code and zero state loss.
5. **Enable/disable per coordinator would invent a second control paradigm** (per-coordinator switches) diverging from 047's main-only switch semantics.

Enforcement: harness suite H7 (entity-set equality across option sets — §11.1) plus the Reviewer checklist (no `available` property touched, no entity-registration removal anywhere in the diff).

## 8. Translations (en.json + fr.json, both required — exact strings)

`options.step.init.data`:

| Key | en | fr |
|-----|----|----|
| `polling_interval_activity` | Activity polling interval (minutes) | Intervalle de polling de l'activité (minutes) |
| `polling_interval_activity_week` | Weekly activity polling interval (minutes) | Intervalle de polling de l'activité hebdomadaire (minutes) |
| `polling_interval_activity_month` | Monthly activity polling interval (minutes) | Intervalle de polling de l'activité mensuelle (minutes) |
| `polling_interval_territory` | Territory polling interval (minutes) | Intervalle de polling du territoire (minutes) |
| `polling_interval_session` | Session polling interval (minutes) | Intervalle de polling des sessions (minutes) |

`options.step.init.description` (updated):

| en | fr |
|----|----|
| Update your Feelloo credentials or polling settings (main and secondary coordinators). Leave the password blank to keep your current credentials. | Mettez à jour vos identifiants ou vos paramètres de polling (coordinateur principal et coordinateurs secondaires). Laissez le mot de passe vide pour conserver vos identifiants actuels. |

`entity.number.*` (`.name`):

| Key | en | fr |
|-----|----|----|
| `polling_interval_activity` | Polling Interval — Activity | Intervalle de polling — Activité |
| `polling_interval_activity_week` | Polling Interval — Activity Week | Intervalle de polling — Activité hebdo |
| `polling_interval_activity_month` | Polling Interval — Activity Month | Intervalle de polling — Activité mensuelle |
| `polling_interval_territory` | Polling Interval — Territory | Intervalle de polling — Territoire |
| `polling_interval_session` | Polling Interval — Session | Intervalle de polling — Session |

Follow the repo convention: translations only in `translations/{en,fr}.json` (no `strings.json`). Full key parity between the two files is a Reviewer check.

## 9. Traffic budget (documented in the spec AND both READMEs)

### 9.1 Table (refresh-cycle convention: `1440 / interval_minutes`; one secondary refresh = one API GET per cat; one main refresh = one list GET + one detail GET per cat)

| Coordinator | Setting | Refreshes/day |
|-------------|---------|---------------|
| Main (cats) | 5 min (047 default) | 288 |
| | disabled via 047 | 0 |
| Activity (day) | 15 min (default, recommended) | 96 |
| Activity week | 60 min → **1440** | 24 → **1** |
| Activity month | 360 min → **1440** | 4 → **1** |
| Territory | 15 min → **1440** | 96 → **1** |
| Session | 30 min → **1440** | 48 → **1** |
| **Secondary subtotal** | defaults → recommended | **268 → 100 (−62.7 %)** |
| **Total, main at 5-min default** | defaults → recommended | **556 → 388 (−30.2 %)** |
| **Total, main disabled** | recommended | **100 (−82.0 %)** |
| **"Quiet profile"** (activity also 1440, main disabled) | | **5 (−99.1 %)** |

Multi-cat note: multiply the secondary rows by the number of cats (and the main row by 1 + cats). Token refresh: ~29 Firebase POSTs/day (`1440/50`) continues regardless — auth housekeeping on a separate endpoint, out of scope per 047 §1, **not** counted in the 556.

### 9.2 Arithmetic (explicit)

`268 = 96 + 24 + 4 + 96 + 48`; recommended secondary `= 96 + 1 + 1 + 1 + 1 = 100`; reduction `= 168/268 = 62.7 %`; totals `556 − 168 = 388` (main default), `100` (main disabled), `5` (quiet). The briefing's "−47 %" could not be reproduced under any convention (the correct figure for slowing territory+session+week alone is 61.6 %; with month, 62.7 %) — corrected here and in research.md §4.

### 9.3 Honesty clause (BINDING for all docs and code comments)

Per-request cost is **negligible**: each poll is a small authenticated GET (a few KB); ~556/day is not a bandwidth or per-request-cost problem, and the reduction must not be sold as one. The documented motivations are:
- **the owner's battery-life concern for the tracker ecosystem** — stated as the owner's motivation, NOT as a claimed mechanical saving: the integration's read rate does not command the tag's reporting cadence (the tag→gateway→cloud chain is autonomous; Petite Souris is what changes tag behaviour, server-side, and this spec does not touch it);
- **avoiding a future rate-limit** — if Feelloo ever introduces API throttling or abuse controls, a ~556-requests/day client is a plausible first target; the recommended profile cuts the secondary exposure by ~63 % and the quiet profile to single digits.

The verifiable claim is the request count itself. The READMEs must include the table (or its numbers) and this framing. No battery/bandwidth/cost claim beyond "fewer cloud calls, older data by design" may appear anywhere.

## 10. Version and docs (release requirements)

- `manifest.json` `"version"`: `1.8.0` → `"1.9.0"`; git tag `v1.9.0`; conventional commit for the bump per repo history.
- **README.md AND README_FR.md** (both mandatory; the FR file mirrors the EN content):
  1. **Features**: one new bullet — the five secondary polling intervals are configurable (1–1440 min; defaults preserve the current cadences).
  2. **Architecture table** (README.md :55–59 / FR :57): the five secondary rows' Interval column becomes **"Configurable (default 15 min / 1 h / 6 h / 15 min / 30 min)"**; the main row stays as 047 documented it.
  3. **Settings table** (README.md :83 / FR :85 area): five new rows (entity, location, range/default).
  4. **The "All other coordinators keep their fixed cadence" bullet (README.md :90 / FR :92) is rewritten** — it becomes false: the five secondary intervals are now configurable (defaults listed); the rest of the "polling disabled" semantics (token refresh, last-known values, Petite Souris) unchanged.
  5. **New subsection "Secondary polling intervals"** under Polling Control: what each setting controls (which sensors each coordinator feeds), the recommended profile (week/month/territory/session = 1440, activity default), the traffic table (§9.1) with the honesty framing (§9.3), the restart-anchored-schedule note (a 1440-min cadence is anchored at each HA start — frequent restarts mean more frequent fetches), the session ≤ territory coherence guidance, and the explicit statement: **slowing never removes, hides, or blanks entities** — data age stays visible (Last Update sensor's `secondary_polling_intervals` attribute, each entity's last-updated timestamp).
  6. **Numbers entity list** (README.md :207–209 / FR :209–211): five new entries.
  7. **Last Update sensor description**: mention the new `secondary_polling_intervals` attribute.
  8. **Requirements** section unchanged (HA ≥ 2024.12.0).

## 11. Verification

### 11.1 Harness extension (BINDING)

Extend `specs/047-polling-control/verification-harness.py` **in place** (the repo's single harness; the 048 spec names it). Same stub architecture (the faithful HA-2026.9 miniatures); update the file docstring to note the 048 extension. New suites:

- **H1 — Resolver table, per key** (all five keys): missing → default; valid; min 1; max 1440; `0` → default (not clamped); `1441` → default (not clamped); `"30"` → 30; `"abc"` → default; `None` → default; float `15.9` → 15 (inherited `int()` truncation); `"15.9"` → default (string not coercible). Defaults asserted == `{activity: 15, activity_week: 60, activity_month: 360, territory: 15, session: 30}`.
- **H2 — Defaults preserved (hard requirement)**: no options → each secondary coordinator constructed with `update_interval ==` the ORIGINAL timedelta constants (`ACTIVITY_UPDATE_INTERVAL`, `ACTIVITY_WEEK_UPDATE_INTERVAL`, `ACTIVITY_MONTH_UPDATE_INTERVAL`, `TERRITORY_UPDATE_INTERVAL`, `SESSION_UPDATE_INTERVAL` — assert against the constants themselves) — the structural proof that 1.9.0 defaults == 1.8.0 behaviour.
- **H3 — Each interval applied + independence**: options with ONE key set → only that coordinator's `update_interval` differs from default (the other four untouched); live apply (`async_apply_polling_interval`) sets the new interval and requests exactly one refresh; same-value apply is an idempotent no-op (no refresh); straggler bound check (the forced refresh cancels the pending old-cadence timer).
- **H4 — No-restart application**: the real `_async_update_listener` with changed options → all five `update_interval`s change, no reload, and the main coordinator's settings are unaffected; entity write path: apply-then-persist ORDER verified (mirror the 047 order-log check), options merged (existing keys preserved), validation rejects `0/1441/2.5/0.5/-1`.
- **H5 — Options flow**: 9-field schema, defaults resolved from current options, five `Range(1..1440)` validators present; polling-only submission persists all five + the two 047 keys, performs NO Firebase POST, leaves `entry.data` untouched; credentials paths intact (`password_required`, `invalid_auth`, validated change merges the options incl. the five); `create_entry` data == merged options.
- **H6 — Entity surface**: unique_ids `{uid}_polling_interval_{name}`, CONFIG category, bounds/step/unit/mode, hub `device_info`, `native_value` reads resolved options, `entry_id` fallback for legacy entries; the Last Update sensor's attributes include `secondary_polling_intervals` with the resolved dict.
- **H7 — NO SENSOR REMOVED** (the executable refutation of the hide-sensors approach): run the sensor platform's `async_setup_entry` with a collecting callback under FOUR option sets — defaults, recommended (§3), quiet, invalid values — and assert the collected entity unique_id SETS are **identical across all four runs** (and therefore identical to 1.8.0's). Also assert the pre-existing number entities (Petite Souris durations, main interval number) are unaffected by the option sets.
- **H8 — 047 regression**: the existing 137 checks keep passing (same file); plus targeted assertions that secondary options do NOT affect the main coordinator (constructor resolution, resolver, Petite-Souris override engage/restore) and that the five settings never interact with `petite_souris_override`.

Exit code 0 with all checks green. The 048 verification record states the new total and the delta (the 047 record's "137/137" remains the historical statement for the 1.8.0 session).

### 11.2 Manual/live matrix (owner's HA + real account; read-only observations)

| # | Case | Steps | Expected |
|---|------|-------|----------|
| L1 | Default upgrade path | Install 1.9.0 over 1.8.0, no options; watch logs ≥ 1 h | Secondary cadences unchanged (15 m / 1 h / 30 m observed in logs; the 6 h month cadence inferred from the absence of unexpected fetches); 5 new number entities present; no reload blips; 047 controls unchanged |
| L2 | Options flow, five intervals | Set week/month/territory/session = 1440, activity = 60; submit with blank password | No credential validation call; cadences apply without restart; one debounced fetch per changed coordinator in the logs, then the new cadences; credentials untouched |
| L3 | Entity write | Set the territory number 15 → 30 | One fetch within ~10 s, then 30-min cadence; value persists across restart; options flow shows the same value |
| L4 | Straggler on slowing | Change a cadence while a fetch is pending | At most one already-scheduled fetch at the old cadence, then the new cadence (047 §5.2 semantics) |
| L5 | Restart persistence | Restart HA with slow options | Startup first refresh for all six coordinators; slow cadences re-armed from options; the 1440-min cadence anchored at start time |
| L6 | Entity registry integrity | Compare the registry before/after | **Zero existing entities removed**; exactly 5 new number entities on the hub device (9 hub entities total); labels render in en and fr |
| L7 | Staleness visible | After ≥ 24 h with week = 1440 | Week sensors keep last values and stay available; each entity's last-updated shows its age; the Last Update sensor's `secondary_polling_intervals` shows the configured cadences |
| L8 | Multi-account (if two accounts configured) | Inspect both accounts' entities | Distinct unique_ids per account; no cross-talk |
| L9 | Petite Souris interplay | Engage Petite Souris with slowed secondaries | Main override engages at 1 min per 047; **secondaries keep their slow cadences throughout**; override end restores the main preference; the five numbers are unaffected |
| L10 | Quiet profile | All five = 1440 + main disabled | Logs show ~5 Feelloo fetches/day (+ ~29 token refreshes); **every sensor still alive** |
| L11 | Credentials still work | Options → new email + password | Validated against Firebase; entry reloads; rebuilt coordinators use the persisted intervals |

**Data safety (explicit):** no destructive or irreversible operation. Only local settings writes; read-only log/UI observations; the same GETs the integration already makes.

## 12. Deliverable files for the Coder (from this spec set)

- `specs/048-secondary-polling-intervals/spec.md` — requirements and scope
- `specs/048-secondary-polling-intervals/plan.md` — implementation order and acceptance criteria
- `specs/048-secondary-polling-intervals/research.md` — codebase findings and corrected arithmetic
- `specs/048-secondary-polling-intervals/data-model.md` — persisted/registry/translation model
- `specs/048-secondary-polling-intervals/quickstart.md` — owner-facing usage guide
- `specs/048-secondary-polling-intervals/contracts/secondary-polling.md` — this contract (BINDING)
- `specs/048-secondary-polling-intervals/verification.md` — the Coder's verification record (to be produced during implementation; §11 is its required content)