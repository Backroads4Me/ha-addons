#### 1.0.7 (Aug 12, 2026)

- **This add-on has moved.** CAN to MQTT Bridge now lives in its own repository:
  <https://github.com/Backroads4Me/ha-addon-can-mqtt-bridge>
- The bridge is unchanged and keeps working. This release only adds a log
  warning and a persistent notification pointing at the new repository.
- This copy will be removed in a future release — please reinstall from the new
  repository.

#### 1.0.6 (Mar 6, 2026)

- Pinned Python dependencies

## [1.0.5] - 2026-02-26

### Changed

- Fixed base image to use addon-base instead of base
- Removed unused SSL and password config options
- Removed redundant packages from Docker image

## [1.0.3] - 2026-01-22

### Changed

- Contact information

## [1.0.2] - 2026-01-11

### Fixed

- Prioritized manual MQTT configuration over Service Discovery. This ensures that when the add-on is orchestrated by another add-on (like RV-Link) which provides specific credentials, those credentials are used effectively.

## [1.0.0] - 2025-10-22

### Changed

- Initial release of CAN to MQTT Bridge
