"""Protocol and lifecycle tests for the Hughes Power Watchdog handler."""

import asyncio
import json
import struct
from datetime import datetime

import conftest  # registers Home Assistant and bleak fakes

from librecoach_ble.bridge import BleBridgeManager
from librecoach_ble.devices.hughes import (
    HughesHandler,
    MAX_V2_PAYLOAD,
    V2_CHAR_UUID,
    V2_ERROR_DELETE,
    V2_ERROR_REPORT,
    V2_END,
    V2_HEADER,
    V2_SET_BACKLIGHT,
    V2_SET_TIME,
)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def scaled(value, factor=10000):
    return struct.pack(">I", round(value * factor))


def v1_frame(
    line,
    voltage=121.4,
    current=14.3,
    power=1735.0,
    energy=142.3,
    frequency=60.0,
    markers=None,
    error=0,
):
    frame = bytearray(40)
    frame[:3] = b"\x01\x03\x20"
    frame[3:7] = struct.pack(">i", round(voltage * 10000))
    frame[7:11] = struct.pack(">i", round(current * 10000))
    frame[11:15] = struct.pack(">i", round(power * 10000))
    frame[15:19] = struct.pack(">i", round(energy * 10000))
    frame[19] = error
    frame[31:35] = struct.pack(">i", round(frequency * 100))
    if markers is None:
        markers = b"\x00\x00\x00" if line == 1 else b"\x01\x01\x01"
    frame[37:40] = markers
    return bytes(frame)


def v2_block(
    voltage,
    current,
    power,
    energy,
    frequency=60.0,
    relay=0,
    neutral=0,
    error=0,
    backlight=3,
):
    block = bytearray(34)
    block[0:4] = scaled(voltage)
    block[4:8] = scaled(current)
    block[8:12] = scaled(power)
    block[12:16] = scaled(energy)
    block[24] = backlight
    block[25] = neutral
    block[26] = 0
    block[27] = 42
    block[28:32] = scaled(frequency, 100)
    block[32] = error
    block[33] = relay
    return block


def v2_frame(*blocks):
    payload = b"".join(blocks)
    return V2_HEADER + bytes([1, 1, 1]) + struct.pack(">H", len(payload)) + payload + V2_END


def v2_packet(message_type, payload=b""):
    return (
        V2_HEADER
        + bytes([1, 1, message_type])
        + struct.pack(">H", len(payload))
        + payload
        + V2_END
    )


def test_name_matching_covers_v1_v2_and_boosters():
    assert HughesHandler.match_name("PMD123")
    assert HughesHandler.match_name("WD_V5_123")
    assert HughesHandler.match_name("WD_E9_123")
    assert not HughesHandler.match_name("EasyTouch-123")


def test_v1_two_line_frames_build_combined_state():
    handler = HughesHandler("AA:BB", {"_device_name": "PMD123"})
    first = handler.parse_status(v1_frame(1, energy=100.0))
    second = handler.parse_status(v1_frame(2, voltage=120.1, current=5.0, power=600.5, energy=50.0))

    assert first["protocol"] == "V1"
    assert first["is_50a"] is False
    assert second["is_50a"] is True
    assert second["voltage_l2"] == 120.1
    assert second["energy_kwh"] == 150.0
    assert second["supports_control"] is False


def test_v1_unrecognised_markers_are_treated_as_line_one():
    handler = HughesHandler("AA:BB", {"_device_name": "PMS123456789ABCE3XX"})
    state = handler.parse_status(v1_frame(1, markers=b"\x02\x07\x00", voltage=118.9))

    assert state["voltage_l1"] == 118.9
    assert state["is_50a"] is False


def test_v1_legacy_hardware_inverts_line_markers_and_drops_error_byte():
    handler = HughesHandler("AA:BB", {"_device_name": "PMD123456789ABCE2XX"})
    first = handler.parse_status(
        v1_frame(2, markers=b"\x00\x00\x00", voltage=119.5, error=3)
    )
    second = handler.parse_status(v1_frame(1, markers=b"\x01\x01\x01", voltage=121.0))

    assert first["voltage_l2"] == 119.5
    assert first["error_code"] is None
    assert first["error_code_l2"] is None
    assert second["voltage_l1"] == 121.0
    assert second["is_50a"] is True


def test_v1_legacy_single_line_keeps_zero_markers_on_line_one():
    handler = HughesHandler("AA:BB", {"_device_name": "PMS123456789ABCE2XX"})
    state = handler.parse_status(v1_frame(1, markers=b"\x00\x00\x00", voltage=120.4))

    assert state["voltage_l1"] == 120.4
    assert state["is_50a"] is False


def test_v1_current_hardware_reports_error_byte():
    handler = HughesHandler("AA:BB", {"_device_name": "PMS123456789ABCE3XX"})
    state = handler.parse_status(v1_frame(1, error=13))

    assert state["error_code"] == 13
    assert state["error_description"] == "Over temperature - internal temperature exceeded 74C"


def test_v2_30a_frame_and_state_message():
    handler = HughesHandler("AA:BB", {"_device_name": "WD_V5_123"})
    state = handler.parse_status(v2_frame(v2_block(121.4, 14.3, 1735.0, 142.3)))

    assert state["protocol"] == "V2"
    assert state["is_50a"] is False
    assert state["voltage_l1"] == 121.4
    assert state["energy_l1"] == 142.3
    assert state["error_code_l1"] == 0
    assert state["relay_status"] == 0
    assert state["output_voltage"] is None
    assert state["supports_control"] is True
    message = handler.state_messages(state)[0]
    assert message.topic == "librecoach/ble/hughes/aa:bb/state"
    assert json.loads(message.payload)["power_l1"] == 1735.0


def test_v2_50a_frame_decodes_line_two():
    handler = HughesHandler("AA:BB", {"_device_name": "WD_E6_123"})
    state = handler.parse_status(v2_frame(
        v2_block(121.4, 14.3, 1735.0, 100.0),
        v2_block(
            120.2, 8.1, 973.6, 42.3, frequency=59.9, error=8, neutral=1
        ),
    ))

    assert state["is_50a"] is True
    assert state["voltage_l2"] == 120.2
    assert state["frequency_l2"] == 59.9
    assert state["energy_l1"] == 100.0
    assert state["energy_l2"] == 42.3
    assert state["energy_kwh"] == 142.3
    assert state["combined_power"] == 2708.6
    assert state["error_code_l1"] == 0
    assert state["error_code_l2"] == 8
    assert state["error_code"] == 8
    assert state["error_description_l2"] == "No neutral circuit detected"
    assert state["neutral_detection_l1"] == 0
    assert state["neutral_detection_l2"] == 1
    assert state["neutral_detection"] == 1


def test_booster_fields_are_gated_by_device_model():
    block = v2_block(121.0, 10.0, 1210.0, 20.0)
    block[20:24] = scaled(118.5)
    block[26] = 1
    block[27] = 55

    booster = HughesHandler("AA:BB", {"_device_name": "WD_V8_123"})
    normal = HughesHandler("AA:CC", {"_device_name": "WD_V5_123"})
    booster_state = booster.parse_status(v2_frame(block))
    normal_state = normal.parse_status(v2_frame(block))

    assert booster_state["has_booster"] is True
    assert booster_state["output_voltage"] == 118.5
    assert booster_state["boost_mode"] == 1
    assert booster_state["temperature"] == 55
    assert normal_state["output_voltage"] is None


def test_v2_command_packet_and_ack():
    handler = HughesHandler("AA:BB", {"_device_name": "WD_V5_123"})

    class Client:
        async def write_gatt_char(self, characteristic, packet, response=False):
            assert characteristic == V2_CHAR_UUID
            command = packet[6]
            ack = V2_HEADER + bytes([1, packet[5], command, 0, 1, 1]) + V2_END
            handler._on_v2_notification(None, ack)

    assert run(handler.handle_command(Client(), {"command": "relay", "value": True})) is True


def test_v2_backlight_and_error_history_commands_update_cached_state():
    handler = HughesHandler("AA:BB", {"_device_name": "WD_V5_123"})
    handler._cache_state(handler.parse_status(v2_frame(
        v2_block(121.4, 14.3, 1735.0, 142.3, backlight=2)
    )))
    commands = []

    class Client:
        async def write_gatt_char(self, characteristic, packet, response=False):
            commands.append((packet[6], packet[9:-2]))
            handler._on_v2_notification(
                None, v2_packet(packet[6], b"\x01")
            )

    updated = run(handler.handle_command(Client(), {"command": "backlight", "value": 5}))
    assert commands[-1] == (V2_SET_BACKLIGHT, b"\x05")
    assert updated["backlight"] == 5

    handler._error_history = [{"record_id": 7}]
    handler._update_cached_state(
        error_history=list(handler._error_history), error_history_count=1
    )
    updated = run(handler.handle_command(Client(), {"command": "clear_error_history"}))
    assert commands[-1] == (V2_ERROR_DELETE, b"\xff")
    assert updated["error_history"] == []
    assert updated["error_history_count"] == 0


def test_v2_rejects_invalid_backlight_values_without_writing():
    handler = HughesHandler("AA:BB", {"_device_name": "WD_V5_123"})

    class Client:
        async def write_gatt_char(self, characteristic, packet, response=False):
            raise AssertionError("invalid control must not be written")

    assert run(handler.handle_command(Client(), {"command": "backlight", "value": 6})) is False
    assert run(handler.handle_command(Client(), {"command": "backlight", "value": 2.5})) is False


def test_v2_error_report_populates_history_with_ongoing_record():
    handler = HughesHandler("AA:BB", {"_device_name": "WD_V5_123"})
    handler._on_v2_notification(
        None, v2_frame(v2_block(121.4, 14.3, 1735.0, 142.3))
    )
    record = bytearray(16)
    record[2] = 7
    record[4:9] = bytes([26, 8, 19, 14, 5])
    record[9] = 0x55
    record[15] = 8

    handler._on_v2_notification(None, v2_packet(V2_ERROR_REPORT, record))

    history = handler._latest_state["error_history"]
    assert handler._latest_state["error_history_count"] == 1
    assert history == [{
        "record_id": 7,
        "error_code": 8,
        "description": "No neutral circuit detected",
        "start_time": "2026-08-19 14:05",
        "end_time": "Ongoing",
    }]


def test_v2_oversized_length_resynchronizes_to_following_valid_frame():
    handler = HughesHandler("AA:BB", {"_device_name": "WD_V5_123"})
    bogus = V2_HEADER + bytes([1, 1, 1]) + struct.pack(">H", MAX_V2_PAYLOAD + 1)
    valid = v2_frame(v2_block(119.8, 4.2, 503.2, 8.1))

    handler._on_v2_notification(None, bogus + valid)

    assert handler._latest_state["voltage_l1"] == 119.8
    assert handler._buffer == b""


def test_v2_clock_payload_uses_calendar_month_and_authentication_syncs_it():
    assert HughesHandler.clock_payload(datetime(2026, 8, 19, 14, 5, 6)) == bytes([
        26, 8, 19, 14, 5, 6,
    ])
    handler = HughesHandler("AA:BB", {"_device_name": "WD_V5_123"})
    commands = []

    class Client:
        async def start_notify(self, characteristic, callback):
            self.callback = callback

        async def write_gatt_char(self, characteristic, packet, response=False):
            if packet == b"!%!%,protocol,open,":
                self.callback(
                    None, v2_frame(v2_block(121.4, 14.3, 1735.0, 142.3))
                )
                return
            commands.append(packet[6])
            self.callback(None, v2_packet(packet[6], b"\x01"))

    assert run(handler.authenticate(Client())) is True
    assert commands == [V2_SET_TIME]


def test_hughes_change_aware_publishing_uses_deadbands_and_heartbeat():
    handler = HughesHandler("AA:BB", {"_device_name": "WD_V5_123"})
    state = handler.parse_status(v2_frame(v2_block(120.0, 10.0, 1200.0, 10.0)))

    assert len(handler.state_messages(state)) == 1
    assert handler.state_messages(dict(state)) == []
    assert handler.state_messages({**state, "voltage_l1": 120.1}) == []
    assert len(handler.state_messages({**state, "error_code_l1": 8})) == 1

    handler._last_publish_time -= 31
    assert len(handler.state_messages({**state, "error_code_l1": 8})) == 1
    assert handler.poll_interval == 1


def test_disabling_hughes_only_tears_down_hughes_devices():
    conftest.reset_recorders()

    class Hass:
        pass

    class Handler:
        def __init__(self, device_type):
            self._device_type = device_type

        def device_type(self):
            return self._device_type

    manager = BleBridgeManager(Hass(), {}, {"microair", "hughes"})
    manager._active_devices = {
        "aa": {"handler": Handler("hughes"), "task": None, "client": None},
        "bb": {"handler": Handler("microair"), "task": None, "client": None},
    }

    run(manager.disable_device_type("hughes"))

    assert "aa" not in manager._active_devices
    assert "bb" in manager._active_devices
    assert manager._enabled_types == {"microair"}
    assert any(
        item["topic"] == "librecoach/ble/hughes/aa/available"
        and item["payload"] == "offline"
        for item in conftest.PUBLISHED
    )


def test_command_topic_must_match_handler_type():
    class Hass:
        pass

    class Handler:
        def device_type(self):
            return "microair"

        async def handle_command(self, client, command):
            raise AssertionError("mismatched command must not be dispatched")

    class Message:
        topic = "librecoach/ble/hughes/aa/set"
        payload = "{}"

    manager = BleBridgeManager(Hass(), {}, {"microair", "hughes"})
    manager._active_devices["aa"] = {"handler": Handler()}
    run(manager._on_mqtt_command(Message()))
