# Bluetooth WiFi Setup for Home Assistant OS

Configure WiFi on headless Home Assistant OS installations via Bluetooth using the BTBerryWifi mobile app.

## Author

Created and maintained by Ted Lanham ([@Backroads4Me](https://github.com/Backroads4Me))

Questions or issues? Open an issue on GitHub or contact tedlanham@gmail.com

## What It Does

This addon solves the problem of configuring WiFi on headless Home Assistant installations (no keyboard/monitor/mouse) by providing a Bluetooth interface for WiFi setup. Perfect for:

- Moving your HA device to a new location with different WiFi
- Recovery when the current WiFi network becomes unavailable
- Initial setup without ethernet access

Uses the BTBerryWifi mobile app (iOS/Android) to scan networks, enter credentials, and configure WiFi through Bluetooth Low Energy.

## Installation

To add this repository to your Home Assistant instance, click the button below:

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FBackroads4Me%2Fha-addons)

Then install "Bluetooth WiFi Setup" from the add-on store.

## Quick Start

1. Install the addon from the Home Assistant add-on store
2. Start the addon (default configuration works for most setups)
3. Download BTBerryWifi app on your phone (iOS App Store or Google Play)
4. Open the app and scan for Bluetooth devices
5. Connect to `BTBerryWifi-{hostname}`
6. Select your WiFi network and enter the password
7. Wait for successful connection confirmation

📖 **See [DOCS.md](DOCS.md) for complete configuration and usage documentation**

## Requirements

**Hardware:**

- Raspberry Pi (or compatible) with Bluetooth adapter
- WiFi adapter
- Home Assistant OS

**Software:**

- BTBerryWifi mobile app (free on iOS/Android)

**Tested on:** Raspberry Pi 5 with Home Assistant OS

## Security Notice

⚠️ This addon runs with elevated privileges and exposes WiFi configuration via Bluetooth.

**Best practices:** Use the auto-shutdown timer, start only when needed, stop immediately after configuration.

See [DOCS.md](DOCS.md#security-considerations) for complete security information.

## Attribution

Based on the [Rpi-SetWiFi-viaBluetooth](https://github.com/nksan/Rpi-SetWiFi-viaBluetooth) project by nksan.

BTBerryWifi mobile app developed by [BluePie Apps](https://bluepieapps.com/).

### Contributing

Contributions welcome! Please:

- Test on actual hardware before submitting PRs
- Update DOCS.md for configuration changes
- Add entries to CHANGELOG.md
- Follow existing code style

## Support

- **Addon issues**: [Open an issue on GitHub](https://github.com/Backroads4Me/ha-addons/issues)
- **BTBerryWifi app**: Contact BluePie Apps
- **Home Assistant**: Visit [Home Assistant Community](https://community.home-assistant.io/)

## License

MIT License

Copyright (c) 2025 Ted Lanham
Copyright (c) nksan (btwifiset.py - [Rpi-SetWiFi-viaBluetooth](https://github.com/nksan/Rpi-SetWiFi-viaBluetooth))

See [LICENSE](LICENSE) file for complete license text and details.
