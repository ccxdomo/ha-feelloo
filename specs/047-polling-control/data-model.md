# Data Model 047 — Persistence, Registry, and State

All state introduced or changed by Spec 047, pinned to the design in `contracts/polling-control.md`.

## 1. Config entry

### 1.1 `entry.data` (unchanged shape)

```json
{
  "email": "<casefolded email>",
  "password": "<password>"
}
```
Credentials-only, exactly as 1.7.5. The spec does not add anything here.

### 1.2 `entry.options` (extended)

```json
{
  "polling_enabled": true,       // bool,   default true  — omit = default
  "polling_interval": 5          // int,    minutes,      default 5, range [1, 1440]
}
```
- Keys absent (existing installs) → defaults → behavior identical to 1.7.5. No migration code; no config entry `VERSION`/`minor_version` bump.
- Resolution helper `get_polling_settings(entry) -> tuple[bool, int]` (in `const.py`) is the single read path; it clamps invalid/missing values to defaults (invalid values fall back to defaults, not to nearest bounds).

## 2. `hass.data[DOMAIN][entry.entry_id]`

Existing keys (unchanged): `auth`, `main`, `activity`, `activity_week`, `activity_month`, `territory`, `session`.

New key:

| Key | Type | Set | Purpose |
|-----|------|-----|---------|
| `active_credentials` | `dict` (copy of `entry.data`) | in `async_setup_entry`, after coordinators are created | lets the update listener detect credential-only changes (compare against `entry.data` on listener invocation) |

## 3. Main coordinator runtime attributes (`FeellooMainCoordinator`)

| Attribute | Type | Meaning |
|-----------|------|---------|
| `polling_enabled` | `bool` | current resolved setting (constructor + `async_apply_polling_settings`) |
| `polling_interval_minutes` | `int` | current resolved interval |
| `last_successful_fetch` | `datetime \| None` | set at the end of each successful `_async_update_data`; drives the diagnostic sensor |
| `update_interval` | `timedelta \| None` | HA coordinator attr: `timedelta(minutes=N)` when enabled, `None` when disabled |
| existing: `_fast_polling_active`, `_fast_polling_timer`, `_cancel_token_refresh`, `_cancel_fast_polling_listen` | unchanged | fast polling now gated by `polling_enabled` inside `_sync_fast_polling_timer` |
| `_ps_override` | `bool` | Petite Souris 1-minute polling override engaged (§4.2 owner addition). TRANSIENT — never persisted; reconstructed at startup from the API `programmed` state |
| `_ps_override_cancelled` | `bool` | Manual-control latch: a manual polling change while the mode was active cancelled the override; resets when the mode fully ends |

Note: while the override is engaged, `polling_enabled` / `polling_interval_minutes` / `update_interval` hold the EFFECTIVE (temporary) state — enabled @ 1 minute — while `entry.options` keeps the user's real preference.

## 4. Device registry

| Device | Identifiers | Name / model | Registered |
|--------|-------------|--------------|------------|
| Cat device (×N, unchanged) | `(feelloo, <cat_uid>)` | cat name / "Cat Tracker" | `_async_setup_devices` (existing) |
| **Hub device (new, 1/entry)** | `(feelloo, <entry.entry_id>)` | "Feelloo" / "Account" | `_async_setup_devices` (additive, unconditional) |

## 5. Entity registry (new entities, all per config entry, all on the hub device)

| Entity | Platform | unique_id | Category | Translation key | Notes |
|--------|----------|-----------|----------|-----------------|-------|
| Automatic polling toggle | switch | `{entry.unique_id or entry.entry_id}_polling_enabled` | CONFIG | `switch.polling_enabled` (base) / `switch.polling_enabled_override` (while §4.2 override runs) | plain `SwitchEntity`, not CoordinatorEntity; state = EFFECTIVE polling (owner follow-up 2: reads ON while the §4.2 override runs, otherwise the persisted preference); attributes `saved_polling_enabled` / `saved_polling_interval_minutes` / `effective_polling_enabled` / `effective_polling_interval_minutes`; icon `mdi:clock-fast` + registry `translation_key` = `polling_enabled_override` while overridden (registry update skipped when unregistered/user-renamed); turn on/off = live apply then persist (command semantics unchanged) |
| Polling interval | number | `{uid}_polling_interval` | CONFIG | `number.polling_interval` | plain `NumberEntity`; min 1, max 1440, step 1, unit "min", mode "box"; set = live apply then persist; native_value = saved preference (unchanged, owner follow-up 2); attribute `effective_polling_interval_minutes` exposes the §4.2 override cadence |
| Refresh data | button | `{uid}_refresh_data` | none | `button.refresh_data` | `ButtonEntity`; press = main refresh (raise on failure) + gather(refresh 5 others, log failures) |
| Last update | sensor | `{uid}_last_update` | DIAGNOSTIC | `sensor.last_update` | `CoordinatorEntity(main)`; `device_class=TIMESTAMP`; native_value = `last_successful_fetch`; attributes `polling_enabled`, `polling_interval_minutes`, `petite_souris_override` (single source of truth for "is the override running") |

Entity id examples (single account, cat "Moustache"): `switch.feelloo_automatic_polling`, `number.feelloo_polling_interval`, `button.feelloo_refresh_data`, `sensor.feelloo_last_update`.

## 6. Options flow schema (data model)

```
step init (single step):
  email                Optional[str]   default = current entry.data email
  password             Optional[str]   default = ""      (blank = keep current)
  polling_enabled      Optional[bool]  default = current resolved
  polling_interval     Optional[int]   default = current resolved, coerced, Range(1..1440)
errors:
  invalid_auth      (existing) — credential validation failed
  password_required (new)      — email changed, password blank
```
Submission produces one `async_update_entry` call: `data` included only if credentials changed (validated); `options` always merged with the two keys.

## 7. Update listener (event path)

```
entry.data / entry.options updated (from options flow or config entities)
   └─ _async_update_listener(hass, entry)
        ├─ entry.data != active_credentials  → credentials changed → async_reload(entry)
        └─ otherwise                         → main.async_apply_polling_settings(*get_polling_settings(entry))
                                                (idempotent; no reload, no entity blip)
```

## 8. Translation model (en.json / fr.json)

Added/changed keys (exact strings in contract §8.3):
- `options.step.init.description` (updated text)
- `options.step.init.data.polling_enabled`, `options.step.init.data.polling_interval`
- `options.error.password_required` (new)
- `entity.switch.polling_enabled`
- `entity.number.polling_interval`
- `entity.button.refresh_data`
- `entity.sensor.last_update`

## 9. Versioning

- `manifest.json`: 1.7.5 → **1.8.0**; git tag `v1.8.0` (repo convention).
- `hacs.json`: HA minimum raised 2024.1.0 → **2024.12.0** (Reviewer follow-up, 2026-10-08). The merged HA-2026.9 options-flow fix relies on the base `OptionsFlow` resolving `config_entry`, which first shipped in HA 2024.12.0 (source-verified: 2024.1–2024.11 define no base property and never assign one). Every mechanism added by 047 itself predates 2024.1.
- No `requirements` changes.