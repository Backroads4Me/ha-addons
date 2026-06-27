import json
import asyncio
import logging

from bleak import BleakError

from ..const import TOPIC_STATE
from .base import BleDeviceHandler, StateMessage, AuthenticationError

_LOGGER = logging.getLogger(__name__)

# --- MicroAir-specific constants ---

UUIDS = {
    "service":     "000000ff-0000-1000-8000-00805f9b34fb",
    "passwordCmd": "0000dd01-0000-1000-8000-00805f9b34fb",
    "jsonCmd":     "0000ee01-0000-1000-8000-00805f9b34fb",
    "jsonReturn":  "0000ff01-0000-1000-8000-00805f9b34fb",
}

MODE_NUM_TO_MODE = {
    0: "off", 1: "fan_only", 2: "cool", 3: "heat", 4: "heat",
    5: "heat", 6: "dry", 7: "heat", 8: "auto", 9: "auto",
    10: "auto", 11: "auto", 12: "heat", 13: "heat",
}

HEAT_TYPE_REVERSE = {
    5: "Heat Pump", 4: "Furnace", 3: "Gas Furnace",
    7: "Heat Strip", 12: "Electric Heat", 13: "Gas Heat",
}

GAS_HEAT_MODES = {3, 4, 13}

FAN_MODE_MAP = {
    0: "auto",
    1: "low",
    2: "medium",
    3: "high",
    128: "auto",
}

UNAVAILABLE_TEMPERATURE = -32768

FAULT_DESCRIPTIONS = {
    0: "No fault",
    1: "No communication",
    2: "Bad remote sensor",
    3: "Bad outside sensor",
    4: "Bad freeze sensor",
    5: "Freeze detected",
    6: "Bad humidity sensor",
    7: "No AC power",
    8: "Invalid config",
    9: "Low DC voltage",
    10: "Bad indoor sensor",
    11: "Inside coil sensor fault",
    12: "Outside coil sensor fault",
    13: "Low refrigerant",
    14: "Undefined fault",
}


class MicroAirHandler(BleDeviceHandler):

    def __init__(self, address, config):
        self.address = address
        self._password = (config.get("microair_password") or "").strip()
        self._email = (config.get("microair_email") or "").strip()
        self._zone_configs = {}

    @staticmethod
    def device_type() -> str:
        return "microair"

    @staticmethod
    def match_name(name: str) -> bool:
        return name.startswith("EasyTouch")

    async def _request_json(self, client, command: dict) -> dict | None:
        """Helper to write JSON to jsonCmd and read from jsonReturn with delay."""
        cmd_bytes = json.dumps(command).encode("utf-8")
        await client.write_gatt_char(UUIDS["jsonCmd"], cmd_bytes, response=True)
        await asyncio.sleep(1.0)
        result = await client.read_gatt_char(UUIDS["jsonReturn"])
        if not result:
            return None
        return json.loads(bytes(result).decode("utf-8"))

    async def authenticate(self, client) -> bool:
        """Authenticate, then confirm access with a cheap read (B-5).

        A reachable device that returns a status without zone data means the
        password was rejected -> AuthenticationError. No response at all is a
        connectivity problem -> BleakError, which the bridge retries/backs off.
        """
        if self._password:
            await client.write_gatt_char(
                UUIDS["passwordCmd"],
                self._password.encode("utf-8"),
                response=True,
            )
            await asyncio.sleep(1.0)

        raw = await self._request_json(client, {"Type": "Get Status"})
        if raw is None:
            raise BleakError("No response during authentication")
        if not isinstance(raw, dict) or "Z_sts" not in raw:
            raise AuthenticationError("Micro-Air rejected credentials")
        return True

    async def poll(self, client) -> dict | None:
        """Send Get Status, read and parse response."""
        raw = await self._request_json(client, {"Type": "Get Status"})
        if not raw:
            return None

        parsed = self.parse_status(raw)

        # Omitting Zone selects the firmware path that returns MAV/FA/MA/SPL.
        # Per-zone requests can return only {"Zone": n}, which must not be cached
        # as a valid capability record because that prevents future retries.
        if parsed.get("zones") and not self._zone_configs:
            await asyncio.sleep(2.0)
            resp = await self._request_json(client, {"Type": "Get Config"})
            self._store_capability_config(resp)

        return parsed

    def _store_capability_config(self, response: dict | None) -> bool:
        """Store meaningful capability records from a Config response."""
        if not isinstance(response, dict):
            return False
        if response.get("Type") != "Response" or response.get("RT") != "Config":
            return False

        raw_cfg = response.get("CFG")
        if isinstance(raw_cfg, str):
            try:
                raw_cfg = json.loads(raw_cfg)
            except json.JSONDecodeError:
                return False
        if not isinstance(raw_cfg, dict):
            return False

        configs = []
        if "Zone" in raw_cfg:
            configs.append(raw_cfg)
        else:
            configs.extend(
                cfg for key, cfg in raw_cfg.items()
                if key.startswith("zone") and isinstance(cfg, dict)
            )

        stored = False
        for cfg in configs:
            try:
                zone = int(cfg.get("Zone", 0))
                mav = int(cfg.get("MAV", 0))
            except (TypeError, ValueError):
                continue
            if mav == 0:
                continue
            self._zone_configs[zone] = {
                "MAV": mav,
                "FA": cfg.get("FA", [0] * 16),
                "SPL": cfg.get("SPL", [60, 85, 50, 85]),
                "MA": cfg.get("MA", [0] * 16),
            }
            stored = True
        return stored

    async def handle_command(self, client, command: dict) -> dict | bool:
        """Write a command dict to the device and read back verified status."""
        cmd_bytes = json.dumps(command).encode("utf-8")
        await client.write_gatt_char(UUIDS["jsonCmd"], cmd_bytes, response=True)

        # Read back status for verification after Change commands
        if command.get("Type") == "Change":
            try:
                await asyncio.sleep(0.3)
                raw = await self._request_json(client, {"Type": "Get Status"})
                if raw:
                    return self.parse_status(raw)
            except Exception as exc:
                _LOGGER.debug("Post-command status read failed: %s", exc)

        return True

    def parse_status(self, status: dict) -> dict:
        """Parse EasyTouch JSON status into zones with readable state."""
        if not isinstance(status, dict):
            return {"available_zones": [0], "zones": {0: {}}}

        if "Z_sts" not in status:
            return {"available_zones": [0], "zones": {0: {}}}

        param = status.get("PRM", [])
        outdoor_temp = param[2] if len(param) > 2 else None
        if outdoor_temp == UNAVAILABLE_TEMPERATURE:
            outdoor_temp = None
        zone_data = {}
        available_zones = []

        for zone_key, info in status["Z_sts"].items():
            try:
                zone_num = int(zone_key)
            except (ValueError, TypeError):
                continue

            try:
                zone_status = {
                    "autoHeat_sp": info[0],
                    "autoCool_sp": info[1],
                    "cool_sp": info[2],
                    "heat_sp": info[3],
                    "dry_sp": info[4],
                    "rh_sp": info[5],
                    "fan_mode_num": info[6],
                    "cool_fan_mode_num": info[7],
                    "heat_fan_mode_num": info[8],
                    "auto_fan_mode_num": info[9],
                    # B-6: dry_fan_mode_num duplicates info[9] and does NOT prove a
                    # distinct dry fan setting exists. Retained as protocol/debug
                    # data only — never used to build an HA dry mode or fan control.
                    "dry_fan_mode_num": info[9],
                    # The upper nibble may carry protocol flags; consumers need
                    # the base operating mode only.
                    "mode_num": info[10] & 0x0F,
                    "furnace_fan_mode_num": info[11],
                    "facePlateTemperature": info[12],
                    "fault": info[14],
                    "active_state_num": info[15],
                }
            except (IndexError, TypeError):
                continue

            if outdoor_temp is not None:
                zone_status["outdoorTemperature"] = outdoor_temp

            if len(param) > 1:
                flags_register = param[1]
                system_power_on = (flags_register & 8) > 0
                zone_status["off"] = not system_power_on
                zone_status["on"] = system_power_on

            mode_num = zone_status.get("mode_num")
            zone_status["mode"] = MODE_NUM_TO_MODE.get(mode_num, "off")

            fault = zone_status["fault"]
            zone_status["fault_description"] = FAULT_DESCRIPTIONS.get(
                fault, f"Unknown fault ({fault})"
            )

            active_state = zone_status.get("active_state_num", 0)
            if active_state & 2:
                current_mode = "cool"
            elif active_state & 4:
                current_mode = "heat"
            elif active_state & 1:
                if zone_status["mode"] == "fan_only":
                    current_mode = "fan_only"
                else:
                    current_mode = "dry"
            elif active_state & 32:
                current_mode = "off"
            else:
                current_mode = "off"
            zone_status["current_mode"] = current_mode

            if mode_num in HEAT_TYPE_REVERSE:
                zone_status["heat_source"] = HEAT_TYPE_REVERSE[mode_num]

            fan_num = self._select_fan_mode(zone_status)
            zone_status["fan_mode_num"] = fan_num
            zone_status["fan_mode"] = FAN_MODE_MAP.get(fan_num, "auto")

            zone_data[zone_num] = zone_status
            available_zones.append(zone_num)

        if not available_zones:
            return {"available_zones": [0], "zones": {0: {}}}

        return {
            "available_zones": sorted(available_zones),
            "zones": zone_data,
            "zone_configs": self._zone_configs,
        }

    def state_messages(self, parsed: dict) -> list[StateMessage]:
        """Build the MQTT messages for a parsed status (B-2).

        Zone topic construction lives here so the bridge never inspects `zones`.
        Topics are unchanged from the previous bridge implementation:
          - state stream:  librecoach/ble/microair/{addr}/state        (per zone, not retained)
          - zone config:   librecoach/ble/microair/{addr}/zone/{n}/config (retained)
        """
        device_type = self.device_type()
        address = self.address
        state_topic = TOPIC_STATE.format(device_type=device_type, address=address)
        zones = parsed.get("zones", {}) or {}
        zone_configs = parsed.get("zone_configs", {}) or {}

        messages: list[StateMessage] = []
        for zone_num, zone_state in zones.items():
            if not isinstance(zone_state, dict):
                continue
            payload = dict(zone_state)
            payload["zone"] = zone_num
            messages.append(StateMessage(state_topic, json.dumps(payload), retain=False))

            # Non-numeric zone keys must not crash publishing.
            try:
                int_zone = int(zone_num)
            except (ValueError, TypeError):
                continue
            if int_zone in zone_configs:
                cfg_topic = f"librecoach/ble/{device_type}/{address}/zone/{zone_num}/config"
                messages.append(
                    StateMessage(cfg_topic, json.dumps(zone_configs[int_zone]), retain=True)
                )
        return messages

    def _select_fan_mode(self, zone_status):
        mode = zone_status.get("mode")
        if mode == "cool":
            return zone_status.get("cool_fan_mode_num", 0)
        if mode == "heat":
            if zone_status.get("mode_num") in GAS_HEAT_MODES:
                return zone_status.get("furnace_fan_mode_num", 0)
            return zone_status.get("heat_fan_mode_num", 0)
        if mode == "auto":
            return zone_status.get("auto_fan_mode_num", 0)
        if mode == "dry":
            return zone_status.get("dry_fan_mode_num", 0)
        if mode == "fan_only":
            return zone_status.get("fan_mode_num", 0)
        return 0
