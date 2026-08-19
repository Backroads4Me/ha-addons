"""Hughes Power Watchdog BLE protocol handler."""

import asyncio
import json
import logging
import struct
import time
from datetime import datetime

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
V2_ERROR_REPORT = 0x02
V2_ENERGY_RESET = 0x03
V2_ERROR_DELETE = 0x05
V2_SET_TIME = 0x06
V2_SET_BACKLIGHT = 0x07
V2_SET_OPEN = 0x0B
V2_NEUTRAL_DETECTION = 0x0D
V2_RELAY_ON = 0x01
V2_RELAY_OFF = 0x02
V2_NEUTRAL_ENABLE = 0x00
V2_NEUTRAL_DISABLE = 0x01

NOTIFICATION_TIMEOUT = 60
INITIAL_DATA_TIMEOUT = 5
COMMAND_ACK_TIMEOUT = 5
MAX_V2_PAYLOAD = 8192
MAX_V2_BUFFER = 2 * (MAX_V2_PAYLOAD + 11)
HUGHES_POLL_INTERVAL = 1
PUBLISH_HEARTBEAT = 30

# Changes at or above these thresholds are published before the heartbeat.
# Faults and discrete controls bypass the thresholds and publish immediately.
PUBLISH_DEADBANDS = {
    "voltage_l1": 0.2,
    "voltage_l2": 0.2,
    "current_l1": 0.2,
    "current_l2": 0.2,
    "power_l1": 25.0,
    "power_l2": 25.0,
    "combined_power": 25.0,
    "frequency_l1": 0.1,
    "frequency_l2": 0.1,
    "energy_l1": 0.01,
    "energy_l2": 0.01,
    "energy_kwh": 0.01,
    "output_voltage": 0.2,
    "temperature": 1.0,
}
IMMEDIATE_PUBLISH_FIELDS = (
    "protocol",
    "is_50a",
    "error_code_l1",
    "error_code_l2",
    "relay_status",
    "neutral_detection",
    "backlight",
    "boost_mode",
    "error_history",
)

# V1 hardware revision, from name[15:17]. E2 predates the error-code byte and
# uses inverted line markers; E3/E4 share the current behaviour.
V1_LEGACY_HW = "E2"
V1_DEFAULT_HW = "E3"
V1_L2_MARKER = b"\x01\x01\x01"
V1_LEGACY_L2_MARKER = b"\x00\x00\x00"

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
    13: "Over temperature - internal temperature exceeded 74C",
    14: "Voltage booster malfunction",
}


class HughesHandler(BleDeviceHandler):
    """Decode Hughes V1/V2 push notifications and encode V2 controls."""

    poll_interval = HUGHES_POLL_INTERVAL

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
        self._error_history = []
        self._last_published_state = None
        self._last_publish_time = 0.0
        # V1 line-marker routing depends on the hardware revision and on whether
        # the unit is dual-line, both of which the advertised name encodes.
        name = self.device_name
        self._v1_hardware = name[15:17] if len(name) >= 17 else V1_DEFAULT_HW
        self._v1_legacy = self._v1_hardware == V1_LEGACY_HW
        self._v1_dual_line = name[2:3] == "D"

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
            await client.write_gatt_char(V2_CHAR_UUID, V2_INIT, response=True)
        await asyncio.wait_for(self._initial_data.wait(), timeout=INITIAL_DATA_TIMEOUT)
        if self.protocol == "V2":
            try:
                await self._sync_clock(client)
            except Exception as exc:
                # Telemetry remains useful when a firmware revision does not
                # acknowledge the optional clock command.
                _LOGGER.warning("Hughes clock synchronization failed: %s", exc)
        return True

    async def poll(self, client) -> dict | None:
        """Return the most recent notification while the push stream is fresh."""
        if not self._latest_state:
            return None
        if time.monotonic() - self._last_notification > NOTIFICATION_TIMEOUT:
            return None
        return dict(self._latest_state)

    async def handle_command(self, client, command: dict) -> dict | bool:
        """Handle supported Gen2 controls and return changed cached state."""
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
        elif action == "backlight":
            level = self._backlight_level(value)
            if level is None:
                return False
            payload = bytes([level])
            command_id = V2_SET_BACKLIGHT
        elif action in ("clear_error_history", "delete_errors"):
            payload = b"\xff"
            command_id = V2_ERROR_DELETE
        else:
            return False

        success = await self._send_v2_command(client, command_id, payload)
        if not success:
            return False

        if action == "backlight":
            return self._update_cached_state(backlight=level) or True
        if action in ("clear_error_history", "delete_errors"):
            self._error_history = []
            return self._update_cached_state(
                error_history=[], error_history_count=0
            ) or True
        return True

    async def _send_v2_command(self, client, command_id: int, payload: bytes) -> bool:
        """Send one serialized Gen2 command and wait for its ResultRes packet."""
        packet = self.build_v2_command(command_id, payload)
        loop = asyncio.get_running_loop()
        self._pending_ack = loop.create_future()
        self._pending_ack_command = command_id
        try:
            await client.write_gatt_char(V2_CHAR_UUID, packet, response=False)
            return await asyncio.wait_for(
                self._pending_ack, timeout=COMMAND_ACK_TIMEOUT
            )
        finally:
            self._pending_ack = None
            self._pending_ack_command = None

    async def _sync_clock(self, client) -> bool:
        """Set the Watchdog clock used by stored error-history timestamps."""
        return await self._send_v2_command(
            client, V2_SET_TIME, self.clock_payload(datetime.now())
        )

    @staticmethod
    def clock_payload(now: datetime) -> bytes:
        """Encode Gen2 SetTime as year since 2000 and a 1-based month."""
        year = now.year - 2000
        if not 0 <= year <= 255:
            raise ValueError("Hughes clock year is outside the Gen2 wire range")
        return bytes([year, now.month, now.day, now.hour, now.minute, now.second])

    @staticmethod
    def _backlight_level(value) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            level = int(value)
        except (TypeError, ValueError):
            return None
        if isinstance(value, float) and not value.is_integer():
            return None
        return level if 0 <= level <= 5 else None

    def parse_status(self, raw: bytes) -> dict:
        """Parse one complete V1 or V2 telemetry frame."""
        if self.protocol == "V1":
            return self._parse_v1(raw)
        return self._parse_v2(raw)

    def state_messages(self, parsed: dict) -> list[StateMessage]:
        if not self._should_publish(parsed):
            return []
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
        if len(self._buffer) > MAX_V2_BUFFER:
            _LOGGER.warning(
                "Hughes Gen2 receive buffer exceeded %d bytes; clearing",
                MAX_V2_BUFFER,
            )
            self._buffer.clear()
            return
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
            if payload_length > MAX_V2_PAYLOAD:
                _LOGGER.warning(
                    "Ignoring Hughes Gen2 payload length %d", payload_length
                )
                del self._buffer[:4]
                continue
            frame_length = 9 + payload_length + 2
            if len(self._buffer) < frame_length:
                return
            frame = bytes(self._buffer[:frame_length])
            del self._buffer[:frame_length]
            if frame[-2:] != V2_END:
                continue
            message_type = frame[6]
            if message_type == V2_ERROR_REPORT:
                self._error_history = self._parse_v2_error_history(frame)
                self._update_cached_state(
                    error_history=list(self._error_history),
                    error_history_count=len(self._error_history),
                )
                continue
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

    def _update_cached_state(self, **changes) -> dict | None:
        """Merge command or history results without inventing telemetry."""
        if not self._latest_state:
            return None
        state = {**self._latest_state, **changes}
        self._latest_state = state
        self._last_notification = time.monotonic()
        return dict(state)

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
            # The error byte carries no data on E2 hardware.
            "error_code": None if self._v1_legacy else raw[19],
        }
        if self._v1_line_number(raw[37:40]) == 2:
            self._line_2 = line
        else:
            self._line_1 = line
        return self._build_state("V1")

    def _v1_line_number(self, markers: bytes) -> int:
        """Resolve which AC line a V1 frame describes, per PROTOCOL-GEN1.md."""
        if self._v1_legacy:
            if markers == V1_LEGACY_L2_MARKER:
                return 2 if self._v1_dual_line else 1
            # A non-zero marker on E2 hardware proves the unit is dual-line.
            self._v1_dual_line = True
            return 1
        return 2 if markers == V1_L2_MARKER else 1

    def _parse_v2(self, raw: bytes) -> dict:
        if len(raw) < 27 or raw[:4] != V2_HEADER or raw[-2:] != V2_END:
            return {}
        payload_length = struct.unpack(">H", raw[7:9])[0]
        if payload_length not in (34, 68) or len(raw) != payload_length + 11:
            return {}
        self._line_1 = self._parse_v2_line(raw, 9)
        self._line_2 = self._parse_v2_line(raw, 43) if payload_length == 68 else None
        state = self._build_state("V2")
        state.update({
            "relay_status": raw[42],
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
            "error_code": raw[offset + 32],
            "neutral_detection": raw[offset + 25],
        }

    def _build_state(self, protocol: str) -> dict:
        line_1 = self._line_1 or {}
        line_2 = self._line_2 or {}
        energy_l1 = line_1.get("energy")
        energy_l2 = line_2.get("energy")
        energy = energy_l1
        if energy is not None and energy_l2 is not None:
            energy += energy_l2
        error_l1 = line_1.get("error_code")
        error_l2 = line_2.get("error_code")
        available_errors = [
            code for code in (error_l1, error_l2) if code is not None
        ]
        active_error = next(
            (code for code in available_errors if code != 0),
            available_errors[0] if available_errors else None,
        )
        neutral_l1 = line_1.get("neutral_detection")
        neutral_l2 = line_2.get("neutral_detection")
        available_neutral = [
            value for value in (neutral_l1, neutral_l2) if value is not None
        ]
        neutral_status = next(
            (value for value in available_neutral if value != 0),
            available_neutral[0] if available_neutral else None,
        )
        state = {
            "device_name": self.device_name,
            "protocol": protocol,
            "is_50a": bool(self._line_2),
            "voltage_l1": line_1.get("voltage"),
            "current_l1": line_1.get("current"),
            "power_l1": line_1.get("power"),
            "frequency_l1": line_1.get("frequency"),
            "energy_l1": energy_l1,
            "error_code_l1": error_l1,
            "error_description_l1": self._error_description(error_l1),
            "neutral_detection_l1": neutral_l1,
            "voltage_l2": line_2.get("voltage"),
            "current_l2": line_2.get("current"),
            "power_l2": line_2.get("power"),
            "frequency_l2": line_2.get("frequency"),
            "energy_l2": energy_l2,
            "error_code_l2": error_l2,
            "error_description_l2": self._error_description(error_l2),
            "neutral_detection_l2": neutral_l2,
            "energy_kwh": energy,
            "combined_power": (
                line_1.get("power", 0) + line_2.get("power", 0)
                if line_1 else None
            ),
            "error_code": active_error,
            "error_description": self._error_description(active_error),
            "neutral_detection": neutral_status,
            "supports_control": protocol == "V2",
            "supports_error_history": protocol == "V2",
            "has_booster": self.has_booster,
            "error_history": list(self._error_history),
            "error_history_count": len(self._error_history),
        }
        return state

    @staticmethod
    def _error_description(error_code) -> str | None:
        if error_code is None:
            return None
        return ERRORS.get(error_code, f"Unknown Error ({error_code})")

    def _parse_v2_error_history(self, frame: bytes) -> list[dict]:
        """Decode 16-byte Gen2 ErrorReport records."""
        payload_length = struct.unpack(">H", frame[7:9])[0]
        payload = frame[9:9 + payload_length]
        records = []
        for offset in range(0, len(payload) - (len(payload) % 16), 16):
            record = payload[offset:offset + 16]
            end_time = (
                "Ongoing"
                if record[9] == 0x55
                else self._format_error_time(record[9:14])
            )
            error_code = record[15]
            records.append({
                "record_id": record[2],
                "error_code": error_code,
                "description": self._error_description(error_code),
                "start_time": self._format_error_time(record[4:9]),
                "end_time": end_time,
            })
        return records

    @staticmethod
    def _format_error_time(value: bytes) -> str:
        year, month, day, hour, minute = value
        return f"20{year:02d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}"

    def _should_publish(self, parsed: dict) -> bool:
        """Publish meaningful changes immediately and a complete heartbeat."""
        now = time.monotonic()
        previous = self._last_published_state
        publish = previous is None or now - self._last_publish_time >= PUBLISH_HEARTBEAT

        if not publish:
            publish = any(
                previous.get(field) != parsed.get(field)
                for field in IMMEDIATE_PUBLISH_FIELDS
            )

        if not publish:
            for field, threshold in PUBLISH_DEADBANDS.items():
                before = previous.get(field)
                after = parsed.get(field)
                if before is None or after is None:
                    if before != after:
                        publish = True
                        break
                    continue
                if abs(after - before) >= threshold:
                    publish = True
                    break

        if publish:
            self._last_published_state = json.loads(json.dumps(parsed))
            self._last_publish_time = now
        return publish
