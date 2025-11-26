# RV Link - RV Control System

RV Link transforms a Raspberry Pi into a professional RV control center. It integrates your RV's RV-C network directly with Home Assistant allowing you to control and monitor your RV from mobile device or pc.

### The "App" vs. The "Installer"
To make setup easy, RV Link is delivered as a **Home Assistant Add-on**.
* **The RV Link Add-on**: This is the *installer*. You run it once to automatically set up the environment.
* **The RV Link App**: This is the *result*. It is the complete system (Dashboards, Automation, Logic) that controls your rig.

## ✨ Features

-   **🧠 System Orchestrator**: One-click setup. The add-on automatically installs and configures the official Mosquitto Broker, CAN-to-MQTT Bridge, and Node-RED.
-   **🔌 Hardware Bridge**: Connects directly to your CAN hardware (e.g., Waveshare HAT) and bridges RV-C network traffic to Home Assistant.
-   **📦 Project Bundler**: Deploys pre-configured RV Link automation flows to instantly interpret your RV's data.

## ⚠️ Requirements

Before installing, ensure you have a supported CAN interface (e.g., Waveshare CAN HAT) installed on your device.

## 🚀 Installation

### 1. Add the Repository
[![Open your Home Assistant instance and show the add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FBackroads4Me%2Fha-addons)

Or manually add: `https://github.com/Backroads4Me/ha-addons`

### 2. Install & Start
Find **RV Link** in the store and click **Install**, then **Start**.

**The add-on will perform the following "Orchestration" steps:**
1.  Check for **Mosquitto** and install/configure it if missing.
2.  Check for **CAN-to-MQTT Bridge** and install/configure it.
3.  Check for **Node-RED** and install/configure it.
4.  **Deploy** the RV Link automation flows.

## 🛑 Existing Node-RED Users
If you already use Node-RED, RV Link will **PAUSE** to protect your work.
To proceed, you must go to the **Configuration** tab and enable `confirm_nodered_takeover`.
*See the [Documentation](https://github.com/Backroads4Me/ha-addons/blob/main/rv-link/DOCS.md) for full details.*

## 📚 Support
For full configuration options, troubleshooting, and guides, please visit:
* **Official Site:** [rvlink.app](https://rvlink.app)
* **Documentation:** [Read the Docs](DOCS.md)

---

## Support the Project

RV Link is free and open-source. If it's saved you time or money, consider supporting continued development:

[![Support RV Link](https://img.shields.io/badge/Support-RV_Link-ea4aaa?style=for-the-badge&logo=github-sponsors&logoColor=white)](https://github.com/sponsors/Backroads4Me)

Your support helps fund hardware testing, infrastructure costs, and those late-night coding sessions. ☕