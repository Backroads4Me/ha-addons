"""Test harness for the BLE bridge.

Home Assistant and bleak are not installed in the dev/test environment, so we
inject lightweight fakes into sys.modules before the bridge package is imported.
The fakes record interactions (callback registrations, MQTT publishes) so the
acceptance tests can assert on them.
"""
import sys
import types
from pathlib import Path

# Make the `librecoach_ble` package importable (its modules use relative imports).
_PKG_PARENT = Path(__file__).resolve().parents[2]  # .../librecoach
if str(_PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(_PKG_PARENT))


# --- fake bleak ---
bleak = types.ModuleType("bleak")


class BleakError(Exception):
    pass


bleak.BleakError = BleakError
sys.modules["bleak"] = bleak

brc = types.ModuleType("bleak_retry_connector")


async def _establish_connection(*args, **kwargs):  # pragma: no cover - not exercised
    raise BleakError("no real BLE in tests")


brc.establish_connection = _establish_connection
brc.BleakClientWithServiceCache = object
sys.modules["bleak_retry_connector"] = brc


# fake aiohttp (imported by the package __init__)
aiohttp = types.ModuleType("aiohttp")


class _ClientTimeout:
    def __init__(self, *args, **kwargs):
        pass


aiohttp.ClientTimeout = _ClientTimeout
sys.modules["aiohttp"] = aiohttp


# --- fake homeassistant (as a package so submodules resolve) ---
ha = types.ModuleType("homeassistant")
ha.__path__ = []  # mark as package
ha_components = types.ModuleType("homeassistant.components")
ha_components.__path__ = []
ha_core = types.ModuleType("homeassistant.core")

ha_helpers = types.ModuleType("homeassistant.helpers")
ha_helpers.__path__ = []
ha_helpers_aiohttp = types.ModuleType("homeassistant.helpers.aiohttp_client")
ha_helpers_aiohttp.async_get_clientsession = lambda hass: None
ha_helpers_typing = types.ModuleType("homeassistant.helpers.typing")
ha_helpers_typing.ConfigType = dict


class HomeAssistant:
    pass


def _callback(func):
    """Identity stand-in for homeassistant.core.callback."""
    return func


ha_core.HomeAssistant = HomeAssistant
ha_core.callback = _callback

# mqtt: record publishes and subscriptions
ha_mqtt = types.ModuleType("homeassistant.components.mqtt")
PUBLISHED = []        # list of dicts: topic/payload/qos/retain
SUBSCRIPTIONS = []    # list of topic strings


async def _async_publish(hass, topic, payload, qos=0, retain=False):
    PUBLISHED.append({"topic": topic, "payload": payload, "qos": qos, "retain": retain})


# Retained messages a test wants the broker to "flush" on subscribe. Each entry is
# a simple object with .topic/.payload/.retain, keyed by the topic-filter prefix
# (the part before the trailing '#') the subscription must match.
RETAINED_FIXTURES = []


class _FakeMsg:
    def __init__(self, topic, payload, retain=True):
        self.topic = topic
        self.payload = payload
        self.retain = retain


async def _async_subscribe(hass, topic, callback, qos=0):
    SUBSCRIPTIONS.append(topic)
    # Emulate the broker flushing retained messages to a fresh wildcard subscriber.
    if topic.endswith("/#"):
        prefix = topic[:-1]  # strip '#', keep trailing '/'
        for msg in RETAINED_FIXTURES:
            if msg.topic.startswith(prefix):
                callback(msg)
    return lambda: None  # unsubscribe handle


ha_mqtt.async_publish = _async_publish
ha_mqtt.async_subscribe = _async_subscribe

# bluetooth: count callback registrations
ha_bt = types.ModuleType("homeassistant.components.bluetooth")
REGISTERED_CALLBACKS = []


def _async_register_callback(hass, callback, matcher, change):
    REGISTERED_CALLBACKS.append(callback)
    return lambda: None


def _async_ble_device_from_address(hass, address, connectable=True):  # pragma: no cover
    return None


class BluetoothCallbackMatcher:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _BluetoothChange:
    ADVERTISEMENT = "advertisement"


class BluetoothServiceInfoBleak:  # placeholder type for annotations
    pass


ha_bt.async_register_callback = _async_register_callback
ha_bt.async_ble_device_from_address = _async_ble_device_from_address
ha_bt.BluetoothCallbackMatcher = BluetoothCallbackMatcher
ha_bt.BluetoothChange = _BluetoothChange
ha_bt.BluetoothServiceInfoBleak = BluetoothServiceInfoBleak

# attribute wiring so `from homeassistant.components import mqtt` works
ha.components = ha_components
ha.core = ha_core
ha.helpers = ha_helpers
ha_components.mqtt = ha_mqtt
ha_components.bluetooth = ha_bt
ha_helpers.aiohttp_client = ha_helpers_aiohttp
ha_helpers.typing = ha_helpers_typing

sys.modules["homeassistant"] = ha
sys.modules["homeassistant.components"] = ha_components
sys.modules["homeassistant.core"] = ha_core
sys.modules["homeassistant.helpers"] = ha_helpers
sys.modules["homeassistant.helpers.aiohttp_client"] = ha_helpers_aiohttp
sys.modules["homeassistant.helpers.typing"] = ha_helpers_typing
sys.modules["homeassistant.components.mqtt"] = ha_mqtt
sys.modules["homeassistant.components.bluetooth"] = ha_bt


def reset_recorders():
    PUBLISHED.clear()
    SUBSCRIPTIONS.clear()
    REGISTERED_CALLBACKS.clear()
    RETAINED_FIXTURES.clear()


def add_retained(topic, payload="x", retain=True):
    """Register a retained message the fake broker flushes to wildcard subscribers."""
    RETAINED_FIXTURES.append(_FakeMsg(topic, payload, retain))
