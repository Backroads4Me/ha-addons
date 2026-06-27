import asyncio
import sys
from pathlib import Path


_PKG_DIR = Path(__file__).resolve().parents[1]
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

from geo_bridge import GeoBridge


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class FakeMqtt:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))


def make_bridge(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-token")
    bridge = GeoBridge(
        {
            "geo_enabled": True,
            "geo_device_tracker_primary": "device_tracker.test",
            "geo_device_tracker_secondary": "",
            "geo_update_threshold": 10,
        },
        FakeMqtt(),
    )
    monkeypatch.setattr(bridge, "_load_cities", lambda: [])
    return bridge


def test_start_does_not_sleep_when_initial_coordinates_are_missing(monkeypatch):
    bridge = make_bridge(monkeypatch)

    async def fetch_coordinates():
        return None

    async def check_and_update(*_args, **_kwargs):  # pragma: no cover
        raise AssertionError("startup should not update without coordinates")

    async def sleep(_delay):  # pragma: no cover
        raise AssertionError("startup should not block on retry sleeps")

    monkeypatch.setattr(bridge, "_fetch_coordinates", fetch_coordinates)
    monkeypatch.setattr(bridge, "_check_and_update", check_and_update)
    monkeypatch.setattr("geo_bridge.asyncio.sleep", sleep)

    async def scenario():
        await bridge.start()
        await bridge.stop()

    run(scenario())


def test_start_attempts_one_forced_update_when_coordinates_exist(monkeypatch):
    bridge = make_bridge(monkeypatch)
    updates = []

    async def fetch_coordinates():
        return (42.0, -76.0, 300.0, "device_tracker.test")

    async def check_and_update(lat, lon, elev, tracker_id, force=False):
        updates.append((lat, lon, elev, tracker_id, force))
        return True

    monkeypatch.setattr(bridge, "_fetch_coordinates", fetch_coordinates)
    monkeypatch.setattr(bridge, "_check_and_update", check_and_update)

    async def scenario():
        await bridge.start()
        await bridge.stop()

    run(scenario())

    assert updates == [(42.0, -76.0, 300.0, "device_tracker.test", True)]
