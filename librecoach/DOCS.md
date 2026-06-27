# LibreCoach

Use this page for first-start steps, setup choices, and recovery notes that are
not obvious from the Configuration tab.

## First start

Keep the **Log** tab open the first time LibreCoach starts. Setup may pause
until Home Assistant is ready for MQTT discovery.

### Add the MQTT integration

If the log stops with a message that the MQTT integration is not yet enabled,
LibreCoach needs you to complete this step. LibreCoach installs and configures
the Mosquitto broker, but the MQTT integration must be manually enabled in Home
Assistant before it can be used.

1. Go to **Settings → Devices & services**.
2. Find **MQTT** under **Discovered**, select **Add**, and then **Submit**.
3. Return to **Settings → Add-ons → LibreCoach** and watch the log. Setup
   should resume automatically. If it does not resume within a minute, click
   **Restart**.

If MQTT is not offered under Discovered, confirm that **Mosquitto broker** is
running, then reload **Settings → Devices & services**.

### Existing Node-RED installation

If setup stops and says Node-RED already exists, that is a safety stop, not
an install failure. See [Existing Node-RED Installation](#existing-node-red-installation) at the bottom of this page.

Setup is complete when the log shows the **LibreCoach Installation Summary**
with **All components installed successfully!**

---

## Identifying your devices

Newly discovered RV-C entities have generic names. Identify them by operating
known physical controls and watching Home Assistant, then rename and assign
areas to the matching entities. Do not operate an unknown entity merely to find
out what it controls. See [Identifying Your Devices](https://librecoach.com/configuration/dentify-devices/) for the recommended process.

---

## Features that need setup outside this app

Enabling these features is only one part of their setup:

- **Victron:** the GX device must be on the same network, allow local MQTT
  access, and have MQTT enabled. Restart Node-RED after completing the GX
  setup. See [Victron GX Integration](https://librecoach.com/configuration/victron/).
- **Micro-Air EasyTouch:** the Home Assistant host needs working Bluetooth and
  must be within reliable range of the thermostat. See [Micro-Air EasyTouch](https://librecoach.com/configuration/microair/).
- **Hughes Power Watchdog:** Bluetooth discovery is easiest when only the
  Watchdog being added is nearby.
- **Automated location updates:** the selected `device_tracker` must expose
  latitude and longitude attributes. Verify this under **Developer Tools →
  States** before enabling it. The secondary tracker is only a fallback. See
  [GPS Updates](https://librecoach.com/configuration/gps/).

---

## Troubleshooting

Enable **Debug Logging** on the Configuration tab to help troubleshoot a
problem. Restart the app and the log will include additional detail. Turn it
off afterward so routine events remain easy to find.

The full installation and configuration guides are available at [LibreCoach.com](https://librecoach.com/).

---

## If you customize your Node-RED configuration

By default, an app update also installs the current LibreCoach Node-RED flows.
This is how updates and new device support are delivered.

Enable **Preserve Node-RED Flow Customizations** before making intentional
changes to the active flows. While preservation is enabled, LibreCoach continues
to update its background processes and reference files but leaves the active
flows alone.

Turning preservation off restores the standard LibreCoach flows on the next
restart and discards the active customized version.

---

## Existing Node-RED installation

LibreCoach supplies and manages its own Node-RED flows. If Node-RED was already
installed, setup stops rather than replace your existing flows without
permission.

Before continuing, create a full Home Assistant backup. Then choose one path:

- To use the standard LibreCoach flows, enable **Allow Node-RED Overwrite**,
  save, and restart LibreCoach. Your active Node-RED flows will be replaced.
- To keep your current flows, enable **Preserve Node-RED Flow Customizations**,
  save, and restart LibreCoach. LibreCoach will still manage Node-RED startup
  and shared support files, but you are responsible for incorporating future
  LibreCoach flow changes yourself.

The overwrite option is only an initial-setup authorization.
