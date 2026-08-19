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
from librecoach_ble import bridge as bridge_mod


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


def test_microair_poll_uses_per_zone_config_request(monkeypatch):
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

    assert requests == [{"Type": "Get Status"}, {"Type": "Get Config", "Zone": 0}]
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
    fast_handler = type("FastHandler", (), {"poll_interval": 1})()
    assert mgr._next_delay(entry, fast_handler) == 1
    seen = []
    for fc in range(1, 8):
        entry["failure_count"] = fc
        seen.append(mgr._next_delay(entry))
    assert seen[:4] == const.BLE_BACKOFF_SCHEDULE
    # caps at the last value
    assert seen[-1] == const.BLE_BACKOFF_SCHEDULE[-1]


def test_healthy_diagnostics_are_not_published_at_fast_device_cadence(monkeypatch):
    conftest.reset_recorders()
    mgr = BleBridgeManager(FakeHass(), {})
    addr = "aa:bb"
    mgr._active_devices[addr] = {
        "failure_count": 0,
        "availability": const.PAYLOAD_ONLINE,
        "last_error": const.ERROR_NONE,
        "last_success_diagnostic": 100.0,
    }
    monkeypatch.setattr(bridge_mod.time, "monotonic", lambda: 101.0)

    run(mgr._on_poll_success("hughes", addr))

    assert conftest.PUBLISHED == []


# --- B-4/F-6: bounded operations and recovery from wedged BLE awaits ---

class _ConnectedClient:
    def __init__(self, hang_disconnect=False):
        self.is_connected = True
        self.disconnect_calls = 0
        self._hang_disconnect = hang_disconnect

    async def disconnect(self):
        self.disconnect_calls += 1
        if self._hang_disconnect:
            await asyncio.Event().wait()
        self.is_connected = False


def _active_entry(handler, client=None):
    return {
        "handler": handler,
        "task": None,
        "ble_device": object(),
        "client": client,
        "lock": asyncio.Lock(),
        "authenticated": client is not None,
        "failure_count": 0,
        "availability": None,
        "last_error": const.ERROR_NONE,
        "wake": asyncio.Event(),
    }


def test_operation_timeout_retries_disconnects_and_releases_lock(monkeypatch):
    monkeypatch.setattr(bridge_mod, "BLE_OPERATION_TIMEOUT", 0.01)
    monkeypatch.setattr(bridge_mod, "BLE_DISCONNECT_TIMEOUT", 0.01)

    client = _ConnectedClient()
    mgr = BleBridgeManager(FakeHass(), {})
    address = "aa:bb"
    entry = _active_entry(object(), client)
    mgr._active_devices[address] = entry
    operation_calls = 0

    async def ensure_connected(_address):
        entry["client"] = client
        client.is_connected = True
        return client

    async def never_returns(_client):
        nonlocal operation_calls
        operation_calls += 1
        await asyncio.Event().wait()

    monkeypatch.setattr(mgr, "_ensure_connected", ensure_connected)

    async def scenario():
        try:
            await mgr._execute_with_lock(address, never_returns)
        except asyncio.TimeoutError:
            pass
        else:  # pragma: no cover - protects the timeout assertion
            raise AssertionError("wedged BLE operation did not time out")

    run(scenario())

    assert operation_calls == 2
    assert client.disconnect_calls == 2
    assert entry["client"] is None
    assert entry["authenticated"] is False
    assert entry["lock"].locked() is False


def test_disconnect_timeout_still_discards_cached_client(monkeypatch):
    monkeypatch.setattr(bridge_mod, "BLE_DISCONNECT_TIMEOUT", 0.01)

    client = _ConnectedClient(hang_disconnect=True)
    mgr = BleBridgeManager(FakeHass(), {})
    address = "aa:bb"
    entry = _active_entry(object(), client)
    mgr._active_devices[address] = entry

    run(mgr._disconnect(address, entry))

    assert client.disconnect_calls == 1
    assert entry["client"] is None
    assert entry["authenticated"] is False


def test_cancelling_bounded_operation_cancels_its_child():
    mgr = BleBridgeManager(FakeHass(), {})

    async def scenario():
        child_started = asyncio.Event()
        child_stopped = asyncio.Event()

        async def child():
            child_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                child_stopped.set()

        outer = asyncio.create_task(mgr._bounded(child(), 60, "test operation"))
        await child_started.wait()
        outer.cancel()
        try:
            await outer
        except asyncio.CancelledError:
            pass

        await child_stopped.wait()

    run(scenario())


def test_authentication_timeout_can_disconnect_new_client(monkeypatch):
    monkeypatch.setattr(bridge_mod, "BLE_OPERATION_TIMEOUT", 0.01)
    monkeypatch.setattr(bridge_mod, "BLE_DISCONNECT_TIMEOUT", 0.01)

    class HangingHandler:
        async def authenticate(self, _client):
            await asyncio.Event().wait()

    client = _ConnectedClient()
    mgr = BleBridgeManager(FakeHass(), {})
    address = "aa:bb"
    entry = _active_entry(HangingHandler())
    mgr._active_devices[address] = entry

    async def establish(*_args, **_kwargs):
        client.is_connected = True
        return client

    monkeypatch.setattr(bridge_mod, "establish_connection", establish)
    monkeypatch.setattr(mgr, "_get_ble_device", lambda _address: object())

    async def operation(_client):  # pragma: no cover - auth never completes
        raise AssertionError("operation ran before authentication completed")

    async def scenario():
        try:
            await mgr._execute_with_lock(address, operation)
        except asyncio.TimeoutError:
            pass
        else:  # pragma: no cover - protects the timeout assertion
            raise AssertionError("wedged authentication did not time out")

    run(scenario())

    assert client.disconnect_calls == 2
    assert entry["client"] is None
    assert entry["authenticated"] is False


def test_ensure_connected_does_not_reuse_unauthenticated_client(monkeypatch):
    class Handler:
        async def authenticate(self, _client):
            return True

    stale_client = _ConnectedClient()
    fresh_client = _ConnectedClient()
    mgr = BleBridgeManager(FakeHass(), {})
    address = "aa:bb"
    entry = _active_entry(Handler(), stale_client)
    entry["authenticated"] = False
    mgr._active_devices[address] = entry

    async def establish(*_args, **_kwargs):
        return fresh_client

    monkeypatch.setattr(bridge_mod, "establish_connection", establish)
    monkeypatch.setattr(mgr, "_get_ble_device", lambda _address: object())

    result = run(mgr._ensure_connected(address))

    assert stale_client.disconnect_calls == 1
    assert result is fresh_client
    assert entry["client"] is fresh_client
    assert entry["authenticated"] is True


def test_poll_timeout_updates_connectivity_diagnostics(monkeypatch):
    conftest.reset_recorders()
    monkeypatch.setattr(bridge_mod, "BLE_OPERATION_TIMEOUT", 0.01)
    monkeypatch.setattr(bridge_mod, "BLE_DISCONNECT_TIMEOUT", 0.01)

    class HangingHandler:
        @staticmethod
        def device_type():
            return "microair"

        async def poll(self, _client):
            await asyncio.Event().wait()

    handler = HangingHandler()
    client = _ConnectedClient()
    mgr = BleBridgeManager(FakeHass(), {})
    address = "aa:bb"
    entry = _active_entry(handler, client)
    entry["wake"].set()
    mgr._active_devices[address] = entry

    async def ensure_connected(_address):
        entry["client"] = client
        client.is_connected = True
        return client

    monkeypatch.setattr(mgr, "_ensure_connected", ensure_connected)
    record_failure = mgr._on_poll_failure

    async def stop_after_failure(device_type, failed_address, exc, error_kind):
        await record_failure(device_type, failed_address, exc, error_kind)
        mgr._stopping = True

    monkeypatch.setattr(mgr, "_on_poll_failure", stop_after_failure)

    run(mgr._poll_loop(handler, address))

    assert entry["failure_count"] == 1
    assert entry["last_error"] == const.ERROR_CONNECTIVITY
    assert any(
        item["topic"].endswith("/failure_count") and item["payload"] == "1"
        for item in conftest.PUBLISHED
    )
    assert any(
        item["topic"].endswith("/last_error")
        and item["payload"] == const.ERROR_CONNECTIVITY
        for item in conftest.PUBLISHED
    )


def test_reconnect_replaces_poll_task_after_hung_disconnect(monkeypatch):
    monkeypatch.setattr(bridge_mod, "BLE_DISCONNECT_TIMEOUT", 0.01)
    monkeypatch.setattr(bridge_mod, "BLE_TASK_CANCEL_TIMEOUT", 0.01)

    class RunningHass(FakeHass):
        def async_create_task(self, coro):
            return asyncio.create_task(coro)

    class Handler:
        @staticmethod
        def device_type():
            return "microair"

    async def scenario():
        client = _ConnectedClient(hang_disconnect=True)
        mgr = BleBridgeManager(RunningHass(), {})
        address = "aa:bb"
        handler = Handler()
        old_lock = asyncio.Lock()
        old_started = asyncio.Event()
        replacement_started = asyncio.Event()
        replacement_release = asyncio.Event()

        async def old_poll():
            old_started.set()
            await asyncio.Event().wait()

        async def replacement_poll(_handler, _address):
            replacement_started.set()
            await replacement_release.wait()

        old_task = asyncio.create_task(old_poll())
        entry = _active_entry(handler, client)
        entry["task"] = old_task
        entry["lock"] = old_lock
        entry["failure_count"] = 4
        mgr._active_devices[address] = entry
        monkeypatch.setattr(mgr, "_poll_loop", replacement_poll)

        await old_started.wait()
        msg = type("Msg", (), {
            "topic": f"librecoach/ble/microair/{address}/reconnect"
        })()
        await mgr._on_reconnect(msg)
        await replacement_started.wait()

        replacement_task = entry["task"]
        assert old_task.cancelled()
        assert replacement_task is not old_task
        assert replacement_task.done() is False
        assert entry["failure_count"] == 0
        assert entry["client"] is None
        assert entry["lock"] is not old_lock

        replacement_release.set()
        await replacement_task

    run(scenario())


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
