# Bluetooth WiFi Setup

Configure WiFi on your Home Assistant OS installation via Bluetooth using the BTBerryWifi mobile app.

## Overview

This addon enables you to configure WiFi network settings on headless Home Assistant OS installations (no keyboard/monitor) using Bluetooth Low Energy (BLE) and a mobile app. This is particularly useful when:

- Moving your Home Assistant device to a new location with different WiFi
- The current WiFi network becomes unavailable
- Initial setup without ethernet access
- The web UI is inaccessible due to network issues

## How It Works

1. Start this addon on your Home Assistant system
2. The addon creates a Bluetooth Low Energy (BLE) server that advertises as `BTBerryWifi-{hostname}`
3. Connect to it using the BTBerryWifi mobile app (iOS/Android)
4. The app scans for available WiFi networks
5. Select a network and enter the password
6. The addon configures NetworkManager and connects to the network
7. After a configurable timeout (default: 15 minutes), the addon automatically shuts down

## Requirements

### Hardware

- Raspberry Pi (or compatible) with Bluetooth adapter (accessible as `/dev/hci0`)
- WiFi adapter (accessible as `wlan0`)
- Home Assistant OS installed and running

**Tested Hardware:**

- Raspberry Pi 5

### Mobile App

Download the **BTBerryWifi** app:

- **iOS**: Search "BTBerryWifi" on Apple App Store
- **Android**: Search "BTBerryWifi" on Google Play Store

## Installation

1. Add this repository to your Home Assistant Supervisor add-on stores (if not already available in the official store)
2. Install the "Bluetooth WiFi Setup" addon
3. Configure the addon (see Configuration section below)
4. Start the addon

## Configuration

```yaml
bluetooth_timeout: 15 # Minutes before auto-shutdown (1-1440)
log_level: info # Logging level: debug, info, warning, error
device_name: BTBerryWifi # BLE advertised name
keep_alive: false # Keep addon running indefinitely (security risk!)
encryption_enabled: false # Enable Bluetooth encryption (premium feature)
password: "" # Password for encryption/lock feature (optional)
```

### Configuration Options Explained

#### `bluetooth_timeout`

- **Default**: `15` (minutes)
- **Range**: 1-1440 (1 minute to 24 hours)
- **Description**: How long the BLE server stays active before automatically shutting down. This limits security exposure.

#### `log_level`

- **Default**: `info`
- **Options**: `debug`, `info`, `warning`, `error`
- **Description**: Controls the verbosity of addon logs. Use `debug` for troubleshooting.

#### `device_name`

- **Default**: `BTBerryWifi`
- **Description**: The Bluetooth device name that appears in the mobile app when scanning. The actual name will be `{device_name}-{hostname}`.

#### `keep_alive`

- **Default**: `false`
- **Description**: If `true`, the addon will NOT auto-shutdown after the timeout. **WARNING**: This poses a security risk as the BLE server remains accessible indefinitely. Only enable temporarily when needed.

#### `encryption_enabled`

- **Default**: `false`
- **Description**: Premium BTBerryWifi app feature. Enables encryption of Bluetooth communication. Requires the premium version of the mobile app.

#### `password`

- **Default**: (empty)
- **Description**: Password for encryption/lock feature. If encryption is enabled but no password is set, the hostname will be used as the password.

## Usage

### Initial WiFi Setup

1. Start the addon from Home Assistant Supervisor
2. Open the BTBerryWifi app on your phone
3. Enable Bluetooth on your phone
4. Scan for devices in the app
5. Connect to `BTBerryWifi-{your-hostname}`
6. The app will display available WiFi networks
7. Select your network and enter the password
8. Wait for confirmation of successful connection

### Changing WiFi Networks

Follow the same steps as initial setup. The addon will configure the new network while preserving existing network configurations.

### Multiple Network Profiles

The addon works with NetworkManager, which supports multiple WiFi profiles. You can configure multiple networks, and Home Assistant will automatically connect to available saved networks based on priority.

## Troubleshooting

### Addon fails to start

**Error: "Bluetooth adapter /dev/hci0 not found!"**

- Ensure your device has a Bluetooth adapter
- Check that the Bluetooth adapter is accessible to Home Assistant OS
- Verify the adapter appears in `Supervisor → System → Hardware`

**Error: "WiFi adapter wlan0 not found!"**

- Your WiFi adapter may have a different name
- This is a warning; the addon may still work
- Check available network interfaces in Home Assistant OS

**Error: "NetworkManager is not accessible!"**

- NetworkManager is required for this addon to function
- This should be available by default on Home Assistant OS
- Try restarting Home Assistant

### Cannot find BLE device in mobile app

- Ensure Bluetooth is enabled on your phone
- Confirm the addon is running (check logs)
- The device name should appear as `BTBerryWifi-{hostname}`
- Try moving your phone closer to the Home Assistant device
- Check addon logs for errors

### WiFi connection fails

- **Incorrect password**: Double-check the WiFi password
- **Weak signal**: Ensure the WiFi network has adequate signal strength
- **Incompatible security**: Some WPA3-only networks may have compatibility issues
- **Check logs**: Set `log_level: debug` for detailed error information

### Addon doesn't auto-shutdown

- Ensure `keep_alive` is set to `false`
- Check the configured `bluetooth_timeout` value
- Review addon logs for errors

## Security Considerations

### Important Warnings

⚠️ **This addon runs with elevated privileges** (SYS_ADMIN, NET_ADMIN) to configure network settings.

⚠️ **BLE communication is unencrypted by default** unless you enable the encryption feature and have the premium mobile app.

⚠️ **Anyone with the BTBerryWifi app can connect** during the active window and potentially configure your WiFi.

### Best Practices

1. **Use the timeout feature**: Keep the default 15-minute timeout or shorter
2. **Don't use `keep_alive`**: Only enable temporarily if absolutely necessary
3. **Start manually**: Set `boot: manual` in configuration to prevent auto-start on boot
4. **Monitor access**: Check addon logs for connection attempts
5. **Disable when not needed**: Stop the addon immediately after configuring WiFi

## Attribution

This addon is based on the excellent [Rpi-SetWiFi-viaBluetooth](https://github.com/nksan/Rpi-SetWiFi-viaBluetooth) project by nksan.

The BTBerryWifi mobile app is developed by [BluePie Apps](https://bluepieapps.com/Set-wifi-via-bluetooth/BTBerryWifi-Overview/).

## Support

For issues related to:

- **This addon**: Report issues on the addon's GitHub repository
- **BTBerryWifi app**: Contact BluePie Apps
- **Home Assistant**: Visit the [Home Assistant Community](https://community.home-assistant.io/)

## License

This addon is provided as-is for use with Home Assistant OS. Please refer to the source repository for license information.
