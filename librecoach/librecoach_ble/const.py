DOMAIN = "librecoach_ble"
CONFIG_PATH = "/config/.librecoach-ble-config.json"
BLE_POLL_INTERVAL = 30  # seconds between BLE device polls when healthy

# Backoff schedule (seconds) applied after consecutive poll failures. The last
# value is the cap and is reused for all further failures. Retries continue
# forever while the device/integration is enabled (B-4).
BLE_BACKOFF_SCHEDULE = [30, 60, 120, 300]

# Consecutive connectivity failures before a device is declared offline. Avoids
# flapping on a single transient failure. Auth failures bypass this (declared at 1).
OFFLINE_AFTER_FAILURES = 3

# Base MQTT topic prefix — device handlers build on this
MQTT_BASE = "librecoach/ble"

# Topic templates (handlers fill in {device_type} and {address})
#   e.g. "librecoach/ble/microair/78:e3:6d:fc:5e:ce/state"
TOPIC_STATE     = MQTT_BASE + "/{device_type}/{address}/state"
TOPIC_SET       = MQTT_BASE + "/{device_type}/{address}/set"
TOPIC_AVAILABLE = MQTT_BASE + "/{device_type}/{address}/available"
TOPIC_BRIDGE    = "librecoach/bridge/{device_type}/{address}"

# Per-device diagnostic topics (F-6). Retained so HA reflects last known state.
TOPIC_LAST_SUCCESS  = MQTT_BASE + "/{device_type}/{address}/last_success"
TOPIC_FAILURE_COUNT = MQTT_BASE + "/{device_type}/{address}/failure_count"
TOPIC_LAST_ERROR    = MQTT_BASE + "/{device_type}/{address}/last_error"

# Bridge-level command topics
TOPIC_RESET_LOCKS = MQTT_BASE + "/reset_locks"          # B-3/BL-3
# Per-device command topics (F-6) — subscribed as wildcards by the bridge
TOPIC_RECONNECT    = MQTT_BASE + "/{device_type}/{address}/reconnect"
TOPIC_CLEAR_ERRORS = MQTT_BASE + "/{device_type}/{address}/clear_errors"

# Seconds to wait for the broker to flush retained messages during a stale-topic
# scan. Retained messages arrive immediately on subscribe; this is a safety margin.
RETAINED_SCAN_WAIT = 2.0

# Availability payloads
PAYLOAD_ONLINE  = "online"
PAYLOAD_OFFLINE = "offline"

# last_error values (also used to distinguish failure classes in HA)
ERROR_NONE        = "none"
ERROR_AUTH_FAILED = "auth_failed"
ERROR_CONNECTIVITY = "connectivity"
