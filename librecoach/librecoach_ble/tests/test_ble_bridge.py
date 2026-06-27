"""Acceptance tests for the BLE bridge refactor (B-1, B-2, B-4, B-5).

These run against fakes for Home Assistant and bleak (see conftest.py).
"""
import asyncio
import json

import conftest  # registers fakes; exposes recorders

from librecoach_ble.bridge import BleBridgeManager
from librecoach_ble.devices.base import BleDeviceHandler, StateMessage, AuthenticationError
from librecoach_ble.devices.microair import MicroAirHandler
from librecoach_ble import const


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class FakeHass:
    def async_create_task(self, coro):
        coro.close()  # don't actually run the poll loop in unit tests
        return None

    async def async_add_executor_job(self, func, *args):
        return func(*args)


# --- B-1: a single advertisement callback is registered regardless of handler count ---

def test_b1_single_callback_one_handler(monkeypatch):
    conftest.reset_recorders()
    import librecoach_ble.bridge as bridge_mod
    monkeypatch.setattr(bridge_mod, "DEVICE_HANDLERS", [MicroAirHandler])

    mgr = BleBridgeManager(FakeHass(), {}, {"microair"})
    run(mgr.start())

    assert len(conftest.REGISTERED_CALLBACKS) == 1


def test_b1_single_callback_two_handlers(monkeypatch):
    conftest.reset_recorders()

    class FakeHughes(MicroAirHandler):
        @staticmethod
        def device_type():
            return "hughes"

        @staticmethod
        def match_name(name):
            return name.startswith("Hughes")

    import librecoach_ble.bridge as bridge_mod
    monkeypatch.setattr(bridge_mod, "DEVICE_HANDLERS", [MicroAirHandler, FakeHughes])

    mgr = BleBridgeManager(FakeHass(), {}, {"microair", "hughes"})
    run(mgr.start())

    # Still exactly one callback even with two handlers registered.
    assert len(conftest.REGISTERED_CALLBACKS) == 1


# --- B-2: handler owns topic construction; bridge stays generic ---

def test_b2_microair_topics_unchanged():
    h = MicroAirHandler("AA:BB:CC:DD:EE:FF", {})
    parsed = {
        "zones": {0: {"mode": "cool", "cool_sp": 72}},
        "zone_configs": {0: {"MAV": 1}},
    }
    msgs = h.state_messages(parsed)
    topics = [m.topic for m in msgs]
    assert "librecoach/ble/microair/aa:bb:cc:dd:ee:ff/state" in [t.lower() for t in topics]
    cfg = [m for m in msgs if m.topic.endswith("/zone/0/config")]
    assert len(cfg) == 1 and cfg[0].retain is True
    # state payload carries the zone number, not retained
    state = [m for m in msgs if m.topic.endswith("/state")][0]
    assert json.loads(state.payload)["zone"] == 0
    assert state.retain is False


def test_b2_nonnumeric_zone_keys_do_not_crash():
    h = MicroAirHandler("aa:bb", {})
    parsed = {"zones": {"weird": {"mode": "off"}, 1: {"mode": "cool"}},
              "zone_configs": {1: {"MAV": 0}}}
    msgs = h.state_messages(parsed)  # must not raise
    # the non-numeric key still publishes a state message but no config
    assert any(m.topic.endswith("/state") for m in msgs)


def test_microair_poll_uses_zoneless_config_request(monkeypatch):
    handler = MicroAirHandler("aa:bb", {})
    requests = []
    responses = iter([
        {"Z_sts": {"0": [70, 75, 72, 68, 0, 0, 1, 2, 2, 128, 2, 0, 71, 0, 0, 2]}},
        {
            "Type": "Response",
            "RT": "Config",
            "CFG": {"Zone": 0, "MAV": 6, "FA": [0] * 16, "SPL": [55, 95, 40, 95]},
        },
    ])

    async def fake_request(client, command):
        requests.append(command)
        return next(responses)

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(handler, "_request_json", fake_request)
    monkeypatch.setattr("librecoach_ble.devices.microair.asyncio.sleep", no_sleep)

    parsed = run(handler.poll(object()))

    assert requests == [{"Type": "Get Status"}, {"Type": "Get Config"}]
    assert parsed["zone_configs"][0]["MAV"] == 6


def test_microair_does_not_cache_config_without_capabilities():
    handler = MicroAirHandler("aa:bb", {})

    assert handler._store_capability_config({
        "Type": "Response", "RT": "Config", "CFG": {"Zone": 0},
    }) is False
    assert handler._zone_configs == {}


def test_microair_parses_string_encoded_capabilities():
    handler = MicroAirHandler("aa:bb", {})

    assert handler._store_capability_config({
        "Type": "Response",
        "RT": "Config",
        "CFG": json.dumps({"Zone": "1", "MAV": "3126", "SPL": [55, 95, 40, 95]}),
    }) is True
    assert handler._zone_configs[1]["MAV"] == 3126


def test_microair_omits_unavailable_outdoor_temperature():
    handler = MicroAirHandler("aa:bb", {})

    parsed = handler.parse_status({
        "PRM": [0, 8, -32768],
        "Z_sts": {
            "0": [68, 68, 74, 60, 72, 45, 0, 128, 128, 128, 0, 128, 68, 0, 0, 0],
        },
    })

    assert "outdoorTemperature" not in parsed["zones"][0]
    assert parsed["zones"][0]["facePlateTemperature"] == 68


def test_b2_fake_nonzoned_handler_can_publish():
    conftest.reset_recorders()

    class FakeNonZoned(BleDeviceHandler):
        def __init__(self, address, config):
            self.address = address

        @staticmethod
        def device_type():
            return "fakedev"

        @staticmethod
        def match_name(name):
            return name.startswith("Fake")

        async def authenticate(self, client):
            return True

        async def poll(self, client):
            return {"watts": 1200}

        async def handle_command(self, client, command):
            return True

        def parse_status(self, raw):
            return raw

        def state_messages(self, parsed):
            return [StateMessage(
                f"librecoach/ble/fakedev/{self.address}/state",
                json.dumps(parsed),
                retain=False,
            )]

    mgr = BleBridgeManager(FakeHass(), {})
    handler = FakeNonZoned("11:22", {})
    run(mgr._publish_messages(handler, {"watts": 1200}))

    assert conftest.PUBLISHED[0]["topic"] == "librecoach/ble/fakedev/11:22/state"
    assert json.loads(conftest.PUBLISHED[0]["payload"]) == {"watts": 1200}


# --- Stale-device cleanup: retire retained MQTT topics for non-locked addresses ---

def _no_sleep(monkeypatch):
    async def _sleep(_delay):
        return None
    monkeypatch.setattr("librecoach_ble.bridge.asyncio.sleep", _sleep)


def test_retire_clears_all_topics_except_locked_address(monkeypatch):
    conftest.reset_recorders()
    _no_sleep(monkeypatch)

    keep = "78:e3:6d:fc:5e:ce"
    stale = "a8:03:2a:31:ce:8a"
    # A stale address leaves several retained topics, including a dynamic zone config.
    conftest.add_retained(f"librecoach/ble/microair/{stale}/available", "offline")
    conftest.add_retained(f"librecoach/ble/microair/{stale}/zone/0/config", "{}")
    conftest.add_retained(f"librecoach/bridge/microair/{stale}", "disconnected")
    # The locked device's own retained topics must survive the sweep.
    conftest.add_retained(f"librecoach/ble/microair/{keep}/available", "online")
    conftest.add_retained(f"librecoach/ble/microair/{keep}/zone/0/config", "{}")

    mgr = BleBridgeManager(FakeHass(), {})
    run(mgr._retire_stale_addresses("microair", keep))

    cleared = {p["topic"] for p in conftest.PUBLISHED if p["payload"] == "" and p["retain"]}
    assert f"librecoach/ble/microair/{stale}/available" in cleared
    assert f"librecoach/ble/microair/{stale}/zone/0/config" in cleared
    assert f"librecoach/bridge/microair/{stale}" in cleared
    # Nothing belonging to the locked address was cleared.
    assert not any(keep in topic for topic in cleared)


def test_retire_without_anchor_is_a_noop(monkeypatch):
    """Missing/empty anchor must never wipe a whole device type (offline device safety)."""
    conftest.reset_recorders()
    _no_sleep(monkeypatch)

    conftest.add_retained("librecoach/ble/microair/aa:aa:aa:aa:aa:aa/available", "online")
    conftest.add_retained("librecoach/bridge/microair/bb:bb:bb:bb:bb:bb", "connected")

    mgr = BleBridgeManager(FakeHass(), {})
    for bad_anchor in (None, ""):
        run(mgr._retire_stale_addresses("microair", bad_anchor))

    assert conftest.PUBLISHED == []


class RecordingHass(FakeHass):
    """FakeHass that records how many background tasks start() schedules."""

    def __init__(self):
        self.created = 0

    def async_create_task(self, coro):
        self.created += 1
        coro.close()  # don't actually run it
        return None


def test_startup_skips_falsy_lock_values(monkeypatch):
    """A corrupted lock value must not anchor a sweep at startup."""
    conftest.reset_recorders()
    _no_sleep(monkeypatch)

    # Falsy lock value — start() must NOT schedule a retire sweep for it.
    hass = RecordingHass()
    mgr = BleBridgeManager(hass, {"locked_devices": {"microair": ""}})
    run(mgr.start())
    assert hass.created == 0

    # A valid lock value — start() SHOULD schedule exactly one sweep.
    hass2 = RecordingHass()
    mgr2 = BleBridgeManager(hass2, {"locked_devices": {"microair": "78:e3:6d:fc:5e:ce"}})
    run(mgr2.start())
    assert hass2.created == 1


def test_retire_ignores_already_cleared_retained(monkeypatch):
    conftest.reset_recorders()
    _no_sleep(monkeypatch)

    stale = "cc:cc:cc:cc:cc:cc"
    # An empty retained payload is an already-tombstoned topic; do not re-publish it.
    conftest.add_retained(f"librecoach/ble/microair/{stale}/available", "")

    mgr = BleBridgeManager(FakeHass(), {})
    run(mgr._retire_stale_addresses("microair", "78:e3:6d:fc:5e:ce"))

    assert conftest.PUBLISHED == []


# --- B-4: backoff schedule ---

def test_b4_backoff_progression():
    mgr = BleBridgeManager(FakeHass(), {})
    entry = {"failure_count": 0}
    assert mgr._next_delay(entry) == const.BLE_POLL_INTERVAL
    seen = []
    for fc in range(1, 8):
        entry["failure_count"] = fc
        seen.append(mgr._next_delay(entry))
    assert seen[:4] == const.BLE_BACKOFF_SCHEDULE
    # caps at the last value
    assert seen[-1] == const.BLE_BACKOFF_SCHEDULE[-1]


# --- B-4/B-5: offline published once on transition; auth distinct from connectivity ---

def test_b4_offline_published_once_on_transition():
    conftest.reset_recorders()
    mgr = BleBridgeManager(FakeHass(), {})
    addr = "aa:bb"
    mgr._active_devices[addr] = {
        "failure_count": 0, "availability": None, "last_error": const.ERROR_NONE,
    }
    # Drive several connectivity failures; offline should appear exactly once.
    for _ in range(6):
        run(mgr._on_poll_failure("microair", addr, Exception("boom"), const.ERROR_CONNECTIVITY))
    offline = [p for p in conftest.PUBLISHED
               if p["topic"].endswith("/available") and p["payload"] == const.PAYLOAD_OFFLINE]
    assert len(offline) == 1


def test_b5_auth_failure_marks_offline_immediately_and_distinctly():
    conftest.reset_recorders()
    mgr = BleBridgeManager(FakeHass(), {})
    addr = "aa:bb"
    mgr._active_devices[addr] = {
        "failure_count": 0, "availability": None, "last_error": const.ERROR_NONE,
    }
    run(mgr._on_poll_failure("microair", addr, AuthenticationError("nope"), const.ERROR_AUTH_FAILED))
    # one failure is enough for auth
    offline = [p for p in conftest.PUBLISHED
               if p["topic"].endswith("/available") and p["payload"] == const.PAYLOAD_OFFLINE]
    assert len(offline) == 1
    last_err = [p for p in conftest.PUBLISHED if p["topic"].endswith("/last_error")][-1]
    assert last_err["payload"] == const.ERROR_AUTH_FAILED


def test_b4_recovery_publishes_online_on_transition():
    conftest.reset_recorders()
    mgr = BleBridgeManager(FakeHass(), {})
    addr = "aa:bb"
    mgr._active_devices[addr] = {
        "failure_count": 5, "availability": const.PAYLOAD_OFFLINE, "last_error": const.ERROR_CONNECTIVITY,
    }
    run(mgr._on_poll_success("microair", addr))
    online = [p for p in conftest.PUBLISHED
              if p["topic"].endswith("/available") and p["payload"] == const.PAYLOAD_ONLINE]
    assert len(online) == 1
    assert mgr._active_devices[addr]["failure_count"] == 0
