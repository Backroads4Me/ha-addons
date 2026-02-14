# LibreCoach - RV Control System

LibreCoach transforms a Raspberry Pi into a professional RV control center. It integrates your RV's RV-C network directly with Home Assistant allowing you to control and monitor your RV from mobile device.

### The "App" vs. The "Installer"

To make setup easy, LibreCoach is delivered as a **Home Assistant Add-on**.

- **The LibreCoach Add-on**: This is the _installer_. You run it once to automatically set up the environment.
- **The LibreCoach App**: This is the _result_. It is the complete system (Dashboards, Automation, Logic) that controls your rig.

## Features

- **System Orchestrator**: One-click setup. The add-on automatically installs and configures the official Mosquitto Broker, CAN-to-MQTT Bridge, and Node-RED.
- **Hardware Bridge**: Connects directly to your CAN hardware (e.g., Waveshare HAT) and bridges RV-C network traffic to Home Assistant.
- **Project Bundler**: Deploys pre-configured LibreCoach automation flows to instantly interpret your RV's data.

## Requirements

Before installing, ensure you have a supported CAN interface (e.g., Waveshare CAN HAT) installed on your device.

## Installation

### 1. Add the Repository

[![Open your Home Assistant instance and show the add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FBackroads4Me%2Fha-addons)

Or manually add: `https://github.com/backroads4me/ha-addons`

### 2. Install & Start

Find **LibreCoach** in the store and click **Install**, then **Start**.

**The add-on will perform the following "Orchestration" steps:**

1.  Check for **Mosquitto** and install/configure it if missing.
2.  Check for **CAN-to-MQTT Bridge** and install/configure it.
3.  Check for **Node-RED** and install/configure it.
4.  **Deploy** the LibreCoach automation flows.

## Existing Node-RED Users

If you already use Node-RED, LibreCoach will **PAUSE** to protect your work.
To proceed, you must go to the **Configuration** tab and enable `confirm_nodered_takeover`.
_See the [Documentation](https://github.com/backroads4me/ha-addons/blob/main/librecoach/DOCS.md) for full details._

## Support

For full configuration options, troubleshooting, and guides, please visit:

- **Official Site:** [LibreCoach.com](https://librecoach.com)

---

## License

This add-on is licensed under the **GNU General Public License v3.0 (GPL-3.0-only)**.
Contributions are accepted under the CLA, which grants the project owner the right to offer
alternative licensing terms (including commercial licensing) outside this repository.

---

## Contributing

Contributions to the LibreCoach add-on require signing the CLA. See [CONTRIBUTING.md](./CONTRIBUTING.md).

---

## Support LibreCoach

LibreCoach is free and open source.
If it's useful to you, you can support its development in either of these ways:

[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-GitHub-EA4AAA?logo=github-sponsors&logoColor=white)](https://github.com/sponsors/Backroads4Me)
[![Buy Me a Coffee](https://img.shields.io/badge/Support-Buy%20Me%20a%20Coffee-FFDD00?logo=buy-me-a-coffee&logoColor=000000)](https://buymeacoffee.com/Backroads4Me)
