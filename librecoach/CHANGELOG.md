## [1.0.2] - 2026-02-14

### Added

- Option to disable Victron integration

## [1.0.1] - 2026-02-13

### Added

- Dimmable control for lights

## [1.0.0] - 2026-02-13

### Added

- Light dimming capability
- Victron GX device support

## [0.9.17] - 2026-02-02

### Changed

- Switched to bundled flows_cred.json for MQTT credentials instead of runtime injection
- Fixed credential_secret to "librecoach" for consistent flows_cred.json decryption
- Backup existing Node-RED credential_secret to share drive when taking over

## [0.9.16] - 2026-02-02

### Changed

- Simplified MQTT credential injection using jq in init script

### Fixed

- Fixed duplicate "MQTT integration is configured" log message

## [0.9.15] - 2026-02-02

### Changed

- Simplified MQTT credential handling using Node-RED environment variable substitution
- Added custom settings.js with fixed credentialSecret for consistent credential encryption

## [0.9.14] - 2026-02-01

### Fixed

- Converted Node-RED init script to a file

## [0.9.8] - 2026-01-24

### Fixed

- Docker build clone repository

## [0.9.7] - 2026-01-24

### Fixed

- Fixed jq parse error when fetching CAN-MQTT Bridge logs
- Removed premature MQTT service discovery that caused "Unable to access the API" error
- Fixed CAN-MQTT Bridge MQTT connection failure by using hassio gateway IP instead of hostname
- Improved Node-RED API error logging to show actual failure reason

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
