"""Hughes Power Watchdog BLE protocol handler."""

import asyncio
import json
import logging
import struct
import time

from ..const import TOPIC_STATE
from .base import BleDeviceHandler, StateMessage

_LOGGER = logging.getLogger(__name__)

V1_PREFIXES = ("PMD", "PWS", "PMS")
V2_PREFIXES = tuple(
    f"WD_{kind}{model}" for kind in ("V", "E") for model in range(5, 10)
)
BOOSTER_MODELS = ("V8", "E8", "V9", "E9")

V1_TX_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"
V2_CHAR_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
V2_HEADER = b"$yw@"
V2_END = b"q!"
V2_INIT = b"!%!%,protocol,open,"
V2_DATA = 0x01
V2_ENERGY_RESET = 0x03
V2_SET_OPEN = 0x0B
V2_NEUTRAL_DETECTION = 0x0D
V2_RELAY_ON = 0x01
V2_RELAY_OFF = 0x02
V2_NEUTRAL_ENABLE = 0x00
V2_NEUTRAL_DISABLE = 0x01

NOTIFICATION_TIMEOUT = 60
INITIAL_DATA_TIMEOUT = 5

ERRORS = {
    0: "No Error",
    1: "Line 1 voltage exceeded 132V or dropped below 104V",
    2: "Line 2 voltage exceeded 132V or dropped below 104V",
    3: "Line 1 amperage rating exceeded",
    4: "Line 2 amperage rating exceeded",
    5: "Line 1 hot and neutral wires reversed",
    6: "Line 2 hot and neutral wires reversed",
    7: "Ground connection lost",
    8: "No neutral circuit detected",
    9: "Surge protection capacity depleted - replace surge board",
    11: "Frequency error (F1)",
    12: "Frequency error (F2)",
}


class HughesHandler(BleDeviceHandler):
    """Decode Hughes V1/V2 push notifications and encode V2 controls."""

    def __init__(self, address, config):
        self.address = address.lower()
        self.device_name = config.get("_device_name", "")
        self.protocol = "V1" if self.device_name.startswith(V1_PREFIXES) else "V2"
        self.has_booster = any(model in self.device_name for model in BOOSTER_MODELS)
        self._buffer = bytearray()
        self._latest_state = None
        self._last_notification = 0.0
        self._initial_data = asyncio.Event()
        self._sequence = 0
        self._pending_ack = None
        self._pending_ack_command = None
        self._line_1 = None
        self._line_2 = None

    @staticmethod
    def device_type() -> str:
        return "hughes"

    @staticmethod
    def match_name(name: str) -> bool:
        return name.startswith(V1_PREFIXES + V2_PREFIXES)

    async def authenticate(self, client) -> bool:
        """Subscribe to the device's push stream and wait for initial telemetry."""
        self._initial_data.clear()
        characteristic = V1_TX_UUID if self.protocol == "V1" else V2_CHAR_UUID
        callback = self._on_v1_notification if self.protocol == "V1" else self._on_v2_notification
        await client.start_notify(characteristic, callback)
        if self.protocol == "V2":
            await client.write_gatt_char(V2_CHAR_UUID, V2_INIT, response=False)
        await asyncio.wait_for(self._initial_data.wait(), timeout=INITIAL_DATA_TIMEOUT)
        return True

    async def poll(self, client) -> dict | None:
        """Return the most recent notification while the push stream is fresh."""
        if not self._latest_state:
            return None
        if time.monotonic() - self._last_notification > NOTIFICATION_TIMEOUT:
            return None
        return dict(self._latest_state)

    async def handle_command(self, client, command: dict) -> dict | bool:
        """Handle the supported V2 relay, neutral, and energy-reset controls."""
        if self.protocol != "V2" or not isinstance(command, dict):
            return False

        action = command.get("command") or command.get("action")
        value = command.get("value")
        if action == "relay":
            payload = bytes([V2_RELAY_ON if self._as_bool(value) else V2_RELAY_OFF])
            command_id = V2_SET_OPEN
        elif action in ("neutral", "neutral_detection"):
            payload = bytes([
                V2_NEUTRAL_ENABLE if self._as_bool(value) else V2_NEUTRAL_DISABLE
            ])
            command_id = V2_NEUTRAL_DETECTION
        elif action in ("reset", "reset_energy", "energy_reset"):
            payload = b""
            command_id = V2_ENERGY_RESET
        else:
            return False

        packet = self.build_v2_command(command_id, payload)
        loop = asyncio.get_running_loop()
        self._pending_ack = loop.create_future()
        self._pending_ack_command = command_id
        try:
            await client.write_gatt_char(V2_CHAR_UUID, packet, response=False)
            return await asyncio.wait_for(self._pending_ack, timeout=5.0)
        finally:
            self._pending_ack = None
            self._pending_ack_command = None

    def parse_status(self, raw: bytes) -> dict:
        """Parse one complete V1 or V2 telemetry frame."""
        if self.protocol == "V1":
            return self._parse_v1(raw)
        return self._parse_v2(raw)

    def state_messages(self, parsed: dict) -> list[StateMessage]:
        topic = TOPIC_STATE.format(device_type=self.device_type(), address=self.address)
        return [StateMessage(topic, json.dumps(parsed), retain=False)]

    @staticmethod
    def _as_bool(value) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "on", "yes")
        return bool(value)

    def build_v2_command(self, command: int, payload: bytes = b"") -> bytes:
        self._sequence = (self._sequence % 100) + 1
        return (
            V2_HEADER
            + bytes([0x01, self._sequence, command])
            + struct.pack(">H", len(payload))
            + payload
            + V2_END
        )

    def _on_v1_notification(self, sender, data):
        chunk = bytes(data)
        if chunk.startswith(b"\x01\x03\x20"):
            self._buffer.clear()
        self._buffer.extend(chunk)
        while len(self._buffer) >= 40:
            frame = bytes(self._buffer[:40])
            del self._buffer[:40]
            parsed = self._parse_v1(frame)
            if parsed:
                self._cache_state(parsed)

    def _on_v2_notification(self, sender, data):
        self._buffer.extend(bytes(data))
        while True:
            start = self._buffer.find(V2_HEADER)
            if start < 0:
                self._buffer.clear()
                return
            if start:
                del self._buffer[:start]
            if len(self._buffer) < 9:
                return
            payload_length = struct.unpack(">H", self._buffer[7:9])[0]
            frame_length = 9 + payload_length + 2
            if len(self._buffer) < frame_length:
                return
            frame = bytes(self._buffer[:frame_length])
            del self._buffer[:frame_length]
            if frame[-2:] != V2_END:
                continue
            message_type = frame[6]
            if message_type != V2_DATA:
                self._resolve_ack(message_type, frame[9:-2])
                continue
            parsed = self._parse_v2(frame)
            if parsed:
                self._cache_state(parsed)

    def _resolve_ack(self, command: int, payload: bytes):
        pending = self._pending_ack
        if (
            pending
            and not pending.done()
            and self._pending_ack_command == command
        ):
            pending.set_result(bool(payload and payload[0] == 0x01))

    def _cache_state(self, parsed: dict):
        self._latest_state = parsed
        self._last_notification = time.monotonic()
        self._initial_data.set()

    def _parse_v1(self, raw: bytes) -> dict:
        if len(raw) != 40 or raw[:3] != b"\x01\x03\x20":
            return {}
        voltage, current, power, energy = (
            struct.unpack(">i", raw[start:start + 4])[0] / 10000
            for start in (3, 7, 11, 15)
        )
        frequency = struct.unpack(">i", raw[31:35])[0] / 100
        line = {
            "voltage": voltage,
            "current": current,
            "power": power,
            "energy": energy,
            "frequency": frequency,
        }
        line_id = raw[37:40]
        if line_id == b"\x00\x00\x00":
            self._line_1 = line
        elif line_id == b"\x01\x01\x01":
            self._line_2 = line
        else:
            return {}
        return self._build_state("V1", raw[19])

    def _parse_v2(self, raw: bytes) -> dict:
        if len(raw) < 27 or raw[:4] != V2_HEADER or raw[-2:] != V2_END:
            return {}
        payload_length = struct.unpack(">H", raw[7:9])[0]
        if payload_length not in (34, 68) or len(raw) != payload_length + 11:
            return {}
        self._line_1 = self._parse_v2_line(raw, 9)
        self._line_2 = self._parse_v2_line(raw, 43) if payload_length == 68 else None
        error_code = raw[41]
        state = self._build_state("V2", error_code)
        state.update({
            "relay_status": raw[42],
            "neutral_detection": raw[34],
            "backlight": raw[33],
            "output_voltage": None,
            "temperature": None,
            "boost_mode": None,
        })
        if self.has_booster:
            state.update({
                "output_voltage": struct.unpack(">I", raw[29:33])[0] / 10000,
                "temperature": raw[36],
                "boost_mode": raw[35],
            })
        return state

    @staticmethod
    def _parse_v2_line(raw: bytes, offset: int) -> dict:
        return {
            "voltage": struct.unpack(">I", raw[offset:offset + 4])[0] / 10000,
            "current": struct.unpack(">I", raw[offset + 4:offset + 8])[0] / 10000,
            "power": struct.unpack(">I", raw[offset + 8:offset + 12])[0] / 10000,
            "energy": struct.unpack(">I", raw[offset + 12:offset + 16])[0] / 10000,
            "frequency": struct.unpack(">I", raw[offset + 28:offset + 32])[0] / 100,
        }

    def _build_state(self, protocol: str, error_code: int) -> dict:
        line_1 = self._line_1 or {}
        line_2 = self._line_2 or {}
        energy = line_1.get("energy")
        if energy is not None and line_2.get("energy") is not None:
            energy += line_2["energy"]
        state = {
            "protocol": protocol,
            "is_50a": bool(self._line_2),
            "voltage_l1": line_1.get("voltage"),
            "current_l1": line_1.get("current"),
            "power_l1": line_1.get("power"),
            "frequency_l1": line_1.get("frequency"),
            "voltage_l2": line_2.get("voltage"),
            "current_l2": line_2.get("current"),
            "power_l2": line_2.get("power"),
            "frequency_l2": line_2.get("frequency"),
            "energy_kwh": energy,
            "combined_power": (
                line_1.get("power", 0) + line_2.get("power", 0)
                if line_1 else None
            ),
            "error_code": error_code,
            "error_description": ERRORS.get(error_code, f"Unknown Error ({error_code})"),
            "supports_control": protocol == "V2",
            "has_booster": self.has_booster,
        }
        return state
