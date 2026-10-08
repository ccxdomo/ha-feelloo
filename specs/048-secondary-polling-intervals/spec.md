# Spec 048 — ha-feelloo: Secondary Polling Intervals

**Component:** `custom_components/feelloo/` (HACS custom component), version 1.8.0 → 1.9.0
**Repo:** `ha-feelloo`, branch `main`, pinned at commit `4f32b05` (released as `v1.8.0`)
**Predecessor:** Spec 047 — main-coordinator polling control, merged and released in 1.8.0. This spec extends the same mechanism family to the five secondary coordinators.
**Note:** This repo does not use spec-kit; this spec set follows the artifact layout established by spec 047 and the repo's own conventions (code style, translations, READMEs, hacs.json).

## 1. Problem

The integration runs six `DataUpdateCoordinator`s. Spec 047 made the **main** (cats) coordinator's polling fully configurable — enable/disable, interval (1–1440 minutes), manual refresh, last-known-value guarantee, and a Petite-Souris 1-minute override. The **five secondary coordinators still poll at hard-coded intervals** fixed in `const.py` and contribute roughly **268 extra scheduled refreshes/day** out of the integration's ~556/day total (all defaults, refresh-cycle convention):

| Coordinator | Interval (const.py @ 4f32b05) | Scheduled refreshes/day |
|-------------|-------------------------------|--------------------------|
| Main (cats) — already configurable via 047 | `CATS_UPDATE_INTERVAL` 5 min | 288 |
| Activity (day) | `ACTIVITY_UPDATE_INTERVAL` 15 min | 96 |
| Activity week | `ACTIVITY_WEEK_UPDATE_INTERVAL` 1 h | 24 |
| Activity month | `ACTIVITY_MONTH_UPDATE_INTERVAL` 6 h | 4 |
| Territory | `TERRITORY_UPDATE_INTERVAL` 15 min | 96 |
| Session | `SESSION_UPDATE_INTERVAL` 30 min | 48 |
| **Secondary subtotal** | | **268** |
| **Total** | | **556** |

(Each secondary refresh issues one API GET per cat; the main refresh issues one `/users/cats` GET plus one detail GET per cat. Full arithmetic and the multi-cat multiplier: contract §9.)

An external contributor (Reifircax, fork commit `e77bb3d`) independently implemented per-coordinator **enable/disable** flags plus **hiding of the associated sensors** when disabled. The owner reviewed that approach and judged it inferior to his own idea, which this spec implements instead: do not disable the secondary pollings — make their **intervals** configurable so they can be slowed down, keeping every sensor alive with reasonably fresh data.

## 2. Owner decisions (from interview — requirements, not options)

1. **No disabling.** The secondary pollings stay enabled; only their **intervals** become configurable. The contributor's enable/disable approach is explicitly rejected (rationale: contract §7).
2. **Stated goal:** "poll the weekly and monthly activity once a day, and the territory likewise" — a substantial traffic cut while every sensor keeps reporting reasonably fresh data.
3. **No sensor hiding, ever.** The owner wants the data to keep flowing, not entities blanked out. Last-known values are retained, consistent with 047's philosophy; staleness must be *visible*, never implemented by removing entities.
4. **Consistency with 047.** The main coordinator's switch/number/button entities and the Petite-Souris override keep working unchanged. The five new settings join the same mechanism family (config entry options + resolver + config entities + options flow) — no second, inconsistent control paradigm.

## 3. Requirements

### FR-1 Per-coordinator interval settings
Five settings — `activity`, `activity_week`, `activity_month`, `territory`, `session` — each persisted in `entry.options` (minutes, int), each applied to its coordinator's `update_interval`, each effective **without a Home Assistant restart**. Bounds: reuse the existing `POLLING_INTERVAL_MIN = 1` and `POLLING_INTERVAL_MAX = 1440` (justification: contract §2.4; the briefing's names "MIN/MAX_UPDATE_INTERVAL_MINUTES" do not exist — the actual constants are `POLLING_INTERVAL_MIN/MAX` and are reused unrenamed).

### FR-2 Defaults preserve today's behaviour EXACTLY (hard requirement)
With no options stored, each coordinator keeps its current cadence: **activity 15, activity_week 60, activity_month 360, territory 15, session 30** (minutes) — identical to the 1.8.0 constants. The resolver must fall back to the per-coordinator **default** for an absent, invalid, or out-of-range value — **never to the nearest bound** (mirror of 047 §2.2: a corrupted or partially edited options dict must never produce a surprising cadence).

### FR-3 Live application
Changes apply without an HA restart and without an entry reload, via the existing update listener (options flow path) and the new config entities (write path). Idempotent: an unchanged value is a no-op. One debounced immediate fetch (~10 s) per *changed* coordinator so the new cadence takes effect at once instead of waiting out the old timer (047 §5 case table, interval-change row; straggler bound: contract §5).

### FR-4 Consistency with Spec 047
The main coordinator's control surface (switch, number, button, Last Update sensor) and the Petite-Souris override are untouched and keep working unchanged. The five new settings reuse 047's established pattern: same bounds, same resolver semantics, same apply-then-persist discipline, same dual surface (options flow + config entities). No second inconsistent mechanism.

### FR-5 NO sensor hiding (binding prohibition)
No entity may be removed, hidden, disabled, or made unavailable by any combination of the new settings. The contributor's "hide their sensors" behaviour is explicitly rejected (full rationale: contract §7). Staleness is visible through the existing surfaces: the Last Update sensor (extended with a `secondary_polling_intervals` attribute) and each entity's own last-updated timestamp.

### FR-6 Options flow extension
The existing flow (credentials + 047's two polling fields) gains five interval fields without breaking either. Blank password = keep credentials; credential validation only when credentials actually change; **no constructor argument** to `FeellooOptionsFlowHandler` — the HA ≥ 2026.9 read-only `config_entry` constraint fixed by merged PR #2 must not be reintroduced.

### FR-7 Entity surface (recommendation — binding, see contract §6)
Mirror the 047 pattern: **five CONFIG-category `NumberEntity`s on the Feelloo hub device**, one per secondary coordinator, stable unique_ids `{uid}_polling_interval_{name}`, translation keys in en AND fr, box mode, 1–1440 min. No switches (disable rejected), no buttons (Refresh Data already refreshes all coordinators), no new services, platforms, or devices. Justification: contract §6.2.

### FR-8 Staleness visibility
The existing Last Update diagnostic sensor gains exactly one attribute: `secondary_polling_intervals` (the resolved dict). No new sensors. The data age of slowed entities remains visible via each entity's last-updated timestamp (HA built-in) and the configured cadence.

### FR-9 Traffic budget (honest, explicit arithmetic)
Both READMEs document the new settings and the traffic reasoning with an explicit requests/day table for the recommended settings (contract §9). Stated plainly: per-request cost is negligible; the motivations are the owner's battery-life concern for the tracker ecosystem (not claimed as a mechanical saving — the integration's read rate does not command the tag's reporting cadence) and avoiding a future rate-limit. No overstatement (contract §9.3).

### FR-10 Version + docs
`manifest.json` 1.8.0 → **1.9.0**, tag `v1.9.0` (repo convention). README.md **and** README_FR.md updated: features bullet, architecture table, settings table, "fixed cadence" bullet rewritten, five new entity-list entries, traffic subsection, no-hiding statement, restart-anchored-schedule note (contract §10).

### FR-11 Verification
The repo has no test infrastructure; spec 047 established the harness `specs/047-polling-control/verification-harness.py` (137 checks — re-run during this spec's research: **137/137 passing at 4f32b05**). **Extend that harness** with 048 suites: defaults preserved, each interval applied (constructor + live), clamping/fallback semantics, no-restart application (listener + entity write order), no sensor ever removed (entity-set equality across option sets), and 047 regression (main control + override unaffected). Live-only observations listed separately (contract §11.2).

## 4. Success criteria

- An existing install upgraded to 1.9.0 with no options set behaves identically to 1.8.0: secondary cadences 15/60/360/15/30, all entities present, credentials flow intact, all 047 controls and the Petite-Souris override unchanged.
- The owner can set each secondary interval 1–1440 minutes live, from a number entity or the options flow; the new cadence takes effect within ~10 s (one debounced fetch per changed coordinator), with no restart, no reload, and no entity blip.
- The owner's goal profile (week/month/territory/session = 1440) yields **100 secondary refreshes/day (−62.7 % of secondary traffic)**; with the main coordinator additionally disabled the whole integration drops to ~100/day, and the optional "quiet" profile (activity also 1440) reaches **5/day** (contract §9 table).
- No entity is ever removed, hidden, or made unavailable by any option combination; slowed sensors keep their last-known values and their age stays visible.
- All 047 mechanisms pass unchanged: the harness's original 137 checks stay green and the Petite-Souris interplay row verifies.
- The extended harness is fully green; the live matrix rows PASS with recorded notes.

## 5. Non-goals

- No enable/disable for the secondary coordinators (owner-rejected; no per-coordinator switches).
- No sensor hiding of any kind.
- No >1440-minute (multi-day) cadences — rejected with arithmetic (contract §2.4).
- No new HA services, platforms, devices, or per-coordinator Last-Update sensors.
- No change to: token refresh (50 min), the Petite-Souris override and switch/service semantics, main-coordinator control, the ring button, `set_petite_souris`, entity availability rules.
- No config entry schema migration (`VERSION` stays 1); no test framework; no HA minimum-version change (every 048 mechanism predates 2024.12; `hacs.json` untouched).

## 6. Artifacts

`spec.md` (this file), `research.md`, `data-model.md`, `plan.md`, `quickstart.md`, `contracts/secondary-polling.md` (BINDING).