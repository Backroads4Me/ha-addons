# LibreCoach Documentation

## Concept: The "System" vs. The "Add-on"

It is important to distinguish between **LibreCoach (The System)** and this **Add-on**.

### 1. The LibreCoach System

This is the "App" and final product. It is a collection of services (Mosquitto, Node-RED, and the CAN Bridge) that run in the background to control your RV.

- **Status:** Always Running.
- **Control:** Via Home Assistant Dashboards and highly customizable.
- **Composition:** The unified system formed by the sum of all installed components.

### 2. This LibreCoach Add-on

This is the "Orchestrator." It is a utility that ensures the System is installed and configured.

- **Status:** Runs continuously in the background.
- **Function:** It installs missing components, updates Node-RED flows, and applies configurations. After completing its work, it stays running so that updates are applied automatically.

> **Normal Behavior:** After starting, this add-on will perform its setup checks and then remain running in the background. The addon staying "running" is normal — the actual work is done by Mosquitto, Node-RED, and CAN Bridge. The addon stays alive so that HAOS can automatically restart it when updates are applied.

## Updating LibreCoach

Updates are applied automatically. When HAOS downloads a new version, it restarts the addon, which re-runs the orchestrator with the updated code. No manual action is required.

## Configuration

### Main Settings

| Option          | Type    | Default  | Description                                                                              |
| :-------------- | :------ | :------- | :--------------------------------------------------------------------------------------- |
| `can_interface` | String  | `can0`   | The host network interface name for your CAN hardware (e.g., `can0`, `vcan0`).           |
| `can_bitrate`   | List    | `250000` | The speed of your RV-C network. Standard is 250k. Options: `125k`, `250k`, `500k`, `1M`. |
| `debug_logging` | Boolean | `false`  | Enables verbose logging of API calls and setup steps. Use only for troubleshooting.      |

### Safety Settings

| Option                     | Type    | Default | Description                                                                                                                                    |
| :------------------------- | :------ | :------ | :--------------------------------------------------------------------------------------------------------------------------------------------- |
| `Allow Node-RED Overwrite` | Boolean | `false` | **DANGER:** Required if Node-RED is already installed. Setting this to `true` allows LibreCoach to **overwrite** your existing Node-RED flows. |

### Automated Settings

LibreCoach automatically handles MQTT credentials to ensure seamless communication between the bridge and the automation flows.

- **MQTT Topics**: Defaults to `can/raw`, `can/send`, and `can/status`.
- **Authentication**: LibreCoach creates a dedicated `librecoach` user in Mosquitto automatically.

## Hardware Setup

LibreCoach requires a physical connection to your RV's CAN bus.

1.  Install your CAN HAT/Adapter (e.g., Waveshare CAN HAT) on your Raspberry Pi.
2.  Ensure the interface is active in the host OS (usually `can0`).
3.  **Note:** The _CAN-MQTT Bridge_ add-on will fail to start if the hardware is missing, but the LibreCoach Orchestrator will still successfully deploy the rest of the software stack (useful for testing).

## Troubleshooting

### "Installation aborted to protect existing flows"

**Reason:** You have Node-RED installed, and LibreCoach is refusing to delete your work.
**Fix:**

1.  Backup your existing flows if you want to keep them.
2.  Go to the **Configuration** tab.
3.  Toggle **Allow Node-RED Overwrite** to true.
4.  Scroll down and click 'Save'

### Using Node-RED Independently

If you wish to stop LibreCoach from managing Node-RED:

1.  Uninstall the **LibreCoach** add-on.
2.  Go to the **Node-RED** add-on configuration tab.
3.  Just above the "Show unused optional configuration options' toggle you should see:

    `bash /share/.librecoach/init-nodered.sh` &#x2716;

4.  Click the &#x2716; to delete the entry and then click save.
