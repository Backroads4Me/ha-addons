# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-10-15

### Added

- Initial release of Bluetooth WiFi Setup addon for Home Assistant OS
- BLE server for WiFi configuration via BTBerryWifi mobile app
- NetworkManager integration for WiFi network configuration
- Support for scanning available WiFi networks
- Configurable timeout for automatic shutdown (default: 15 minutes)
- Multiple log levels (debug, info, warning, error)
- Security features:
  - Auto-shutdown after timeout
  - Optional keep-alive mode
  - Optional Bluetooth encryption support (premium feature)
- Hardware validation checks for Bluetooth and WiFi adapters
- Comprehensive user documentation (DOCS.md)
- Multi-architecture support (aarch64, amd64, armv7)
- Configuration options:
  - Bluetooth timeout (1-1440 minutes)
  - Custom BLE device name
  - Log level selection
  - Keep-alive mode toggle
  - Encryption enable/disable
  - Custom password support

### Technical Details

- Based on [Rpi-SetWiFi-viaBluetooth](https://github.com/nksan/Rpi-SetWiFi-viaBluetooth) v2
- Uses NetworkManager via DBus for WiFi configuration
- BlueZ 5.x for Bluetooth Low Energy server
- Python 3 with dbus-python, PyGObject, and cryptography
- Alpine Linux base image

### Known Limitations

- Requires Bluetooth adapter accessible as `/dev/hci0`
- WiFi adapter expected at `wlan0` (warning if not found)
- Requires BTBerryWifi mobile app (iOS/Android)
- Premium app features (encryption) require separate purchase
