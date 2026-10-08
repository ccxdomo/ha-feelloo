# Data Model 048 — Persistence, Registry, and State

All state introduced or changed by Spec 048, pinned to the design in `contracts/secondary-polling.md`.

## 1. Config entry

### 1.1 `entry.data` (unchanged shape)

```json
{
  "email": "<casefolded email>",
  "password": "<password>"
}
```
Credentials-only, exactly as 1.8.0. Spec 048 adds nothing here. The only writer remains the options flow's validated credentials path.

### 1.2 `entry.options` (extended with five keys)

```json
{
  "polling_enabled": true,                 // Spec 047 (main coordinator)
  "polling_interval": 5,                   // Spec 047 (main coordinator, minutes)
  "polling_interval_activity": 15,         // Spec 048 — minutes, default 15, range [1, 1440]
  "polling_interval_activity_week": 60,    // Spec 048 — minutes, default 60
  "polling_interval_activity_month": 360,  // Spec 048 — minutes, default 360
  "polling_interval_territory": 15,        // Spec 048 — minutes, default 15
  "polling_interval_session": 30           // Spec 048 — minutes, default 30
}
```
- Keys absent (existing 1.8.0 installs) → per-coordinator defaults → behaviour **identical to 1.8.0**: activity 15 min, activity_week 60 min, activity_month 360 min, territory 15 min, session 30 min. No migration code; config entry `VERSION` stays `1`.
- Resolution: `get_secondary_polling_intervals(entry) -> dict[str, int]` (in `const.py`, next to `get_polling_settings`) is the **single read path** for all five values. Per-key defensive semantics: missing, non-int-coercible, or outside `[POLLING_INTERVAL_MIN, POLLING_INTERVAL_MAX]` → that coordinator's **default**, never the nearest bound (047 §2.2 philosophy). `int()`-coercible strings accepted (`"30"` → 30); floats truncate through `int()` (`15.9` → 15) — inherited 047 semantics, deliberately not diverged.
- Settings live in `entry.options` only. No `hass.storage`, no registry-based storage.

## 2. `hass.data[DOMAIN][entry.entry_id]` (unchanged shape)

Existing keys (unchanged): `auth`, `main`, `activity`, `activity_week`, `activity_month`, `territory`, `session`, `active_credentials`.

Spec 048 adds **no new keys**. The update listener reaches the five secondary coordinators through the existing keys; the loop order is fixed: `activity`, `activity_week`, `activity_month`, `territory`, `session`.

## 3. Coordinator runtime attributes

New base class `FeellooSecondaryCoordinator(DataUpdateCoordinator)` (coordinator.py, placed before the five subclasses):

| Attribute | Type | Meaning |
|-----------|------|---------|
| `polling_interval_minutes` | `int` | resolved interval; set at construction from `get_secondary_polling_intervals(entry)[key]`, updated by `async_apply_polling_interval(interval_minutes)` |
| `update_interval` | `timedelta` | HA coordinator attr: `timedelta(minutes=N)` — always set for secondaries (they are never disabled; the owner rejected disabling) |

The five subclasses (`FeellooActivityCoordinator`, `FeellooActivityWeekCoordinator`, `FeellooActivityMonthCoordinator`, `FeellooTerritoryCoordinator`, `FeellooSessionCoordinator`) inherit both; their `_async_update_data` bodies and public getters are untouched. Constructors keep the `(hass, entry, auth)` signature.

`FeellooMainCoordinator` runtime attributes are **unchanged** (its own `polling_enabled`, `polling_interval_minutes`, `last_successful_fetch`, `_ps_override`, `_ps_override_cancelled`, and the 047 override machinery).

## 4. Device registry (unchanged)

| Device | Identifiers | Registered |
|--------|-------------|------------|
| Cat device (×N) | `(feelloo, <cat_uid>)` | `_async_setup_devices` (existing) |
| Hub device (1/entry) | `(feelloo, <entry.entry_id>)` | `_async_setup_devices` (existing, 047) |

Spec 048 registers no devices.

## 5. Entity registry (five new rows, all on the hub device)

| Entity (friendly name, en) | Platform | unique_id | Category | Translation key | Value |
|----------------------------|----------|-----------|----------|-----------------|-------|
| Polling Interval — Activity | number | `{uid}_polling_interval_activity` | CONFIG | `number.polling_interval_activity` | minutes, default 15 |
| Polling Interval — Activity Week | number | `{uid}_polling_interval_activity_week` | CONFIG | `number.polling_interval_activity_week` | default 60 |
| Polling Interval — Activity Month | number | `{uid}_polling_interval_activity_month` | CONFIG | `number.polling_interval_activity_month` | default 360 |
| Polling Interval — Territory | number | `{uid}_polling_interval_territory` | CONFIG | `number.polling_interval_territory` | default 15 |
| Polling Interval — Session | number | `{uid}_polling_interval_session` | CONFIG | `number.polling_interval_session` | default 30 |

`uid = entry.unique_id or entry.entry_id` (casefolded email from the config flow; stable across reinstall, distinct per account). Entity-id examples (single account): `number.feelloo_polling_interval_activity`, `number.feelloo_polling_interval_activity_week`, `number.feelloo_polling_interval_activity_month`, `number.feelloo_polling_interval_territory`, `number.feelloo_polling_interval_session`.

Class model: one parameterized class `FeellooSecondaryPollingIntervalNumber(NumberEntity)` instantiated five times (contract §6.1) — plain `NumberEntity` (not `CoordinatorEntity`; controls stay usable even when a coordinator's last refresh failed), `native_min_value=1`, `native_max_value=1440`, `native_step=1`, `native_unit_of_measurement="min"`, `mode="box"`, icon `mdi:clock-outline`. `native_value` reads the resolved options (saved == effective for secondaries — there is no override concept); **no extra_state_attributes** (nothing to distinguish; the Last Update sensor carries the dict for machine consumption).

## 6. Last Update sensor (one new attribute)

`FeellooLastUpdateSensor.extra_state_attributes` gains exactly one key:

```json
"secondary_polling_intervals": {
  "activity": 15,
  "activity_week": 60,
  "activity_month": 360,
  "territory": 15,
  "session": 30
}
```
(resolved values — the saved preferences; for secondaries saved == effective). The existing three attributes (`polling_enabled`, `polling_interval_minutes`, `petite_souris_override` — the main coordinator's *effective* state) are unchanged. The sensor already re-renders on entry updates, so the attribute follows changes made from any surface.

## 7. Options flow schema (data model)

```
step init (single step, 9 fields — all Optional):
  email                              default = current entry.data email
  password                           default = ""      (blank = keep current)
  polling_enabled                    default = current resolved (047)
  polling_interval                    default = current resolved (047), Coerce(int), Range(1..1440)
  polling_interval_activity           default = current resolved, Coerce(int), Range(1..1440)
  polling_interval_activity_week      default = current resolved, Coerce(int), Range(1..1440)
  polling_interval_activity_month     default = current resolved, Coerce(int), Range(1..1440)
  polling_interval_territory          default = current resolved, Coerce(int), Range(1..1440)
  polling_interval_session            default = current resolved, Coerce(int), Range(1..1440)
errors:
  invalid_auth       (existing) — credential validation failed
  password_required  (existing) — email changed, password blank
```

Submission produces one `async_update_entry` call: `data` included only when credentials changed (and were validated); `options` always the merge of the existing options with all seven polling keys. `async_create_entry(title=email, data=new_options)` — the merged options, per the 047 source-verified deviation #1 (HA persists create_entry data as `entry.options`; an empty dict would wipe them).

The handler remains **no-arg** (`FeellooOptionsFlowHandler()`); `config_entry` comes from the read-only base property (HA ≥ 2026.9 constraint).

## 8. Update listener (event path)

```
entry.data / entry.options updated (from options flow, config entities, or API)
   └─ _async_update_listener(hass, entry)
        ├─ entry.data != active_credentials  → credentials changed → async_reload(entry)
        └─ otherwise → await data["main"].async_apply_polling_settings(*get_polling_settings(entry))
                       then for each key in SECONDARY order:
                         await data[key].async_apply_polling_interval(resolved[key])
                       (idempotent — unchanged values are no-ops; no reload, no entity blip)
```

## 9. Translation model (en.json / fr.json)

Added keys (exact strings in contract §8):
- `options.step.init.description` (updated text mentioning secondary intervals)
- `options.step.init.data.polling_interval_activity` (+ `_week`, `_month`, `_territory`, `_session`)
- `entity.number.polling_interval_activity` (+ `_week`, `_month`, `_territory`, `_session`) — en and fr

## 10. Versioning

- `manifest.json`: 1.8.0 → **1.9.0**; git tag `v1.9.0` (repo convention: minor bump for user-facing features with no breaking change).
- `hacs.json`: **unchanged** (`homeassistant: 2024.12.0`). Every 048 mechanism (options keys, resolver, `update_interval` assignment, debounced refresh, update listeners, `NumberEntity` native API, CONFIG category, translations) predates 2024.12; the read-only `config_entry` constraint is respected by leaving the flow handler's constructor untouched.
- No `requirements` changes.