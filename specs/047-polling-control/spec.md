# Spec 047 — ha-feelloo: Polling Control

**Component:** `custom_components/feelloo/` (HACS custom component), version 1.7.5 → 1.8.0
**Repo:** `ha-feelloo`, pinned at commit `59e0361`
**Note:** This repo does not use spec-kit and has no `specs/` history; this spec set follows the orchestrator's artifact layout while staying adapted to a Home Assistant custom component. All content reflects the repo's own conventions (code style, translations, README, hacs.json).

## 1. Problem

The main coordinator polls the Feelloo cloud (`/users/cats` + per-cat detail) every 5 minutes, hardcoded (`CATS_UPDATE_INTERVAL`, `coordinator.py:192`). The owner wants control over this polling: turn it off entirely, change its cadence, and still be able to fetch on demand — without entities going stale/unavailable when polling is off.

## 2. Owner decisions (from interview — these are requirements, not options)

1. **Disable automatic polling** — main coordinator only (the `/users/cats` poller). All other coordinators (activity 15 m, activity_week 1 h, activity_month 6 h, territory 15 m, session 30 m) and the token refresh (50 m) keep their behavior.
2. **Change the polling frequency** — main coordinator only.
3. **Manual refresh as a global button** — one button that refreshes, not one per cat.
4. **Last known value** — with polling disabled, entities must keep showing the last known value and must NOT become unavailable merely because polling is off. Explicit owner choice.
5. **Settings surfaces** — in the existing OptionsFlow AND as configuration entities (switch + number) so they can be automated from Home Assistant. (Orchestrator decision on the owner's behalf.)

## 3. Requirements

### FR-1 Disable/enable
- Setting persisted in `entry.options`, default enabled (existing installs behave exactly as 1.7.5 until the owner changes something).
- Mechanism: the main coordinator's `update_interval` is `None` when disabled (HA: no periodic scheduling), `timedelta(minutes=N)` when enabled.
- The startup initial fetch (`async_config_entry_first_refresh`, `coordinator.py:204`) must still run when polling is disabled.
- The petite-souris fast polling timer (1 min) is part of the main coordinator's automatic polling; petite souris API commands still work; token refresh keeps running (manual refreshes need valid tokens). The original "suppressed while disabled" clause is superseded by FR-8: an active petite-souris mode temporarily re-enables 1-minute polling.
- No restart needed to apply.

### FR-2 Frequency
- Interval in minutes, stored in `entry.options`, applied to the main coordinator's `update_interval`.
- Bounds: min 1, max 1440 (24 h), default 5 (= current behavior). Justification in the contract §2.4.
- Changes take effect without HA restart and without an entry reload (live application), via a coordinator method; one bounded immediate fetch is acceptable when changing cadence.

### FR-3 Manual refresh button
- One `ButtonEntity` per config entry (global, not per cat), modeled on the repo's existing button platform style.
- Press refreshes **all coordinators** (main first, then the other five) — scope resolution justified in the contract §6: the owner's "global" concerns entity granularity; a manual button that left activity/territory/session stale would not do what the owner expects.
- Works with polling on or off; genuine failures surface (`HomeAssistantError` when the main refresh fails).

### FR-4 Last known value
- With polling disabled, no scheduled refreshes occur, so no failure states occur: `last_update_success` stays true and all entities retain values and availability (verified current behavior analysis in research.md §4 and contract §9).
- Disable must NEVER be implemented via errors/raising/clearing data.
- The genuine unavailability path (a refresh actually failing — e.g. auth failure) must remain intact.
- Data age is visible in the UI via a new diagnostic timestamp sensor ("Last Update") with `polling_enabled` / `polling_interval_minutes` attributes.

### FR-5 Settings surfaces
- `FeellooOptionsFlowHandler` gains the two settings without breaking the credential update path (credentials remain validated when actually changed; blank password = keep current).
- Two CONFIG-category entities on existing platforms: `switch` (enable/disable) and `number` (interval, box mode, 1–1440 min), following the repo's existing entity patterns (stable unique_ids from `entry.unique_id`, translation keys, hub device).
- Both entities apply the change live AND persist to options (idempotent under both listener and auto-reload HA semantics).

### FR-6 Persistence, version, docs
- Settings in `entry.options` only; `entry.data` stays credentials-only. No config entry version/migration.
- Defaults for existing installs = current behavior (enabled, 5 min).
- Release: manifest 1.8.0, tag `v1.8.0`, README section + entity list updates (and coordinator-table doc fix), translations en+fr.

### FR-7 Verification
- Repo has no test infrastructure → documented manual verification procedure with a required test matrix (contract §10: 14 cases covering defaults, disable via both surfaces, straggler bound, enable, live interval change, button on/off, petite souris interplay, restart, genuine failure path via reversible WAN cut, credentials flow, HA listener-behavior note).
- No destructive/irreversible operations involved — stated explicitly; no data-safety ritual invented.

### FR-8 Petite Souris × polling interplay (owner addition, 2026-10-08 — contract §4.2)
- An active petite-souris mode (any cat programmed) temporarily sets the main coordinator to 1-minute polling regardless of the user's preference, so the mode actually works.
- The user's real preference is preserved untouched in `entry.options` (never written by the override) and re-resolved live — not from a snapshot — when the mode ends, by manual deactivation or server-side expiry.
- Any manual polling change while the mode is active wins: the temporary override is cancelled (latched) and does not re-engage until the mode is deactivated and activated again; with polling left enabled, the legacy fast-polling timer keeps 1-minute tracking.
- The override state is transient (in-memory coordinator flags), reconstructed at startup from the cloud's `programmed` state; nothing is persisted for it.
- The diagnostic sensor exposes `petite_souris_override` and shows the effective cadence; the polling switch/number keep showing the saved preference.

## 4. Success criteria

- Existing install upgraded to 1.8.0 with no options set behaves identically to 1.7.5 (5-minute cadence, all entities, credentials flow).
- Owner can disable polling (switch or options flow): after at most one bounded straggler fetch, zero periodic main-coordinator fetches; entities keep last values; fast polling suppressed; button still fetches.
- Owner can set any interval 1–1440 minutes live.
- Pressing the button fetches all six coordinators once.
- Data age visible on the diagnostic sensor.
- All 14 verification-matrix rows PASS with notes recorded.

## 5. Non-goals

- No control over the five secondary coordinators' intervals.
- No new HA service, no new platform, no schema/migration machinery.
- No change to token refresh, petite souris switch semantics (besides the fast-polling gate), ring button, or the existing `set_petite_souris` service.
- No test-framework introduction.
- No HA minimum-version change.

## 6. Artifacts

`spec.md` (this file), `research.md`, `data-model.md`, `plan.md`, `quickstart.md`, `contracts/polling-control.md` (BINDING).