# Quickstart 048 — Secondary Polling Intervals (owner guide)

How to use the secondary polling intervals once release **1.9.0** of the Feelloo integration is installed (HACS update or manual copy + restart).

## What you get

Five new **config numbers on the Feelloo hub device** (Settings → Devices & Services → Feelloo), one per secondary coordinator, plus the same five fields in the options flow (Configure). Each sets that coordinator's polling interval in minutes (1–1440). Defaults are the current cadences — nothing changes until you change something:

| Entity | Controls | Default |
|--------|----------|---------|
| **Polling Interval — Activity** | today's rest/calm/action percentages and history | 15 min |
| **Polling Interval — Activity Week** | weekly percentages | 60 min |
| **Polling Interval — Activity Month** | monthly percentages | 360 min (6 h) |
| **Polling Interval — Territory** | outing start/end, outing count | 15 min |
| **Polling Interval — Session** | last session duration, points, start/end | 30 min |

All five are also editable in the options flow, are persisted in the config entry options (survive restarts), and apply **live** — no Home Assistant restart, no integration reload, fresh cadence within ~10 seconds.

## The recommended setup (your stated goal)

"Weekly and monthly activity once a day, and the territory likewise":

1. Set **Polling Interval — Activity Week** to `1440`
2. Set **Polling Interval — Activity Month** to `1440`
3. Set **Polling Interval — Territory** to `1440`
4. Set **Polling Interval — Session** to `1440` — recommended companion: the session detail only changes when territory refreshes, so a faster session cadence would re-download the same payload ~48×/day
5. Leave **Polling Interval — Activity** at `15` (today's activity is the only secondary data that changes hour by hour) — or slow it too if you accept day-old percentages

What this does to the cloud traffic (scheduled refreshes/day, single-cat arithmetic):

| Coordinator | Before | After |
|-------------|--------|-------|
| Main (cats) | 288 (5 min) | 288 — or **0** if you also disable it via the 047 **Automatic Polling** switch |
| Activity | 96 | 96 (default kept) |
| Activity week | 24 | 1 |
| Activity month | 4 | 1 |
| Territory | 96 | 1 |
| Session | 48 | 1 |
| **Secondary subtotal** | **268** | **100 (−62.7 %)** |
| **Total (main at 5 min)** | **556** | **388 (−30.2 %)** |
| **Total (main disabled)** | | **100 (−82.0 %)** |
| "Quiet profile": activity also 1440, main disabled | | **5/day (−99.1 %)** |

Honest framing, stated plainly: each request costs nothing (a few KB GET) — this is not a bandwidth saving. The motivations are your battery-life concern for the tracker ecosystem and avoiding a future rate-limit (a ~556-requests/day client is a plausible first target if Feelloo ever throttles). The verifiable fact is the request count itself. Note the honest caveat recorded in the docs: the integration's read rate does not command the tracker's own reporting cadence (the tag→gateway→cloud chain is autonomous; Petite Souris is what changes tag behaviour) — so no mechanical battery saving is claimed.

Multi-cat households: each secondary refresh fetches once per cat, so multiply the secondary rows by your number of cats.

## What slowing means — and what it never means

- **Sensors stay alive.** Slowing a coordinator never removes, hides, or blanks its entities. They keep their last-known values and stay available; their data is simply older by design.
- **Age stays visible.** Each entity's *last updated* timestamp shows how old its data is, and the **Last Update** sensor's new `secondary_polling_intervals` attribute shows the configured cadences at a glance.
- **On-demand freshness always works.** The **Refresh Data** button fetches everything now, whatever the cadences (and whatever the main polling state).
- **A daily cadence is anchored at each HA start**: with 1440-minute intervals, the day's fetch happens 24 h after each restart — frequent restarts mean more frequent fetches.
- **Coherence guidance**: keep session ≤ territory (the recommended profile sets both to 1440). Nothing enforces it.
- **Main-coordinator features are untouched**: the 047 switch/number/button and the Petite Souris override (temporary 1-minute main polling while the mode is active) work exactly as before — secondaries keep their slow cadences even during a Petite Souris boost.

## Automate it (examples)

```yaml
automation:
  - alias: "Slow territory at night"
    trigger:
      - platform: time
        at: "23:00:00"
    action:
      - service: number.set_value
        target:
          entity_id: number.feelloo_polling_interval_territory
        data:
          value: 1440
  - alias: "Watch the outings on weekend mornings"
    trigger:
      - platform: time
        at: "09:00:00"
    condition:
      - condition: time
        weekday:
          - sat
          - sun
    action:
      - service: number.set_value
        target:
          entity_id: number.feelloo_polling_interval_territory
        data:
          value: 15
  - alias: "Fetch everything when I come home"
    trigger:
      - platform: zone
        entity_id: person.owner
        zone: zone.home
        event: enter
    action:
      - service: button.press
        target:
          entity_id: button.feelloo_refresh_data
```

## Good to know

- **Upgrades are invisible**: installing 1.9.0 over 1.8.0 with no options set changes nothing — every cadence stays 15/60/360/15/30 until you set a value.
- **Corrupted values are safe**: an absent, invalid, or out-of-range stored value falls back to that coordinator's default (never to the nearest bound) — a partially edited options file can never produce a surprising cadence.
- **Credentials flow unchanged**: the options flow still never demands your password for polling-only edits (leave it blank); entering new credentials still validates and applies them.
- **Multiple accounts**: each configured account gets its own set of the five entities.
- **Why not disable/hide?** A contributor's fork did exactly that (per-coordinator on/off switches that hid the sensors). The owner rejected it: it destroys last-known values, breaks automations and history referencing the entities, and hides data age instead of showing it. Slowing keeps every sensor alive with reasonably fresh data — which is what this release implements.