<div align="center">

<img src="can-mqtt-bridge-logo.svg" alt="CAN to MQTT Bridge Logo" width="200"/>

# CAN to MQTT Bridge

![GitHub release](https://img.shields.io/github/v/release/Backroads4Me/ha-addons?display_name=tag&sort=semver)
![GitHub issues](https://img.shields.io/github/issues/Backroads4Me/ha-addons)
![License](https://img.shields.io/github/license/Backroads4Me/ha-addons?logo=github&cacheSeconds=60)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-compatible-blue)

A Home Assistant add-on that initializes CAN interfaces and provides bidirectional bridging to MQTT.

</div>

## Author

Created and maintained by Ted Lanham ([@Backroads4Me](https://github.com/Backroads4Me))

Questions or issues? Open an issue on GitHub or contact tedlanham@gmail.com

## Installation

This addon is part of the ha-addons repository. To install:

1. Add the repository to your Home Assistant instance
2. Navigate to Settings > Add-ons > Add-on Store
3. Find "CAN to MQTT Bridge" and click Install

See the [main repository README](../README.md) for detailed installation instructions.

## Configuration

### User Options

The add-on has minimal configuration options:

| Option              | Default          | Description                                      |
| ------------------- | ---------------- | ------------------------------------------------ |
| `can_interface`     | `can0`           | CAN interface name                               |
| `can_bitrate`       | `250000`         | CAN bitrate (125000, 250000, 500000, or 1000000) |
| `mqtt_host`         | `core-mosquitto` | MQTT broker hostname (uses service discovery)    |
| `mqtt_port`         | `1883`           | MQTT broker port                                 |
| `mqtt_user`         | `canbus`         | MQTT broker username (uses service discovery, or configure manually) |
| `mqtt_pass`         | ``               | MQTT broker password (uses service discovery, or configure manually) |
| `mqtt_topic_raw`    | `can/raw`        | Topic for raw CAN frames                         |
| `mqtt_topic_send`   | `can/send`       | Topic to send CAN frames                         |
| `mqtt_topic_status` | `can/status`     | Topic for bridge status                          |
| `debug_logging`     | `false`          | Enable verbose debug logging                     |
| `ssl`               | `false`          | Enable SSL/TLS for MQTT connections              |
| `password`          | ``               | Web interface password protection                |

## Usage

### Monitoring CAN Traffic

Subscribe to see all CAN frames (replace credentials as needed):

```bash
mosquitto_sub -h localhost -t can/raw -u canbus -P ha_can_mqtt_bridge
```

### Sending CAN Messages

Publish CAN frames (replace credentials as needed):

```bash
mosquitto_pub -h localhost -t can/send -u canbus -P ha_can_mqtt_bridge -m "123#DEADBEEF"
```

### Bridge Status

Monitor bridge status (replace credentials as needed):

```bash
mosquitto_sub -h localhost -t can/status -u canbus -P ha_can_mqtt_bridge
```

## CAN Frame Format

The add-on supports two CAN frame formats:

### Standard Format: `ID#DATA`

- `ID`: Hexadecimal CAN identifier (3 or 8 digits)
- `DATA`: Hexadecimal data payload (0-16 hex digits)

Examples:

- `123#DEADBEEF` - Standard ID with 4 bytes of data
- `18FEF017#0102030405060708` - Extended ID with 8 bytes

### Raw Hex Format (Auto-Converted)

For convenience, the add-on automatically converts raw hex strings to the standard format:

- **Input**: `19FEDB9406FFFA05FF00FFFF` (raw hex string)
- **Converted to**: `19FEDB94#06FFFA05FF00FFFF` (ID#DATA format)
- **CAN ID**: First 8 characters become the identifier
- **Data**: Remaining characters become the data payload

This allows seamless integration with systems that send CAN frames as continuous hex strings.

## Troubleshooting

### Common Issues

**CAN interface initialization failed:**

- Verify CAN hardware is connected (USB-CAN adapter, CAN HAT, etc.)
- Check that interface name matches your hardware (usually `can0`)
- Ensure CAN drivers are available in Home Assistant OS
- Try different bitrate settings (125000, 250000, 500000, 1000000)

**MQTT connection issues:**

- Verify Mosquitto add-on is installed and running
- Check if service discovery is working (default setup should auto-configure)
- For manual configuration, verify broker hostname, port, and credentials
- Check MQTT broker logs for connection errors

**Bridge process crashes:**

- Enable debug logging to see detailed error messages
- Check Home Assistant system logs for permission errors
- Verify add-on has necessary privileges (NET_ADMIN)
- Restart the add-on to clear any stuck processes

**CAN messages not being sent:**

- Verify CAN frame format (either `ID#DATA` or raw hex strings)
- Check CAN bus termination and wiring
- Use debug logging to see frame conversion and transmission attempts
- Test with known-good CAN frames first

Enable `debug_logging: true` for verbose output.

## Requirements

- CAN interface hardware (USB-CAN adapter, CAN HAT, etc.)
- MQTT broker (Mosquitto add-on recommended)
