## [0.1.8] - 2025-10-16

### Changed

- Removed logging noise

## [0.1.7] - 2025-10-16

### Fixed

- Fixed Python 3.12+ SyntaxWarnings in btwifiset.py by converting regex patterns to raw strings
- Eliminated 6 invalid escape sequence warnings in regex patterns

### Changed

- Updated regex patterns to use raw strings (r'...') for proper Python 3.12+ compatibility
- Modified lines: 398, 459, 1065, 1545, 1557, 1620 in btwifiset.py

## [0.1.4] - 2025-10-16

### Fixed

- Re-added `networkmanager` and `networkmanager-wifi` packages to Dockerfile (required for `nmcli` CLI tool)
- Python code requires `nmcli` command to configure WiFi networks
- `nmcli` client connects to host's NetworkManager via D-Bus (`host_dbus: true`)

### Changed

- Updated Dockerfile comment to clarify NetworkManager client usage
- Kept improved D-Bus accessibility check in run.sh

## [0.1.3] - 2025-10-16

### Fixed

- Fixed NetworkManager detection to use D-Bus API instead of `nmcli` command
- NetworkManager is accessed via host D-Bus (`host_dbus: true`), not as an installed binary

### Changed

- Removed unnecessary `networkmanager` and `networkmanager-wifi` packages from Dockerfile
- Updated NetworkManager check to verify D-Bus accessibility
- Improved error messages for NetworkManager troubleshooting

## [0.1.2] - 2025-10-16

### Fixed

- Fixed Bluetooth adapter detection to use sysfs (`/sys/class/bluetooth/`) instead of device nodes (`/dev/hci0`)
- Removed unnecessary device mapping from config.yaml - addon now uses BlueZ D-Bus API properly

### Changed

- Updated documentation to reflect proper Bluetooth detection method
- Improved error messages for Bluetooth adapter troubleshooting

## [0.1.1] - 2025-10-16

### Changed

- Configured GitHub Container Registry for pre-built images
- Improved documentation formatting with centered header

### Added

- Automated release workflow for GitHub Releases

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

- Requires Bluetooth adapter accessible via BlueZ D-Bus API
- WiFi adapter expected at `wlan0` (warning if not found)
- Requires BTBerryWifi mobile app (iOS/Android)
- Premium app features (encryption) require separate purchase
