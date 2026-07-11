### 1.4.1 (Jul 11, 2026)

🐛 Fixes

- corrected AquaHot water temperature and coolant temp display
- fixed AquaHot electric-only operation toggle
- rounded generator coolant temperature to a whole °F

### 1.4.0 (Jul 10, 2026)

✨ New

- Add additional Victron entities:
  - battery time-to-go, consumed amp-hours, and low-voltage alarm
  - solarcharger yield today
  - MultiPlus alarms and shore power connected states
  - MultiPlus Charge Power, Inverter Power and Total Output Power

🛠️ Improvements

- Improve Aqua-Hot 100/200 series support
- Victron sensors now publish friendly labels such as "Inverting" and "Ok"
- Victron energy sensors now work with Home Assistant energy tracking

🐛 Fixes

- Micro-Air fan modes now map manual/cycled high and low values correctly
- Micro-Air heat source presets now better match supported device capabilities

### 1.3.3 (Jun 28, 2026)

🐛 Fixes

- Persist DC_DRIVER based lights dimmer capability

### 1.3.2 (Jun 27, 2026)

🐛 Fixes

- DC dimmer capability now self-heals if it fails to report correctly

### 1.3.0 (Jun 26, 2026)

> ⚠️ **Victron entity naming update:** Entity names were restructured to correctly
> handle multiple devices of the same type. If your dashboards, automations, scripts,
> scenes, or templates reference Victron entity IDs directly, they will need to be
> updated after upgrading.

✨ New

- Hughes Power Watchdog Bluetooth integration
- Generator start/stop via HA switch entities, with run-status and fault sensors

🛠️ Improvements

- Victron entities report unavailable when the GX device is offline instead of showing stale values
- Victron integration correctly handles multiple devices of the same type
- RV-C entities report unavailable when the CAN interface is offline instead of showing stale values
- Enabling or disabling an integration no longer restarts HA just to release Bluetooth devices
- Improved AI dashboard prompts and entity exports

🐛 Fixes

- Dimmer and light state persists correctly across upgrades
- Integration state now survives a Node-RED reinstall
- GeoBridge startup and RV-C network time-sync are more reliable
- BLE monitoring no longer blocks HA startup or shutdown
