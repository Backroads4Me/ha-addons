import json
import asyncio
import logging
from .base import BleDeviceHandler

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
    10: "auto", 11: "auto", 12: "heat",
}

HEAT_TYPE_REVERSE = {
    5: "Heat Pump", 4: "Furnace", 3: "Gas Furnace",
    7: "Heat Strip", 12: "Electric Heat",
}

FAN_MODE_MAP = {0: "auto", 1: "low", 2: "high", 128: "auto"}


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
        """Authenticate with device. Called by bridge after connection."""
        if not self._password:
            return True
        await client.write_gatt_char(
            UUIDS["passwordCmd"],
            self._password.encode("utf-8"),
            response=True,
        )
        await asyncio.sleep(1.0)
        return True

    async def poll(self, client) -> dict | None:
        """Send Get Status, read and parse response."""
        raw = await self._request_json(client, {"Type": "Get Status"})
        if not raw:
            return None

        parsed = self.parse_status(raw)

        # Check for new zones and fetch their config (run once per newly discovered zone)
        if "zones" in parsed:
            found_zones = []
            for z in parsed["zones"].keys():
                try:
                    found_zones.append(int(z))
                except Exception:
                    pass

            missing_configs = [z for z in found_zones if z not in self._zone_configs]
            if missing_configs:
                for zone in missing_configs:
                    await asyncio.sleep(2.0)
                    resp = await self._request_json(client, {"Type": "Get Config", "Zone": zone})
                    if resp and resp.get("Type") == "Response" and resp.get("RT") == "Config":
                        cfg_str = resp.get("CFG", "{}")
                        cfg_data = json.loads(cfg_str) if isinstance(cfg_str, str) else cfg_str
                        self._zone_configs[zone] = {
                            "MAV": cfg_data.get("MAV", 0),
                            "FA": cfg_data.get("FA", [0] * 16),
                            "SPL": cfg_data.get("SPL", [60, 85, 50, 85]),
                            "MA": cfg_data.get("MA", [0] * 16),
                        }

        return parsed

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
                    "dry_fan_mode_num": info[9],
                    "mode_num": info[10],
                    "furnace_fan_mode_num": info[11],
                    "facePlateTemperature": info[12],
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

    def _select_fan_mode(self, zone_status):
        mode = zone_status.get("mode")
        if mode == "cool":
            return zone_status.get("cool_fan_mode_num", 0)
        if mode == "heat":
            return zone_status.get("heat_fan_mode_num", zone_status.get("furnace_fan_mode_num", 0))
        if mode == "auto":
            return zone_status.get("auto_fan_mode_num", 0)
        if mode == "dry":
            return zone_status.get("dry_fan_mode_num", 0)
        if mode == "fan_only":
            return zone_status.get("fan_mode_num", 0)
        return 0
