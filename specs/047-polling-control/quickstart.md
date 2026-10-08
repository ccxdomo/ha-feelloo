# Quickstart 047 — Polling Control (owner guide)

How to use the polling-control features once release **1.8.0** of the Feelloo integration is installed (HACS update or manual copy + restart).

## What you get

On the new **Feelloo** hub device (Settings → Devices & Services → Feelloo):

| Entity | What it does |
|--------|--------------|
| **Automatic Polling** (switch, config) | ON = the main cats poller runs (default). OFF = no automatic polling at all (only manual fetches). |
| **Polling Interval** (number, config) | Main poller cadence in minutes, 1 to 1440 (24 h). Default 5. |
| **Refresh Data** (button) | One press = fetch everything now (all coordinators), regardless of polling state. |
| **Last Update** (sensor, diagnostic) | Timestamp of the last successful cats fetch; freezes when polling is off so you can see the data age. Attributes show current polling settings. |

## Everyday use

**Stop the background polling**
- Toggle **Automatic Polling** off, or Settings → Devices & Services → Feelloo → Configure → turn "Enable automatic polling" off.
- What happens: after at most one final fetch, the integration stops calling the Feelloo cloud on its own. Your entities keep their **last known values** — nothing goes "unavailable" just because polling is off. The **Last Update** sensor freezes, showing how old the data is.
- Token refresh (internal authentication housekeeping) keeps running so on-demand fetches still work.

**Fetch on demand**
- Press **Refresh Data** — works with polling on or off. It refreshes the cats data first, then activity, weekly/monthly activity, territory and session data. Automatable: `button.feelloo_refresh_data`.

**Change the cadence**
- Set **Polling Interval** (e.g. 10 for every 10 minutes). Applies within ~10 seconds — no restart needed. Works while polling is on; if polling is off, the value is stored and used when you re-enable.

**Automate it (examples)**

```yaml
automation:
  - alias: "No polling at night"
    trigger:
      - platform: time
        at: "23:00:00"
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.feelloo_automatic_polling
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

## Good to know

- **New installs and existing installs behave exactly as before** until you change a setting (polling on, every 5 minutes).
- **Petite Souris + polling off**: turning Petite Souris ON while polling is off **temporarily re-enables polling at 1 minute** so the mode actually tracks your cat. When it ends (switch off or expiry), your settings are restored automatically — polling goes back to disabled if that is your preference. Changing any polling setting manually during the mode wins: the temporary boost stops (and with polling left enabled, 1-minute tracking continues via the fast-polling timer). While the boost runs, the **Automatic Polling** switch visibly reads ON — labeled *(Petite Souris)* with a fast-clock icon, and its attributes show both your saved preference and the effective 1-minute state — so a control that looks disabled while data flows can no longer happen. The **Last Update** sensor's `petite_souris_override` attribute confirms the override at any time.
- **Genuine failures still show**: if a fetch actually fails (network down, bad credentials), coordinator-gated entities (binary sensors, device tracker, duration number) become unavailable as usual — that's correct behavior and is preserved.
- **Credentials**: the options flow no longer requires typing your password just to change polling settings — leave the password blank to keep current credentials. Entering a new email/password still validates and applies them as before.
- **Multiple accounts**: each configured account gets its own set of the four entities.

## Where the settings live

Persisted in the config entry's options (survives restarts, backup/restore). Defaults: enabled, 5 minutes. Range: 1–1440 minutes.