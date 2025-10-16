# CAN to MQTT Bridge

## How It Works

1. The addon initializes your CAN interface with the specified bitrate
2. Establishes connection to MQTT broker (auto-discovered or manually configured)
3. Subscribes to the send topic (`can/send`) to receive CAN frames to transmit
4. Publishes all received CAN frames to the raw topic (`can/raw`)
5. Publishes bridge status to the status topic (`can/status`)
6. Automatically converts between raw hex and standard CAN frame formats

## Prerequisites

Before using this addon, ensure you have:

**Hardware:**

- CAN interface hardware connected to your Home Assistant system:
  - USB-CAN adapter
  - CAN HAT for Raspberry Pi
  - Built-in CAN interface

**Software:**

- MQTT broker installed and running:
  - Mosquitto add-on (recommended - auto-configured)
  - Custom MQTT broker (requires manual configuration)
- Home Assistant OS with CAN driver support

## Configuration

### User Options

The add-on has minimal configuration options:

| Option              | Default          | Description                                                                                                        |
| ------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------ |
| `can_interface`     | `can0`           | CAN interface name                                                                                                 |
| `can_bitrate`       | `250000`         | CAN bitrate (125000, 250000, 500000, or 1000000)                                                                   |
| `mqtt_host`         | `core-mosquitto` | MQTT broker hostname (uses service discovery)                                                                      |
| `mqtt_port`         | `1883`           | MQTT broker port                                                                                                   |
| `mqtt_user`         | `canbus`         | MQTT broker username _(auto-configured via service discovery when using Mosquitto add-on, otherwise set manually)_ |
| `mqtt_pass`         | ``               | MQTT broker password _(auto-configured via service discovery when using Mosquitto add-on, otherwise set manually)_ |
| `mqtt_topic_raw`    | `can/raw`        | Topic for raw CAN frames                                                                                           |
| `mqtt_topic_send`   | `can/send`       | Topic to send CAN frames                                                                                           |
| `mqtt_topic_status` | `can/status`     | Topic for bridge status                                                                                            |
| `debug_logging`     | `false`          | Enable verbose debug logging                                                                                       |
| `ssl`               | `false`          | Enable SSL/TLS for MQTT connections                                                                                |
| `password`          | ``               | Web interface password protection                                                                                  |

### MQTT Credentials Setup

**Using Mosquitto Add-on (Recommended):**

- The add-on automatically discovers MQTT credentials via Home Assistant service discovery
- No manual configuration needed - `mqtt_user` and `mqtt_pass` are auto-populated
- Works with the official [Mosquitto broker add-on](https://github.com/home-assistant/addons/tree/master/mosquitto)

**Using Custom MQTT Broker:**

- Manually configure `mqtt_host`, `mqtt_port`, `mqtt_user`, and `mqtt_pass`
- Ensure your broker has the user account created with appropriate permissions
- The credentials must match what's configured in your MQTT broker

## Usage

### Monitoring CAN Traffic

Subscribe to see all CAN frames (replace with your actual MQTT credentials):

```bash
mosquitto_sub -h localhost -t can/raw -u YOUR_MQTT_USER -P YOUR_MQTT_PASSWORD
```

### Sending CAN Messages

Publish CAN frames (replace with your actual MQTT credentials):

```bash
mosquitto_pub -h localhost -t can/send -u YOUR_MQTT_USER -P YOUR_MQTT_PASSWORD -m "123#DEADBEEF"
```

### Bridge Status

Monitor bridge status (replace with your actual MQTT credentials):

```bash
mosquitto_sub -h localhost -t can/status -u YOUR_MQTT_USER -P YOUR_MQTT_PASSWORD
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

## Status Messages

Published to `can/status` topic:

- `bridge_online` - Bridge is running
- `bridge_offline` - Bridge has stopped

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

## Advanced Usage

### Using with Home Assistant Automations

Create automations that respond to CAN events:

```yaml
automation:
  - alias: "CAN Frame Received"
    trigger:
      platform: mqtt
      topic: can/raw
    action:
      service: notify.persistent_notification
      data:
        message: "CAN frame received: {{ trigger.payload }}"
```

### Sending CAN Frames from Automations

```yaml
automation:
  - alias: "Send CAN Command"
    trigger:
      platform: state
      entity_id: switch.my_switch
      to: "on"
    action:
      service: mqtt.publish
      data:
        topic: can/send
        payload: "123#DEADBEEF"
```

### Filtering CAN Traffic

Use MQTT wildcards and filters in your automations to respond to specific CAN IDs or patterns.

## Additional Resources

**CAN Bus Resources:**

- [SocketCAN Documentation](https://www.kernel.org/doc/html/latest/networking/can.html)
- [CAN Bus Protocol Guide](https://www.csselectronics.com/pages/can-bus-simple-intro-tutorial)

**Need Help?**

- Review troubleshooting section above
- Enable debug logging for detailed error messages
- Check addon logs and Home Assistant system logs
- Visit [Home Assistant Community](https://community.home-assistant.io/) for support
