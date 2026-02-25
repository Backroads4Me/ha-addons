# LibreCoach Documentation

---

## Settings UI (Sidebar)

Most operational settings are managed in the **LibreCoach** sidebar panel — click the LibreCoach icon in the Home Assistant sidebar.

| Setting                            | Description                                                                                  |
| :--------------------------------- | :------------------------------------------------------------------------------------------- |
| **Automated GPS Location Updates** | Syncs your Home Assistant location, timezone, and elevation from a GPS device tracker.       |
| **Victron**                        | Enable or disable Victron GX device support. Enabled by default.                             |
| **Micro-Air EasyTouch**            | Enable Bluetooth thermostat integration. Requires your Micro-Air account email and password. |
| **Beta Testing**                   | Enables experimental features still in development.                                          |

---

## Add-on Configuration Tab

> **Most users will not need to change these settings.**

These settings are found under **Settings → Add-ons → LibreCoach → Configuration**.

| Option                                    | Description                                                                                                                                      |
| :---------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------- |
| **Allow Node-RED Overwrite**              | Only used during first install. Must be enabled to allow LibreCoach to replace existing Node-RED flows. **This will delete your current flows.** |
| **Preserve Node-RED Flow Customizations** | Preserves your customized Node-RED flows during add-on updates. System software and reference files still update normally.                       |
| **Enable Debug Logging**                  | Enables verbose logging for troubleshooting. Leave off during normal use.                                                                        |
| **CAN Interface**                         | The host network interface name for your CAN hardware.                                                                                           |
| **MQTT User / Password**                  | Credentials used by the Vehicle Bridge and Node-RED to connect to Mosquitto.                                                                     |

---

## MQTT

LibreCoach automatically configures MQTT to ensure seamless communication between the Vehicle Bridge and Node-RED.

- A dedicated `librecoach` user is created in Mosquitto on first install.
- Default credentials are pre-configured and can be changed in the Configuration tab if needed.
- MQTT topics (`can/raw`, `can/send`, `can/status`) and CAN bitrate (250 kbps) are fixed.
