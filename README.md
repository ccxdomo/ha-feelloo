<p align="center">
  <img src="https://raw.githubusercontent.com/ccxdomo/ha-feelloo/main/icon.png" width="128" height="128" alt="Feelloo Logo">
</p>

# Feelloo Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Custom integration for [Feelloo](https://feelloo.com) cat trackers in Home Assistant.

## Features

- **Real-time GPS tracking** — live location on the Home Assistant map
- **Activity monitoring** — rest, calm, and action percentages with hourly history
- **Territory sessions** — track outings with start/end timestamps and session count
- **Battery & charging status** — never miss a low battery
- **Presence detection** — home / away / in-range status
- **Ring button** — locate your cat by triggering the tag ringtone
- **Extended search mode** — monitor search activation and expiration
- **Dynamic fast polling** — when Petite Souris mode is enabled, polling increases to 1 minute for real-time GPS and signal strength updates
- **Polling control** — disable automatic polling or change its cadence (1–1440 minutes), refresh on demand, and see data age — see [Polling Control](#polling-control)
- **Secondary polling intervals** — each of the five secondary coordinators (daily, weekly and monthly activity, territory, session) has its own configurable polling interval (1–1440 minutes; the defaults preserve the current cadences)

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations**
3. Click the menu (⋮) and select **Custom repositories**
4. Add `https://github.com/ccxdomo/ha-feelloo` with category **Integration**
5. Click **Download**
6. Restart Home Assistant

### Manual

1. Copy the `custom_components/feelloo` folder to your Home Assistant `config/custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Feelloo**
3. Enter your Feelloo account email and password

Your cats and their data will be automatically discovered.

## Architecture

The integration uses **six DataUpdateCoordinators** for optimal polling:

| Coordinator | Endpoint | Interval |
|------------|----------|----------|
| Main | `/users/cats` + `/users/cats/{cat_id}` | **Configurable** (default 5 minutes; 1 min with Petite Souris fast polling) |
| Activity | `/users/cats/{cat_id}/activity?period_type=day` | **Configurable** (default 15 minutes) |
| Activity Week | `/users/cats/{cat_id}/activity?period_type=week` | **Configurable** (default 1 hour) |
| Activity Month | `/users/cats/{cat_id}/activity?period_type=month` | **Configurable** (default 6 hours) |
| Territory | `/users/cats/{cat_id}/territory/paths` | **Configurable** (default 15 minutes) |
| Session | `/users/cats/{cat_id}/territory/paths/{session_id}` | **Configurable** (default 30 minutes) |

All coordinators share a single Firebase auth manager with automatic token refresh every 50 minutes (always running, even when polling is disabled, so on-demand fetches can always authenticate).

### Dynamic Fast Polling

When the **Petite Souris** switch is turned ON for a cat:
- The integration temporarily sets the **main coordinator to a 1-minute polling interval** (the "Petite Souris override") — this is what makes the mode actually work, whether automatic polling is enabled or disabled
- This affects GPS location, signal strength, battery, and all main coordinator entities
- When the mode ends (switch OFF or server-side expiry), **your polling settings are restored exactly** — including back to "disabled" if that is what you had configured
- Multiple cats share one override: it engages when the first cat activates and ends when the last one deactivates; extending the duration or activating it twice changes nothing (idempotent)
- **If you change a polling setting manually while the mode is active, your manual action wins** — the temporary 1-minute boost stops and will not re-engage until the mode is deactivated and activated again. While polling stays enabled, the mode still gets 1-minute updates through the legacy fast-polling timer. Setting the **Polling Interval** during the boost saves that value as your preference and stops the boost
- Your configured preference is never modified by the mode: it lives in the config entry options, and the temporary override is transient (in-memory; after a Home Assistant restart it is reconstructed from the Feelloo cloud's mode state)

**Seeing the polling interval change to 1 minute on its own?** That is the override at work: while any cat has Petite Souris active, the main poller runs at 1 minute, and your saved settings resume automatically when the mode ends (switch OFF or expiry). To confirm, check the **Last Update** sensor's `petite_souris_override` attribute (`true` during the boost) or the info log line `Petite Souris active: temporary 1-minute polling override engaged`. The **Automatic Polling** switch visibly turns itself ON for the duration of the boost — labeled *(Petite Souris)* with a fast-clock icon — and flips back to your saved state when the mode ends; the **Polling Interval** number shows the effective 1-minute cadence while the boost runs and returns to your saved value when the mode ends (your preference stays visible in its `saved_polling_interval_minutes` attribute).

## Polling Control

You control how often (and whether) the Feelloo cloud is polled automatically. All settings live on the **Feelloo** hub device (one set per configured account) and in the integration's options flow (Settings → Devices & Services → Feelloo → Configure).

### Settings

| Setting | Where | Range / Default |
|---------|-------|------------------|
| **Automatic Polling** (switch, config) | Feelloo device | ON (default) / OFF |
| **Polling Interval** (number, config) | Feelloo device | 1–1440 minutes, default **5** |
| **Polling Interval — Activity** (number, config) | Feelloo device | 1–1440 minutes, default **15** |
| **Polling Interval — Activity Week** (number, config) | Feelloo device | 1–1440 minutes, default **60** |
| **Polling Interval — Activity Month** (number, config) | Feelloo device | 1–1440 minutes, default **360** |
| **Polling Interval — Territory** (number, config) | Feelloo device | 1–1440 minutes, default **15** |
| **Polling Interval — Session** (number, config) | Feelloo device | 1–1440 minutes, default **30** |

All settings can also be edited in the options flow, and all are persisted in the config entry options (they survive restarts). Changes apply live — no Home Assistant restart and no integration reload is needed.

### What "polling disabled" means

- The **main coordinator** (`/users/cats`) stops fetching on its own. After at most one already-scheduled fetch, zero automatic cloud calls are made for cat data.
- **The five secondary coordinators keep polling at their configured intervals** (daily, weekly and monthly activity, territory, session — each configurable 1–1440 min, defaults 15 m / 1 h / 6 h / 15 m / 30 m; see [Secondary polling intervals](#secondary-polling-intervals)). They read the last-known cat list, so they keep fetching even with the main poller disabled.
- **Token refresh (auth housekeeping) keeps running** (~50 min) so manual refreshes and Petite Souris commands still work.
- **Petite Souris + polling disabled**: turning Petite Souris ON while automatic polling is disabled **temporarily re-enables polling at 1 minute** so the mode actually tracks your cat (a log line notes it). When the mode ends, polling is disabled again automatically — your preference is remembered in the entry options and never modified. If you manually change any polling setting while the mode is active, your manual action wins (the temporary boost stops) — turning the **Automatic Polling** switch OFF during the boost immediately stops it and the switch visibly flips to OFF.
- **The override is visible on the polling switch**: while the boost runs, the **Automatic Polling** switch reads **ON** (polling IS running, at 1 minute), shows a fast-clock icon, and is labeled *Automatic Polling (Petite Souris)* — a control that looks disabled while data flows can no longer happen. Its attributes expose both your saved preference (`saved_polling_enabled`, `saved_polling_interval_minutes`) and what is currently in force (`effective_polling_enabled`, `effective_polling_interval_minutes`). When the mode ends, the switch returns to your saved state automatically. The **Polling Interval** number shows the effective interval too — 1 minute during the boost, back to your saved value when it ends — with the saved preference visible in `saved_polling_interval_minutes` and the override flagged by `petite_souris_override`.
- **The Last Update sensor stays the source of truth for the override**: while the boost runs, its `polling_enabled` / `polling_interval_minutes` attributes show the temporary 1-minute cadence and `petite_souris_override` is `true`.
- **Entities keep their last known values**: with no refreshes there are no failures, so nothing goes "unavailable" just because polling is off. Genuine failures (network down, bad credentials) still surface exactly as before.
- The **Last Update** diagnostic sensor freezes at the last successful fetch, so data age is always visible; its attributes show the current polling settings.
- Disabling polling applies a debounced immediate refresh when **re-enabling** or changing the interval while enabled (fresh data arrives within ~10 s), so changes take effect without waiting out the old timer.

### Secondary polling intervals

Each of the five secondary coordinators has its own polling interval, configurable from **1 to 1440 minutes** (24 h) — via the five **Polling Interval — …** numbers on the Feelloo hub device or the options flow. Defaults preserve the 1.8.0 cadences exactly, so nothing changes until you set a value:

| Setting | Controls | Default |
|---------|----------|---------|
| **Polling Interval — Activity** | today's rest/calm/action percentages and history | 15 min |
| **Polling Interval — Activity Week** | weekly percentages | 60 min |
| **Polling Interval — Activity Month** | monthly percentages | 360 min (6 h) |
| **Polling Interval — Territory** | last outing start/end, outing count | 15 min |
| **Polling Interval — Session** | last session duration, points, start/end | 30 min |

**Recommended profile** ("poll the weekly and monthly activity once a day, and the territory likewise"): set **Activity Week**, **Activity Month**, **Territory** and **Session** to `1440`, keep **Activity** at `15` (today's activity is the only secondary data that changes hour by hour). The session coordinator fetches the latest *known* session, which only changes when territory refreshes — a 30-minute session cadence over a 1-day territory cadence would re-download an identical payload ~48×/day. Guidance only: keep **Session ≤ Territory** for coherence; nothing enforces it.

**Cloud traffic** (scheduled refreshes/day, single-cat arithmetic — each secondary refresh is one API GET per cat; one main refresh is one list GET plus one detail GET per cat):

| Coordinator | Defaults | Recommended profile |
|-------------|----------|---------------------|
| Main (cats) | 288 (5 min) — or **0** when disabled via 047 | 288 / 0 |
| Activity (day) | 96 | 96 |
| Activity week | 24 | 1 |
| Activity month | 4 | 1 |
| Territory | 96 | 1 |
| Session | 48 | 1 |
| **Secondary subtotal** | **268** | **100 (−62.7 %)** |
| **Total, main at 5-min default** | **556** | **388 (−30.2 %)** |
| **Total, main disabled** | | **100 (−82.0 %)** |
| **"Quiet profile"** (activity also 1440, main disabled) | | **5 (−99.1 %)** |

Multi-cat households: multiply the secondary rows by the number of cats (and the main row by 1 + cats). The Firebase token refresh (~29 requests/day, `1440/50`) keeps running regardless of any setting — auth housekeeping on a separate endpoint, not counted in the 556.

**Honest framing**: each request is a small authenticated GET (a few KB) — this is not a bandwidth or per-request-cost saving. The documented motivations are the owner's battery-life concern for the tracker ecosystem (stated as the motivation, **not** as a claimed mechanical saving — the integration's read rate does not command the tag's reporting cadence; the tag→gateway→cloud chain is autonomous, and Petite Souris is what changes tag behaviour, server-side) and avoiding a future rate limit (a ~556-requests/day client is a plausible first target if Feelloo ever introduces API throttling; the recommended profile cuts the secondary exposure by ~63 %, the quiet profile to single digits). The verifiable claim is the request count itself.

**What slowing never means**: slowing a coordinator **never removes, hides, disables, or blanks its entities** — they keep their last-known values, stay available, and their data age stays visible (each entity's *last updated* timestamp, and the **Last Update** sensor's `secondary_polling_intervals` attribute showing the configured cadences). On-demand freshness is always available via the **Refresh Data** button, whatever the cadences. A 1440-minute cadence is anchored at each Home Assistant start — frequent restarts mean more frequent fetches. An absent, invalid, or out-of-range stored value falls back to that coordinator's default (never to the nearest bound), so a partially edited options file can never produce a surprising cadence.

All five are automation targets (e.g. `number.set_value`), exactly like the main interval.

### Manual Refresh

The **Refresh Data** button (one per account, on the Feelloo device) fetches everything now — the main cats data first, then activity, weekly/monthly activity, territory and session data. It works with polling on or off. Rapid double-presses are safe (they are coalesced).

Automation example:

```yaml
automation:
  - alias: "Refresh when I come home"
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

### Credentials in the options flow

The options flow no longer asks for your password just to change polling settings — leave the password **blank to keep your current credentials**. Entering a new email (with password) or a new password still validates against Firebase and applies them as before.

## Entities

For each detected cat, the following entities are created:

### Binary Sensors
- **Home** — whether the cat is at home
- **In Range** — whether the tag is in LoRa range
- **Gateway Online** — whether the gateway is connected
- **Charging** — whether the tag is charging
- **Is Ringing** — whether the tag is currently ringing
- **Battery Low** — low battery warning
- **Extended Search** — whether extended search mode is enabled

### Sensors
- **Signal Strength** — LoRa signal strength (%) from tag to gateway
  - Attribute: `rssi_dbm` — raw RSSI value
- **Battery** — battery level (%)
- **Latitude** / **Longitude** — last known GPS coordinates
- **GPS Precision** — accuracy in meters
- **Last Seen** — timestamp of last location update
- **Presence Time** — timestamp of last presence detection
- **Activity** — current dominant activity (sleep / calm / active)
  - Attribute: `history` — full 24-hour hourly breakdown
- **Activity Rest** — rest percentage (%)
- **Activity Calm** — calm percentage (%)
- **Activity Action** — action percentage (%)
  - Attribute: `history` — full 24-hour hourly breakdown
- **Extended Search Expiration** — when extended search expires
- **Last Outing Start** — timestamp of last territory session start
- **Last Outing End** — timestamp of last territory session end
- **Outing Count** — total number of territory sessions

### Device Tracker
- **Tracker** — GPS location on the Home Assistant map
  - `source_type`: GPS
  - `latitude` / `longitude`: last known coordinates
  - `location_accuracy`: precision radius in meters (circle on the map)
  - State: `home` if `presence.status.in_range` is true, otherwise `not_home`
  - Attributes:
    - `last_seen`: ISO timestamp of last location update
    - `precision_meter`: GPS accuracy in meters
  - Icon: `mdi:cat`
  - **Custom picture**: see [Custom Cat Images](#custom-cat-images) below

### Custom Cat Images

You can display a custom photo for each cat on the map and in the device tracker card.

**How it works:**
- At startup, the integration checks if an image file exists for each cat
- If found, it automatically sets `entity_picture` on the device tracker
- No API call or cloud storage needed — purely local files

**Where to place the image:**

Create the folder and copy your cat's photo:

```bash
mkdir -p /config/www/feelloo
cp /path/to/your/photo.jpg /config/www/feelloo/{cat_name}.jpg
```

Replace `{cat_name}` with your cat's name slug (lowercase, spaces as underscores).

**File naming:**
- The filename must match the **cat name slug** (lowercase, spaces replaced by underscores)
- Example: cat named `Moustache` → file must be named `moustache.jpg` or `moustache.png`
- Example: cat named `Moustache Le Chat` → file must be named `moustache_le_chat.jpg`

**Supported formats:** `.jpg` and `.png`

**Recommended resolution:** 400×400 pixels (1:1 ratio) for optimal display on the map and entity cards

**Dynamic detection:** the integration checks for the image file at every coordinator refresh (every 5 minutes, or every 1 minute when Petite Souris is ON). No restart required — just add the image and wait for the next refresh.

**Result:** the device tracker will show your cat's photo instead of the default `mdi:cat` icon on the map and in entity cards.

### Switches
- **Petite Souris** — enables/disables extended search mode with fast polling
  - When ON: polling interval drops to **1 minute** for real-time GPS and signal strength (unless automatic polling is disabled)
  - When OFF: returns to normal polling
  - Each cat has its own independent timer
- **Automatic Polling** (config) — on the **Feelloo** device; ON = the main poller runs automatically (default), OFF = no automatic polling (see [Polling Control](#polling-control)). While a Petite Souris override is active the switch reads ON (polling runs at 1 minute) with a *(Petite Souris)* label and a fast-clock icon; its attributes expose your saved preference and the effective state

### Numbers
- **Petite Souris Duration** — duration in hours used when Petite Souris is enabled
- **Polling Interval** (config) — on the **Feelloo** device; main poller cadence in minutes (1–1440, default 5). While a Petite Souris override is active, the value shown is the effective 1-minute cadence (`saved_polling_interval_minutes` keeps your saved value visible, `petite_souris_override` flags the override); when the mode ends the number returns to your saved value automatically
- **Polling Interval — Activity** (config) — on the **Feelloo** device; daily-activity coordinator cadence in minutes (1–1440, default 15)
- **Polling Interval — Activity Week** (config) — weekly-activity coordinator cadence in minutes (1–1440, default 60)
- **Polling Interval — Activity Month** (config) — monthly-activity coordinator cadence in minutes (1–1440, default 360)
- **Polling Interval — Territory** (config) — territory coordinator cadence in minutes (1–1440, default 15)
- **Polling Interval — Session** (config) — session coordinator cadence in minutes (1–1440, default 30)

### Button
- **Ring** — trigger the tag ringtone (only if `can_ring` is true)
- **Refresh Data** — on the **Feelloo** device; fetches all Feelloo data now (all coordinators), regardless of polling state

### Sensors (device-level, on the **Feelloo** hub device)
- **Last Update** (diagnostic) — timestamp of the last successful cats fetch; freezes when polling is off so data age is visible. Attributes: `polling_enabled`, `polling_interval_minutes` (the **effective** state — during a Petite Souris override they show the temporary 1-minute cadence), `petite_souris_override` (`true` while the override temporarily forces 1-minute polling), and `secondary_polling_intervals` (the five configured secondary cadences, in minutes)

## Device Registry

Each cat is registered as a device with:
- Name: the cat's profile name
- Manufacturer: Feelloo
- Model: Cat Tracker

Each configured account also gets a **Feelloo** hub device (model: Account) hosting the per-account entities: **Automatic Polling**, **Polling Interval**, the five **Polling Interval — …** numbers, **Refresh Data**, and **Last Update**.

## Requirements

- Home Assistant 2024.12.0 or newer (the options flow relies on the base `OptionsFlow` resolving `config_entry`, introduced in HA 2024.12)

## Support

For issues and feature requests, please use the [GitHub issue tracker](https://github.com/ccxdomo/ha-feelloo/issues).
