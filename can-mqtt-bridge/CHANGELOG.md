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
