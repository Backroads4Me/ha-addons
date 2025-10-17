# Bluetooth WiFi Setup

## How It Works

1. Start this addon on your Home Assistant system
2. The addon creates a Bluetooth server that advertises as `BTBerryWifi` (or your configured device name)
3. Connect to it using the BTBerryWifi mobile app (iOS/Android)
4. The app scans for available WiFi networks
5. Select a network and enter the password
6. The addon configures WiFi via the Home Assistant Supervisor API
7. After a configurable timeout (default: 15 minutes), the addon automatically shuts down

## Prerequisites

Before using this addon, ensure you have:

**Hardware:**

- Raspberry Pi (or compatible) with Bluetooth adapter
- WiFi adapter (accessible as `wlan0`)

**Software:**

- BTBerryWifi mobile app installed on your phone:
  - **iOS**: Search "BTBerryWifi" on Apple App Store
  - **Android**: Search "BTBerryWifi" on Google Play Store

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
- **Description**: How long the Bluetooth server stays active before automatically shutting down. This limits security exposure.

#### `log_level`

- **Default**: `info`
- **Options**: `debug`, `info`, `warning`, `error`
- **Description**: Controls the verbosity of addon logs. Use `debug` for troubleshooting.

#### `device_name`

- **Default**: `BTBerryWifi`
- **Description**: The Bluetooth device name that appears in the mobile app when scanning. Uses the configured name exactly as entered. If left blank, falls back to the system hostname.

#### `keep_alive`

- **Default**: `false`
- **Description**: If `true`, the addon will NOT auto-shutdown after the timeout. **WARNING**: This poses a security risk as the Bluetooth server remains accessible indefinitely. Only enable temporarily when needed.

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
5. Connect to the Bluetooth device (default name: `BTBerryWifi`)
6. The app will display available WiFi networks
7. Select your network and enter the password
8. Wait for confirmation of successful connection

### Changing WiFi Networks

Follow the same steps as initial setup. The addon will configure the new network while preserving existing network configurations.

## Troubleshooting

### Addon fails to start

**Error: "No Bluetooth adapter found!"**

- Ensure your device has a Bluetooth adapter
- Check that Bluetooth is enabled in Home Assistant
- Verify the adapter appears in `Settings → System → Hardware`
- Run `bluetoothctl list` in the Terminal addon to confirm BlueZ can see the adapter

**Error: "WiFi adapter wlan0 not found!"**

- Your WiFi adapter may have a different name
- This is a warning; the addon may still work
- Check available network interfaces in Home Assistant OS

**Error: "SUPERVISOR_TOKEN not found!" or "Supervisor API is not accessible!"**

- The Supervisor API is required for this addon to function
- This should be available by default on Home Assistant OS
- Ensure `hassio_api: true` is set in config.yaml (it should be by default)
- Try restarting the addon or Home Assistant

### Cannot find BLE device in mobile app

- Ensure Bluetooth is enabled on your phone
- Confirm the addon is running (check logs)
- The device name should appear as configured (default: `BTBerryWifi`)
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

⚠️ **This addon runs with elevated privileges** (SYS_ADMIN, NET_ADMIN, SYS_RAWIO) to configure network settings.

⚠️ **Bluetooth communication is unencrypted by default** unless you enable the encryption feature and have the premium mobile app.

⚠️ **Anyone with the BTBerryWifi app can connect** during the active window and potentially configure your WiFi.

### Best Practices

1. **Use the timeout feature**: Keep the default 15-minute timeout or shorter
2. **Don't use `keep_alive`**: Only enable temporarily if absolutely necessary
3. **Start manually**: Set `boot: manual` in configuration to prevent auto-start on boot
4. **Monitor access**: Check addon logs for connection attempts
5. **Disable when not needed**: Stop the addon immediately after configuring WiFi

## Additional Resources

**BTBerryWifi Mobile App:**

- Developed by [BluePie Apps](https://bluepieapps.com/Set-wifi-via-bluetooth/BTBerryWifi-Overview/)
- Premium features available (encryption, lock screen)

**Based on:**

- [Rpi-SetWiFi-viaBluetooth](https://github.com/nksan/Rpi-SetWiFi-viaBluetooth) project by nksan

**Need Help?**

- Review troubleshooting section above
- Check addon logs for detailed error messages
- Visit [Home Assistant Community](https://community.home-assistant.io/) for general questions
