# CAN to MQTT Bridge

Bidirectional bridge between CAN bus interfaces and MQTT for Home Assistant.

## Author

Created and maintained by Ted Lanham ([@Backroads4Me](https://github.com/Backroads4Me))

Questions or issues? Open an issue on GitHub or contact tedlanham@gmail.com

## What It Does

This addon initializes CAN interfaces on your Home Assistant system and bridges CAN bus traffic to MQTT topics, enabling:

- Monitor CAN bus traffic in real-time via MQTT
- Send CAN frames through MQTT publish
- Integrate CAN devices with Home Assistant automations
- Log and analyze CAN communications
- Support for standard and extended CAN frame formats

Uses Home Assistant's Mosquitto broker (or custom MQTT broker) for seamless integration.

## Installation

To add this repository to your Home Assistant instance, click the button below:

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FBackroads4Me%2Fha-addons)

Then install "CAN to MQTT Bridge" from the add-on store.

## Quick Start

1. Install the addon from the Home Assistant add-on store
2. Connect your CAN hardware (USB-CAN adapter or CAN HAT)
3. Start the addon (default configuration auto-detects Mosquitto broker)
4. Subscribe to `can/raw` topic to see CAN traffic
5. Publish to `can/send` topic to send CAN frames

📖 **See [DOCS.md](DOCS.md) for complete configuration and usage documentation**

## Requirements

**Hardware:**

- CAN interface hardware (USB-CAN adapter, CAN HAT, etc.)
- Compatible with socketcan-supported devices

**Software:**

- MQTT broker (Mosquitto add-on recommended)
- Home Assistant OS with CAN driver support

## CAN Frame Formats

The addon supports both standard and raw formats:

**Standard:** `123#DEADBEEF` (ID#DATA format)
**Raw Hex:** `19FEDB9406FFFA05FF00FFFF` (auto-converted)

See [DOCS.md](DOCS.md#can-frame-format) for complete format details.

### Contributing

Contributions welcome! Please:

- Test with actual CAN hardware before submitting PRs
- Update DOCS.md for configuration changes
- Add entries to CHANGELOG.md
- Follow existing code style

## Support

- **Addon issues**: [Open an issue on GitHub](https://github.com/Backroads4Me/ha-addons/issues)
- **CAN hardware**: Consult your hardware manufacturer's documentation
- **Home Assistant**: Visit [Home Assistant Community](https://community.home-assistant.io/)

## License

MIT License

Copyright (c) 2025 Ted Lanham

See [LICENSE](LICENSE) file for complete license text.
