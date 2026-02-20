DOMAIN = "librecoach_ble"
CONFIG_PATH = "/config/.librecoach-ble-config.json"

# Base MQTT topic prefix — device handlers build on this
MQTT_BASE = "librecoach/ble"

# Topic templates (handlers fill in {device_type} and {address})
#   e.g. "librecoach/ble/microair/78:e3:6d:fc:5e:ce/state"
TOPIC_STATE     = MQTT_BASE + "/{device_type}/{address}/state"
TOPIC_SET       = MQTT_BASE + "/{device_type}/{address}/set"
TOPIC_AVAILABLE = MQTT_BASE + "/{device_type}/{address}/available"
TOPIC_BRIDGE    = "librecoach/bridge/{device_type}/{address}"
