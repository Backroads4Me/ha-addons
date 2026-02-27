# LibreCoach Documentation

---

## Configuration

All settings are managed under **Settings → Add-ons → LibreCoach → Configuration**.

| Option                                    | Description                                                                                                                                      |
| :---------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------- |
| **Enable Automated Location Updates**     | Syncs your Home Assistant location, timezone, and elevation from a device_tracker (must have GPS).                                               |
| **Enable Micro-Air EasyTouch**            | Enable Bluetooth thermostat integration. Requires your Micro-Air account email and password.                                                     |
| **Enable Victron Energy Integration**     | Enable or disable Victron GX device support. Enabled by default.                                                                                 |
| **Enable Beta Features**                  | Enables experimental features still in development. Use at your own risk.                                                                        |
| **Allow Node-RED Overwrite**              | Only used during first install. Must be enabled to allow LibreCoach to replace existing Node-RED flows. **This will delete your current flows.** |
| **Preserve Node-RED Flow Customizations** | Preserves your customized Node-RED flows during add-on updates. System software and reference files still update normally.                       |
| **Enable Debug Logging**                  | Enables verbose logging for troubleshooting. Leave off during normal use.                                                                        |
| **MQTT User / Password**                  | Credentials used by the Vehicle Bridge and Node-RED to connect to Mosquitto.                                                                     |
| **CAN Interface**                         | The host network interface name for your CAN hardware (default is `can0`).                                                                       |

---

## MQTT

LibreCoach automatically configures MQTT to ensure seamless communication between the Vehicle Bridge and Node-RED.

- A dedicated `librecoach` user is created in Mosquitto on first install.
- Default credentials are pre-configured and can be changed in the Configuration tab if needed.
- MQTT topics (`can/raw`, `can/send`, `can/status`) and CAN bitrate (250 kbps) are fixed.
