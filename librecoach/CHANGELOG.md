## [0.9.5] - 2026-01-24

### Fixed

- Fixed jq parse error when fetching CAN-MQTT Bridge logs
- Removed premature MQTT service discovery that caused "Unable to access the API" error

## [0.9.1] - 2026-01-22

### Changed

- Contact information

## [0.9.0] - 2026-01-16

### Changed

- Rebranding from RV Link to LibreCoach

## [0.8.57] - 2026-01-14

### Changed

- Addon no longer auto-starts on boot

## [0.8.56] - 2026-01-14

### Fixed

- Fixed jq error on subsequent startups when Node-RED users config is null

## [0.8.54] - 2026-01-11

### Fixed

- Increased delay after Mosquitto restart to allow service discovery credentials to fully update
- CAN-MQTT Bridge now receives correct credentials on first start without manual Mosquitto restart

## [0.8.53] - 2026-01-11

### Changed

- Updated MQTT integration setup instructions (click ADD instead of CONFIGURE, click START instead of RESTART)
- Addon now stays running after installation to keep logo colored in UI
- Graceful shutdown handling for clean updates and restarts

## [0.8.52] - 2026-01-11

### Added

- MQTT integration prerequisite check before installation
- Persistent notification in HA UI when MQTT integration setup required
- Enhanced error detection to surface CAN-MQTT Bridge failures in LibreCoach logs
- Installation summary showing status of all components
- Diagnostic MQTT credential logging for troubleshooting

### Fixed

- CAN-MQTT Bridge MQTT authentication failures now properly reported in LibreCoach logs
- Mosquitto restart triggers MQTT integration discovery for new installations

### Changed

- Installation now pauses if MQTT integration not configured, with clear setup instructions

## [0.8.51] - 2026-01-09

### Fixed

- Corrected CAN to MQTT addon slug

## [0.8.5] - 2025-11-27

### Fixed

- Fixed MQTT topic fields being blank in CAN-MQTT Bridge by adding missing schema entries

## [0.8.3] - 2025-11-25

### Changed

- First release
