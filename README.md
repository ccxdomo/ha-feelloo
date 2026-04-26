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

The integration uses **three separate DataUpdateCoordinators** for optimal polling:

| Coordinator | Endpoint | Interval |
|------------|----------|----------|
| Main | `/users/cats` | 5 minutes |
| Activity | `/users/cats/{cat_id}/activity?period_type=day` | 15 minutes |
| Territory | `/users/cats/{cat_id}/territory/paths` | 15 minutes |

All coordinators share a single Firebase auth manager with automatic token refresh every 50 minutes.

## Entities

For each detected cat, the following entities are created:

### Binary Sensors
- **Home** — whether the cat is at home
- **In Range** — whether the tag is in Bluetooth range
- **Gateway Online** — whether the gateway is connected
- **Charging** — whether the tag is charging
- **Is Ringing** — whether the tag is currently ringing
- **Battery Low** — low battery warning
- **Extended Search** — whether extended search mode is enabled

### Sensors
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
- **Tracker** — GPS location on the map

### Button
- **Ring** — trigger the tag ringtone (only if `can_ring` is true)

## Device Registry

Each cat is registered as a device with:
- Name: the cat's profile name
- Manufacturer: Feelloo
- Model: Cat Tracker

## Requirements

- Home Assistant 2024.1.0 or newer

## Support

For issues and feature requests, please use the [GitHub issue tracker](https://github.com/ccxdomo/ha-feelloo/issues).
