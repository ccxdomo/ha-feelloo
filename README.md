# Feelloo Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Custom integration for [Feelloo](https://feelloo.com) cat trackers in Home Assistant.

## Features

- Track your cats' location in real-time
- Monitor battery level and charging status
- View activity status (sleep, calm, active)
- Ring your cat's tag to locate them
- Presence detection (home / away)
- Extended search mode status

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
- **Activity** — current activity (sleep / calm / active)
- **Extended Search Expiration** — when extended search expires

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
