# Bluetooth WiFi Setup for Home Assistant OS

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Addon-blue.svg)](https://www.home-assistant.io/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Configure WiFi on headless Home Assistant OS installations via Bluetooth using the BTBerryWifi mobile app.

## Overview

This addon enables WiFi configuration on Home Assistant OS through Bluetooth Low Energy (BLE), solving the problem of reconfiguring WiFi on headless installations (no keyboard/monitor/mouse) when:

- Moving your HA device to a new location
- The current WiFi network becomes unavailable
- Performing initial setup without ethernet
- The web UI is inaccessible due to network issues

## Features

- 🔵 **BLE Server** - Advertises as discoverable Bluetooth device
- 📡 **WiFi Scanning** - Shows all available networks with signal strength
- ⚙️ **NetworkManager Integration** - Configures WiFi using native HAOS networking
- ⏱️ **Auto-shutdown** - Configurable timeout (default: 15 min) for security
- 📱 **Mobile App** - Works with BTBerryWifi for iOS and Android
- 🔒 **Encryption Support** - Optional Bluetooth encryption (premium feature)
- 🔧 **Multi-architecture** - Supports aarch64, amd64, armhf, armv7

## Quick Start

1. Install the addon from the Home Assistant add-on store
2. Configure the addon (see DOCS.md for details)
3. Start the addon
4. Download BTBerryWifi app on your phone (iOS/Android)
5. Connect via Bluetooth and select your WiFi network
6. Enter password and connect

See [DOCS.md](DOCS.md) for detailed setup and usage instructions.

## Requirements

### Hardware
- Raspberry Pi (or compatible) with Bluetooth adapter (`/dev/hci0`)
- WiFi adapter (`wlan0`)
- Home Assistant OS

### Mobile App
- **BTBerryWifi** - Available on iOS App Store and Google Play Store

## Configuration

```yaml
bluetooth_timeout: 15        # Auto-shutdown timer (minutes)
log_level: info             # debug | info | warning | error
device_name: BTBerryWifi    # BLE advertised name
keep_alive: false           # Disable auto-shutdown (security risk)
encryption_enabled: false   # Enable BLE encryption (premium)
password: ""                # Optional encryption password
```

## Security Notice

⚠️ **Important**: This addon runs with elevated privileges and exposes WiFi configuration via Bluetooth.

**Best practices:**
- Use the auto-shutdown timeout (don't enable `keep_alive`)
- Start manually only when needed
- Stop immediately after configuring WiFi
- Monitor addon logs for unexpected access

See [DOCS.md](DOCS.md#security-considerations) for complete security information.

## Documentation

- [DOCS.md](DOCS.md) - Complete user documentation
- [CHANGELOG.md](CHANGELOG.md) - Version history
- [ICONS.md](ICONS.md) - Icon creation guide

## Attribution

This addon is based on the excellent [Rpi-SetWiFi-viaBluetooth](https://github.com/nksan/Rpi-SetWiFi-viaBluetooth) project by nksan.

The BTBerryWifi mobile app is developed by [BluePie Apps](https://bluepieapps.com/).

## Support

- **Addon issues**: Open an issue on GitHub
- **BTBerryWifi app**: Contact BluePie Apps
- **Home Assistant**: Visit [Home Assistant Community](https://community.home-assistant.io/)

## License

See [LICENSE](LICENSE) file for details.

## Development

### Repository Structure

```
bluetooth-wifi-setup/
├── config.yaml              # Addon configuration
├── Dockerfile              # Container definition
├── build.yaml              # Multi-arch build config
├── DOCS.md                 # User documentation
├── CHANGELOG.md            # Version history
├── README.md               # This file
├── ICONS.md                # Icon creation guide
└── rootfs/
    └── usr/local/btwifiset/
        ├── btwifiset.py    # Main Python BLE server
        ├── requirements.txt # Python dependencies
        └── run.sh          # Startup script
```

### Building Locally

This addon uses Home Assistant's build system. To test locally:

1. Clone this repository to your Home Assistant `addons` directory
2. Install the addon from the Local Add-ons section
3. Configure and start

### Contributing

Contributions welcome! Please:
- Follow existing code style
- Test on actual hardware before submitting PRs
- Update documentation for new features
- Add entries to CHANGELOG.md

---

**Tested on**: Raspberry Pi 5 with Home Assistant OS
