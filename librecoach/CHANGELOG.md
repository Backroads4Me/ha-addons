### 1.2.7 (Feb 28, 2026)

**⚠️ Check your tank names ⚠️** Black and gray tank labels were previoulsy swapped in some installations and now corrected.

- Fixed tank black/gray sensor assignment
- Added additional tank support

### 1.2.0 (Feb 26, 2026)

- Added GeoBridge for automatic home location tracking
- Added MQTT-driven BLE lifecycle (no HA restart needed for enable/disable)
- Added autonomous cleanup (Suicide Pattern) for uninstall scenarios
- Added weekly scheduled Docker rebuild for base image security patches
- Fixed base image mismatch (addon-base instead of base)
- Fixed preserve-mode transition when toggling prevent_flow_updates
- Removed mqtt_host, mqtt_port, mqtt_topic, and can_bitrate config options
- Removed host_dbus dependency (BLE now uses HA integration)

### 1.1.10 (Feb 21, 2026)

- Refined Micro-Air integration

### 1.1.8 (Feb 20, 2026)

- Added Victron write capability
- Fixed integration hash check

### 1.1.7 (Feb 20, 2026)

- Moved Bluetooth from add-on to native HA integration for improved reliability
- Removed standalone bridge and dbus dependency

### 1.1.6 (Feb 19, 2026)

- CAN-to-MQTT Bridge add-on no longer required (auto-disabled)
- Added Micro-Air EasyTouch Bluetooth integration
- Victron integration can now be disabled
- Fixed RV-C polling and watchdog takeover issue

### 1.0.3 (Feb 15, 2026)

- Start add-on once after update to enable auto-start
- Added Template Export / Import
- Add-on stays running for automatic updates

### 1.0.0 – 1.0.2 (Feb 13–14, 2026)

- Added light dimming support
- Added Victron GX support
- Option to disable Victron

### 0.9.x (Jan–Feb 2026)

- Major MQTT credential handling overhaul
- Bundled Node-RED credentials system
- Multiple CAN-MQTT bridge connection and logging fixes

### 0.9.0 (Jan 16, 2026)

- Rebranded from RV Link to LibreCoach

### 0.8.x (Jan 2026)

- Added MQTT setup validation and diagnostics
- Multiple CAN-MQTT and Mosquitto reliability fixes
- Initial public releases
