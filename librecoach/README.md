# LibreCoach - RV Control System

LibreCoach transforms a Raspberry Pi into a professional RV control center. It integrates your RV's RV-C network directly with Home Assistant, allowing you to control and monitor your RV from any device.

## Features

- One-click setup — automatically installs and configures Mosquitto Broker and Node-RED.
- Connects directly to your CAN hardware (e.g., Waveshare HAT) and bridges RV-C network traffic to Home Assistant.
- Deploys pre-configured automation flows to instantly interpret your RV's data.

## Installation

### 1. Add the Repository

[![Open your Home Assistant instance and show the add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FBackroads4Me%2Fha-addons)

Or manually add: `https://github.com/backroads4me/ha-addons`

### 2. Install & Start

Find **LibreCoach** in the app store and click **Install**, then **Start**.

**The app will perform the following orchestration steps:**

1.  Check for **Mosquitto MQTT broker** and install/configure it if missing.
2.  Start the internal **RV-C and Location Tracking Bridges**.
3.  Check for **Node-RED** and install/configure it.
4.  **Deploy** the LibreCoach automation flows.

## Existing Node-RED Users

If you already use Node-RED, LibreCoach will **PAUSE** to protect your work.
To proceed, go to the **Configuration** tab and enable `Allow Node-RED Overwrite`.
See the [Documentation](https://github.com/backroads4me/ha-addons/blob/main/librecoach/DOCS.md) for full details.

## Support

For configuration options, advanced features, and guides, visit [LibreCoach.com](https://librecoach.com).

---

## License

This app is licensed under the **GNU General Public License v3.0 (GPL-3.0-only)**.
Contributions are accepted under the CLA, which grants the project owner the right to offer
alternative licensing terms (including commercial licensing) outside this repository.

---

## Contributing

Contributions to LibreCoach require signing the CLA. See [CONTRIBUTING.md](./CONTRIBUTING.md).

---

## Support LibreCoach

LibreCoach is free and open source.
If it's useful to you, you can support its development in either of these ways:

[![Star Repository](https://img.shields.io/badge/%E2%AD%90%20Star%20this%20Repo-GitHub-lightgrey?logo=github&logoColor=black)](https://github.com/Backroads4Me/ha-addons)
[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-GitHub-EA4AAA?logo=github-sponsors&logoColor=white)](https://github.com/sponsors/Backroads4Me)
[![Buy Me a Coffee](https://img.shields.io/badge/Support-Buy%20Me%20a%20Coffee-FFDD00?logo=buy-me-a-coffee&logoColor=000000)](https://buymeacoffee.com/Backroads4Me)
