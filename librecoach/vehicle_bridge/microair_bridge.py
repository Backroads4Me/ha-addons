# SPDX-License-Identifier: GPL-3.0-only
#
# Micro-Air EasyTouch BLE bridge for LibreCoach
#
# Micro-Air BLE protocol reference (UUIDs, mode mappings, status structure):
#   https://github.com/k3vmcd/ha-micro-air-easytouch  (GPL-3.0)
#   https://github.com/mlefevre/ha_EasyTouchRV_MicroAir_MZ  (GPL-3.0)

import asyncio
import json
import logging

from dbus_next.aio import MessageBus
from dbus_next.constants import BusType
from dbus_next import Variant

log = logging.getLogger("vehicle_bridge.microair")

UUIDS = {
    "service": "000000ff-0000-1000-8000-00805f9b34fb",
    "passwordCmd": "0000dd01-0000-1000-8000-00805f9b34fb",
    "jsonCmd": "0000ee01-0000-1000-8000-00805f9b34fb",
    "jsonReturn": "0000ff01-0000-1000-8000-00805f9b34fb",
}

MODE_NUM_TO_MODE = {
    0: "off",
    1: "fan_only",
    2: "cool",
    3: "heat",
    4: "heat",
    5: "heat",
    6: "dry",
    7: "heat",
    8: "auto",
    9: "auto",
    10: "auto",
    11: "auto",
    12: "heat",
}

HEAT_TYPE_REVERSE = {
    5: "Heat Pump",
    4: "Furnace",
    3: "Gas Furnace",
    7: "Heat Strip",
    12: "Electric Heat",
}

FAN_MODE_MAP = {
    0: "off",
    1: "low",
    2: "high",
    3: "medium",
    128: "auto",
}


async def _get_bus():
    """Connect to the system D-Bus."""
    return await MessageBus(bus_type=BusType.SYSTEM).connect()


async def _get_interface(bus, path, iface_name):
    """Introspect a BlueZ object and return a specific interface proxy."""
    introspection = await bus.introspect("org.bluez", path)
    proxy = bus.get_proxy_object("org.bluez", path, introspection)
    return proxy.get_interface(iface_name)


class MicroAirBridge:
    def __init__(self, config, mqtt):
        self.config = config
        self.mqtt = mqtt
        self.name = "microair"
        self._stopping = False

        self._enabled = bool(config.get("microair_enabled", False))
        self._ble_enabled = bool(config.get("ble_enabled", True))
        self._password = (config.get("microair_password") or "").strip()
        self._email = (config.get("microair_email") or "").strip()
        self._scan_interval = int(config.get("ble_scan_interval", 30))

        self._devices = {}
        self._scan_task = None

    def is_enabled(self):
        return self._enabled

    async def start(self):
        if not self._ble_enabled:
            self.mqtt.publish("librecoach/bridge/ble", "disabled", retain=True)
            return

        self.mqtt.publish("librecoach/bridge/ble", "monitoring", retain=True)
        self.mqtt.subscribe("librecoach/ble/microair/+/set", self._on_command)
        self._scan_task = asyncio.create_task(self._scan_loop())

    async def stop(self):
        self._stopping = True
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
        for device in list(self._devices.values()):
            await device.stop()

    async def _scan_loop(self):
        """Monitor BlueZ for EasyTouch devices via InterfacesAdded signal.

        Uses passive monitoring (no StartDiscovery) to coexist with HA Core Bluetooth.
        Falls back to a single brief active scan if no devices are found within 30s,
        which handles the case where HA Core Bluetooth is disabled.
        """
        while not self._stopping:
            bus = None
            try:
                bus = await _get_bus()
                obj_manager = await _get_interface(bus, "/", "org.freedesktop.DBus.ObjectManager")

                # Check for devices already in BlueZ's object tree (from HA Core's scanner)
                objects = await obj_manager.call_get_managed_objects()
                for path, interfaces in objects.items():
                    self._handle_device(path, interfaces)

                # Subscribe to InterfacesAdded — fires when BlueZ discovers any new device
                obj_manager.on_interfaces_added(self._handle_device)

                # If no devices found yet, give passive discovery 30s before falling back
                # to a single brief active scan (needed when HA Core Bluetooth is disabled)
                if not self._devices:
                    await asyncio.sleep(30)
                    if not self._devices:
                        log.info("No MicroAir devices found passively, trying active scan...")
                        await self._do_discovery_scan(bus, obj_manager)

                # Keep bus alive to receive InterfacesAdded signals.
                # Periodic GetManagedObjects re-check catches devices that appeared
                # while the bus was reconnecting (no active scan needed).
                check_counter = 0
                while not self._stopping:
                    await asyncio.sleep(30)
                    check_counter += 1
                    if check_counter % 10 == 0:  # Every ~5 minutes
                        try:
                            objects = await obj_manager.call_get_managed_objects()
                            for path, interfaces in objects.items():
                                self._handle_device(path, interfaces)
                        except Exception:
                            break  # Bus dropped — reconnect outer loop

            except Exception as exc:
                log.warning("BLE monitor error: %s", exc)
                self.mqtt.publish("librecoach/bridge/ble", f"error: {exc}", retain=True)
            finally:
                if bus:
                    bus.disconnect()

            if not self._stopping:
                await asyncio.sleep(15)

    def _handle_device(self, path, interfaces):
        """Process a BlueZ device object — called from InterfacesAdded or GetManagedObjects."""
        if "org.bluez.Device1" not in interfaces:
            return
        props = interfaces["org.bluez.Device1"]
        name = props.get("Name", Variant("s", "")).value
        if not name.startswith("EasyTouch"):
            return
        address = props.get("Address", Variant("s", "")).value.lower()

        if address in self._devices:
            # Update stale device path if BlueZ re-registered the device under a new path.
            # This fixes the "interface not found on this object" error after adapter resets.
            existing = self._devices[address]
            if existing.device_path != path:
                log.info("MicroAir %s: device path updated %s -> %s", address, existing.device_path, path)
                existing.device_path = path
                existing._connected = False  # Force reconnect with fresh path
            return

        log.info("Discovered MicroAir device: %s (%s)", address, name)
        microair = _MicroAirDevice(
            address=address,
            device_path=path,
            name=name,
            password=self._password,
            email=self._email,
            mqtt=self.mqtt,
        )
        self._devices[address] = microair
        microair.start(self._scan_interval)

    async def _do_discovery_scan(self, bus, obj_manager):
        """Single brief active BLE scan to seed BlueZ's device cache.
        Only called when no devices were found via passive monitoring.
        """
        adapter_path = "/org/bluez/hci0"
        try:
            # Find first available adapter rather than hardcoding hci0
            objects = await obj_manager.call_get_managed_objects()
            for path, interfaces in objects.items():
                if "org.bluez.Adapter1" in interfaces:
                    adapter_path = path
                    break

            adapter = await _get_interface(bus, adapter_path, "org.bluez.Adapter1")
            await adapter.call_set_discovery_filter({
                "Transport": Variant("s", "le"),
                "UUIDs": Variant("as", [UUIDS["service"]]),
            })
            await adapter.call_start_discovery()
            await asyncio.sleep(10.0)
            try:
                await adapter.call_stop_discovery()
            except Exception:
                pass

            # Check for newly discovered devices
            objects = await obj_manager.call_get_managed_objects()
            for path, interfaces in objects.items():
                self._handle_device(path, interfaces)

        except Exception as exc:
            log.warning("Active discovery scan failed: %s", exc)

    async def _on_command(self, topic, payload):
        parts = topic.split("/")
        if len(parts) < 5:
            return
        mac = parts[3].lower()
        device = self._devices.get(mac)
        if not device:
            log.warning("MicroAir command for unknown device: %s", mac)
            return

        try:
            data = json.loads(payload) if isinstance(payload, str) else payload
        except json.JSONDecodeError:
            log.warning("Invalid MicroAir command payload: %s", payload)
            return

        if not isinstance(data, dict):
            log.warning("MicroAir command payload must be JSON object")
            return

        await device.send_command(data)


class _MicroAirDevice:
    def __init__(self, address, device_path, name, password, email, mqtt):
        self.address = address
        self.device_path = device_path
        self.name = name
        self.password = password
        self.email = email
        self.mqtt = mqtt

        self._stopping = False
        self._lock = asyncio.Lock()
        self._poll_task = None
        self._zone_configs = {}

        # Persistent connection state
        self._bus = None
        self._char_paths = {}  # uuid -> dbus path
        self._connected = False

    def start(self, interval):
        if self._poll_task and not self._poll_task.done():
            return
        self._poll_task = asyncio.create_task(self._poll_loop(interval))

    async def stop(self):
        self._stopping = True
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        await self._disconnect()

    async def _ensure_connected(self):
        """Connect to device if not already connected. Reuses bus and caches char paths."""
        if self._connected and self._bus:
            # Verify connection is still alive
            try:
                props_iface = await _get_interface(
                    self._bus, self.device_path, "org.freedesktop.DBus.Properties"
                )
                connected = await props_iface.call_get("org.bluez.Device1", "Connected")
                if connected.value:
                    return
            except Exception:
                pass
            # Connection lost, clean up
            log.debug("MicroAir %s: connection lost, reconnecting", self.address)
            await self._disconnect()

        self._bus = await _get_bus()
        device_iface = await _get_interface(self._bus, self.device_path, "org.bluez.Device1")
        props_iface = await _get_interface(
            self._bus, self.device_path, "org.freedesktop.DBus.Properties"
        )

        await device_iface.call_connect()
        log.debug("MicroAir %s: BLE connect requested", self.address)

        # Wait for ServicesResolved
        for _ in range(30):
            resolved = await props_iface.call_get("org.bluez.Device1", "ServicesResolved")
            if resolved.value:
                break
            await asyncio.sleep(0.5)
        else:
            raise TimeoutError("GATT services did not resolve within 15s")

        # Give the stack a moment to stabilize after service resolution
        await asyncio.sleep(2.0)

        # Cache characteristic paths
        self._char_paths = {}
        obj_manager = await _get_interface(self._bus, "/", "org.freedesktop.DBus.ObjectManager")
        objects = await obj_manager.call_get_managed_objects()
        for path, interfaces in objects.items():
            if not path.startswith(self.device_path + "/"):
                continue
            if "org.bluez.GattCharacteristic1" not in interfaces:
                continue
            props = interfaces["org.bluez.GattCharacteristic1"]
            char_uuid = props.get("UUID", Variant("s", "")).value.lower()
            self._char_paths[char_uuid] = path

        # Send password once after connect
        if self.password:
            pw_path = self._char_paths.get(UUIDS["passwordCmd"])
            if pw_path:
                char_iface = await _get_interface(
                    self._bus, pw_path, "org.bluez.GattCharacteristic1"
                )
                await char_iface.call_write_value(
                    self.password.encode("utf-8"), {}
                )
                await asyncio.sleep(1.0)
                log.debug("MicroAir %s: password sent", self.address)

        self._connected = True
        log.info("MicroAir %s: connected and GATT resolved", self.address)

    async def _disconnect(self):
        """Disconnect and clean up bus."""
        self._connected = False
        self._char_paths = {}
        if self._bus:
            try:
                device_iface = await _get_interface(
                    self._bus, self.device_path, "org.bluez.Device1"
                )
                await device_iface.call_disconnect()
            except Exception:
                pass
            try:
                self._bus.disconnect()
            except Exception:
                pass
            self._bus = None

    async def _poll_loop(self, interval):
        failure_count = 0
        while not self._stopping:
            try:
                status = await self._request_json({"Type": "Get Status"})
                if not status:
                    raise Exception("No status response")

                parsed = _parse_status(status)

                # If we discovered new zones in the status, ensure we have configs for them
                if "zones" in parsed:
                    found_zones = []
                    for z in parsed["zones"].keys():
                        try:
                            found_zones.append(int(z))
                        except Exception:
                            pass

                    missing_configs = [z for z in found_zones if z not in self._zone_configs]
                    if missing_configs:
                        await self._fetch_zone_configs(missing_configs)

                zones = parsed.get("available_zones", [])
                for zone in zones:
                    zone_state = parsed.get("zones", {}).get(zone, {})
                    zone_state["zone"] = zone
                    self.mqtt.publish(
                        f"librecoach/ble/microair/{self.address}/state",
                        zone_state,
                        retain=False,
                    )

                # Success — reset failure count and mark online
                failure_count = 0
                self.mqtt.publish(
                    f"librecoach/ble/microair/{self.address}/available",
                    "online",
                    retain=True,
                )
                self.mqtt.publish(
                    f"librecoach/bridge/microair/{self.address}",
                    "connected",
                    retain=True,
                )

            except Exception as exc:
                failure_count += 1
                log.warning("MicroAir poll failed for %s (fail count: %d): %s", self.address, failure_count, exc)

                # Connection might be broken, tear it down
                await self._disconnect()

                # Only report offline after 10 consecutive failures (~5 min at 30s interval)
                # to avoid flipping unavailable on transient BLE interference
                if failure_count >= 10:
                    self.mqtt.publish(
                        f"librecoach/ble/microair/{self.address}/available",
                        "offline",
                        retain=True,
                    )
                    self.mqtt.publish(
                        f"librecoach/bridge/microair/{self.address}",
                        "disconnected",
                        retain=True,
                    )

            retry_delay = interval if failure_count >= 10 else min(interval, 10)
            await asyncio.sleep(retry_delay)

    async def send_command(self, command):
        try:
            await self._write_json(command)
        except Exception as exc:
            log.warning("MicroAir command failed for %s: %s", self.address, exc)

    async def _fetch_zone_configs(self, zones):
        for zone in zones:
            # Add delay between config fetches to be gentle on the connection
            await asyncio.sleep(2.0)
            response = await self._request_json({"Type": "Get Config", "Zone": zone})
            if not response:
                continue
            if response.get("Type") != "Response" or response.get("RT") != "Config":
                continue
            cfg_str = response.get("CFG", "{}")
            cfg_data = json.loads(cfg_str) if isinstance(cfg_str, str) else cfg_str
            self._zone_configs[zone] = {
                "MAV": cfg_data.get("MAV", 0),
                "FA": cfg_data.get("FA", [0] * 16),
                "SPL": cfg_data.get("SPL", [60, 85, 50, 85]),
                "MA": cfg_data.get("MA", [0] * 16),
            }

    async def _request_json(self, command):
        async with self._lock:
            try:
                await self._ensure_connected()

                cmd_path = self._char_paths.get(UUIDS["jsonCmd"])
                ret_path = self._char_paths.get(UUIDS["jsonReturn"])

                if not cmd_path or not ret_path:
                    log.debug("MicroAir GATT characteristics not found")
                    return None

                cmd_iface = await _get_interface(
                    self._bus, cmd_path, "org.bluez.GattCharacteristic1"
                )
                await cmd_iface.call_write_value(
                    json.dumps(command).encode("utf-8"), {}
                )
                await asyncio.sleep(1.0)

                ret_iface = await _get_interface(
                    self._bus, ret_path, "org.bluez.GattCharacteristic1"
                )
                result = await ret_iface.call_read_value({})
                payload = bytes(result)
                if not payload:
                    return None
                return json.loads(payload.decode("utf-8"))

            except Exception as exc:
                log.debug("MicroAir request failed: %s", exc)
                await self._disconnect()
                return None

    async def _write_json(self, command):
        async with self._lock:
            try:
                await self._ensure_connected()

                cmd_path = self._char_paths.get(UUIDS["jsonCmd"])
                if not cmd_path:
                    log.debug("MicroAir jsonCmd characteristic not found")
                    return

                cmd_iface = await _get_interface(
                    self._bus, cmd_path, "org.bluez.GattCharacteristic1"
                )
                await cmd_iface.call_write_value(
                    json.dumps(command).encode("utf-8"), {}
                )
            except Exception as exc:
                log.debug("MicroAir write failed: %s", exc)
                await self._disconnect()
                raise


def _parse_status(status):
    if not isinstance(status, dict):
        return {"available_zones": [0], "zones": {0: {}}}

    if "Z_sts" not in status:
        return {"available_zones": [0], "zones": {0: {}}}

    param = status.get("PRM", [])
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

        if len(param) > 2 and zone_num == 0:
            zone_status["outdoorTemperature"] = param[2]

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

        fan_num = _select_fan_mode(zone_status)
        zone_status["fan_mode_num"] = fan_num
        zone_status["fan_mode"] = FAN_MODE_MAP.get(fan_num, "off")

        zone_data[zone_num] = zone_status
        available_zones.append(zone_num)

    if not available_zones:
        return {"available_zones": [0], "zones": {0: {}}}

    return {
        "available_zones": sorted(available_zones),
        "zones": zone_data,
    }


def _select_fan_mode(zone_status):
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
