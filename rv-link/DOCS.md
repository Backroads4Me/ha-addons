# RV Link Documentation

## Concept: The "System" vs. The "Add-on"

It is important to distinguish between **RV Link (The System)** and this **Add-on**.

### 1. The RV Link System 🚐
This is the "App" and final product. It is a collection of services (Mosquitto, Node-RED, and the CAN Bridge) that run in the background to control your RV.
* **Status:** Always Running.
* **Control:** Via Home Assistant Dashboards and highly customizable.
* **Composition:** The unified system formed by the sum of all installed components.

### 2. This RV Link Add-on 🛠️
This is the "Orchestrator." It is a utility that ensures the System is installed and configured.
* **Status:** Runs on boot, then **STOPS**.
* **Function:** It installs missing components, updates Node-RED flows, and applies configurations.

> **✅ Normal Behavior:** When you start this add-on, it will perform its checks and then turn itself off. **This does not mean your RV control has stopped.** It simply means the Orchestrator has finished its job.

## 🔧 Configuration

### Main Settings

| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `can_interface` | String | `can0` | The host network interface name for your CAN hardware (e.g., `can0`, `vcan0`). |
| `can_bitrate` | List | `250000` | The speed of your RV-C network. Standard is 250k. Options: `125k`, `250k`, `500k`, `1M`. |
| `debug_logging` | Boolean | `false` | Enables verbose logging of API calls and setup steps. Use only for troubleshooting. |

### Safety Settings

| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `confirm_nodered_takeover` | Boolean | `false` | **⚠️ DANGER:** Required if Node-RED is already installed. Setting this to `true` allows RV Link to **overwrite** your existing Node-RED flows. |

### Automated Settings
RV Link automatically handles MQTT credentials to ensure seamless communication between the bridge and the automation flows.
* **MQTT Topics**: Defaults to `can/raw`, `can/send`, and `can/status`.
* **Authentication**: RV Link creates a dedicated `rvlink` user in Mosquitto automatically.

## 🔌 Hardware Setup
RV Link requires a physical connection to your RV's CAN bus.
1.  Install your CAN HAT/Adapter (e.g., Waveshare CAN HAT) on your Raspberry Pi.
2.  Ensure the interface is active in the host OS (usually `can0`).
3.  **Note:** The *CAN-MQTT Bridge* add-on will fail to start if the hardware is missing, but the RV Link Orchestrator will still successfully deploy the rest of the software stack (useful for testing).

## 🛠️ Troubleshooting

### "Installation aborted to protect existing flows"
**Reason:** You have Node-RED installed, and RV Link is refusing to delete your work.
**Fix:**
1.  Backup your existing flows if you want to keep them.
2.  Go to the **Configuration** tab.
3.  Toggle **Allow Node-RED Overwrite** (`confirm_nodered_takeover`) to on.
4.  Restart RV Link.

### "MQTT broker not responding"
**Reason:** The Mosquitto add-on is not running or is unhealthy.
**Fix:** Check the "Mosquitto broker" add-on logs. Ensure it is started. RV Link cannot proceed without a working broker.

### Add-on stops immediately after "RV Link System Fully Operational"
**Reason:** This is designed behavior. The Orchestrator has finished its job.
**Fix:** No fix needed. Check the "Overview" dashboard or the Node-RED interface to verify your system is working.

### Using Node-RED Independently
If you wish to stop RV Link from managing Node-RED:
1.  Uninstall the **RV Link** add-on.
2.  Go to the **Node-RED** add-on configuration.
3.  Edit the configuration in YAML and remove the `init_commands` that RV Link injected.