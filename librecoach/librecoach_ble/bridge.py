import asyncio
import json
import logging

from bleak import BleakError
from bleak_retry_connector import establish_connection, BleakClientWithServiceCache
from homeassistant.components import mqtt
from homeassistant.components.bluetooth import (
    async_ble_device_from_address,
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothServiceInfoBleak,
    async_register_callback,
)
from homeassistant.core import HomeAssistant

from .const import TOPIC_STATE, TOPIC_SET, TOPIC_AVAILABLE, TOPIC_BRIDGE, CONFIG_PATH
from .devices import DEVICE_HANDLERS

_LOGGER = logging.getLogger(__name__)

class BleBridgeManager:
    """Manages discovered BLE devices with persistent connections and serialized operations."""

    def __init__(self, hass: HomeAssistant, config: dict):
        self.hass = hass
        self.config = config
        self._active_devices = {}   # address -> device entry dict
        self._cancel_callbacks = []
        self._stopping = False
        self._locked_devices = self._load_locked_devices()  # device_type -> address

    def _load_locked_devices(self) -> dict:
        """Load previously locked device addresses from config file."""
        try:
            import os
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    locked = data.get("locked_devices", {})
                    if locked:
                        _LOGGER.info("Loaded locked devices: %s", locked)
                    return locked
        except Exception as exc:
            _LOGGER.warning("Failed to load locked devices: %s", exc)
        return {}

    def _save_locked_device(self, device_type: str, address: str):
        """Save a locked device address to config file."""
        self._locked_devices[device_type] = address
        try:
            import os
            data = {}
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data["locked_devices"] = self._locked_devices
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f)
            _LOGGER.info(
                "Locked %s device address: %s", device_type, address
            )
        except Exception as exc:
            _LOGGER.warning("Failed to save locked device: %s", exc)

    async def start(self):
        """Register BLE advertisement callbacks for all device handlers."""
        for handler_class in DEVICE_HANDLERS:
            cancel = async_register_callback(
                self.hass,
                self._on_ble_advertisement,
                BluetoothCallbackMatcher(
                    connectable=True,
                ),
                BluetoothChange.ADVERTISEMENT,
            )
            self._cancel_callbacks.append(cancel)

        # Subscribe to MQTT command topics
        await mqtt.async_subscribe(
            self.hass,
            "librecoach/ble/+/+/set",
            self._on_mqtt_command,
            qos=1,
        )

    async def stop(self):
        """Cancel all poll loops, disconnect all devices, and unregister callbacks."""
        self._stopping = True
        for cancel in self._cancel_callbacks:
            cancel()
        for address, entry in self._active_devices.items():
            entry["task"].cancel()
            try:
                await entry["task"]
            except asyncio.CancelledError:
                pass
            await self._disconnect(address)

    # --- Device Discovery ---

    def _on_ble_advertisement(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """Called when HA sees a BLE advertisement."""
        name = service_info.name or ""
        address = service_info.address.lower()

        if address in self._active_devices:
            self._active_devices[address]["ble_device"] = service_info.device
            return

        for handler_class in DEVICE_HANDLERS:
            if handler_class.match_name(name):
                device_type = handler_class.device_type()

                # If we have a locked address for this device type, skip others
                locked_addr = self._locked_devices.get(device_type)
                if locked_addr and locked_addr != address:
                    _LOGGER.debug(
                        "Ignoring %s device %s (locked to %s)",
                        device_type, address, locked_addr,
                    )
                    return

                _LOGGER.info(
                    "Discovered %s device: %s (%s)",
                    handler_class.device_type(), address, name,
                )
                handler = handler_class(address, self.config)
                task = self.hass.async_create_task(
                    self._poll_loop(handler, address)
                )
                self._active_devices[address] = {
                    "handler": handler,
                    "task": task,
                    "ble_device": service_info.device,
                    "client": None,
                    "lock": asyncio.Lock(),
                    "authenticated": False,
                }
                return

    # --- Connection Management ---

    def _get_ble_device(self, address: str):
        """Get BLE device, trying HA's cache first then falling back to stored ref."""
        ble_device = async_ble_device_from_address(
            self.hass, address, connectable=True
        )
        if ble_device:
            return ble_device

        entry = self._active_devices.get(address)
        if entry and entry.get("ble_device"):
            _LOGGER.debug("Using stored BLE device for %s", address)
            return entry["ble_device"]

        return None

    async def _ensure_connected(self, address: str):
        """Ensure we have a connected, authenticated client. Returns the client."""
        entry = self._active_devices[address]

        # Reuse existing connection if still valid
        if entry["client"] and entry["client"].is_connected:
            return entry["client"]

        # Need new connection
        ble_device = self._get_ble_device(address)
        if not ble_device:
            raise Exception(f"BLE device {address} not available")

        _LOGGER.debug("Establishing connection to %s", address)
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            address,
            timeout=20.0,
        )

        # Authenticate
        handler = entry["handler"]
        await handler.authenticate(client)
        entry["client"] = client
        entry["authenticated"] = True
        _LOGGER.debug("Connected and authenticated to %s", address)
        return client

    async def _disconnect(self, address: str):
        """Safely disconnect and clear connection state."""
        entry = self._active_devices.get(address)
        if not entry:
            return

        client = entry.get("client")
        if client:
            try:
                if client.is_connected:
                    await client.disconnect()
            except (BleakError, OSError) as exc:
                _LOGGER.debug("Error during disconnect for %s: %s", address, exc)

        entry["client"] = None
        entry["authenticated"] = False

    async def _execute_with_lock(self, address: str, operation):
        """Acquire lock, ensure connection, run operation. Retry once on BLE error."""
        entry = self._active_devices[address]
        async with entry["lock"]:
            for attempt in range(2):  # 1 try + 1 retry
                try:
                    client = await self._ensure_connected(address)
                    return await operation(client)
                except (BleakError, OSError, asyncio.TimeoutError) as exc:
                    if attempt == 0:
                        _LOGGER.debug(
                            "BLE operation failed for %s, retrying: %s",
                            address, exc,
                        )
                        await self._disconnect(address)
                    else:
                        raise

    # --- Poll Loop ---

    async def _poll_loop(self, handler, address: str):
        """Poll a device at regular intervals, publish state to MQTT."""
        device_type = handler.device_type()
        poll_interval = int(self.config.get("ble_scan_interval", 30))
        failure_count = 0

        while not self._stopping:
            try:
                async def _do_poll(client):
                    return await handler.poll(client)

                parsed = await self._execute_with_lock(address, _do_poll)

                if not parsed:
                    raise Exception("No status response")

                # Publish state and config to MQTT
                await self._publish_state(handler, address, parsed)

                # Lock this address on first successful poll
                device_type = handler.device_type()
                if device_type not in self._locked_devices:
                    self._save_locked_device(device_type, address)

                # Mark online
                failure_count = 0
                await mqtt.async_publish(
                    self.hass,
                    TOPIC_AVAILABLE.format(
                        device_type=device_type, address=address
                    ),
                    "online", qos=1, retain=True,
                )
                await mqtt.async_publish(
                    self.hass,
                    TOPIC_BRIDGE.format(
                        device_type=device_type, address=address
                    ),
                    "connected", qos=1, retain=True,
                )

            except Exception as exc:
                failure_count += 1
                if failure_count <= 3:
                    _LOGGER.debug(
                        "%s poll failed for %s (count %d): %s",
                        device_type, address, failure_count, exc,
                    )
                else:
                    _LOGGER.warning(
                        "%s poll failed for %s (count %d): %s",
                        device_type, address, failure_count, exc,
                    )

                if failure_count >= 10:
                    await mqtt.async_publish(
                        self.hass,
                        TOPIC_AVAILABLE.format(
                            device_type=device_type, address=address
                        ),
                        "offline", qos=1, retain=True,
                    )
                    await mqtt.async_publish(
                        self.hass,
                        TOPIC_BRIDGE.format(
                            device_type=device_type, address=address
                        ),
                        "disconnected", qos=1, retain=True,
                    )

            # Sleep OUTSIDE the lock so commands can execute between polls
            await asyncio.sleep(poll_interval)

    # --- MQTT Command Handler ---

    async def _on_mqtt_command(self, msg):
        """Handle inbound MQTT commands on librecoach/ble/+/+/set."""
        parts = msg.topic.split("/")
        if len(parts) < 5:
            return
        address = parts[3].lower()

        entry = self._active_devices.get(address)
        if not entry:
            _LOGGER.warning("Command for unknown device: %s", address)
            return

        handler = entry["handler"]

        try:
            command = json.loads(msg.payload)
        except (json.JSONDecodeError, TypeError):
            _LOGGER.warning("Invalid command payload: %s", msg.payload)
            return

        try:
            async def _do_command(client):
                return await handler.handle_command(client, command)

            result = await self._execute_with_lock(address, _do_command)

            # Publish verified state if command returned parsed status
            if isinstance(result, dict) and "zones" in result:
                await self._publish_state(handler, address, result)

        except Exception as exc:
            _LOGGER.warning("Command failed for %s: %s", address, exc)

    # --- MQTT Publishing ---

    async def _publish_state(self, handler, address: str, parsed: dict):
        """Publish zone state and config to MQTT."""
        device_type = handler.device_type()
        zones = parsed.get("zones", {})
        zone_configs = parsed.get("zone_configs", {})

        for zone_num, zone_state in zones.items():
            zone_state["zone"] = zone_num
            topic = TOPIC_STATE.format(
                device_type=device_type, address=address
            )
            await mqtt.async_publish(
                self.hass, topic, json.dumps(zone_state), qos=1, retain=False
            )

            # Publish zone config if available (retained for discovery)
            int_zone = int(zone_num) if not isinstance(zone_num, int) else zone_num
            if int_zone in zone_configs:
                config_topic = f"librecoach/ble/{device_type}/{address}/zone/{zone_num}/config"
                await mqtt.async_publish(
                    self.hass, config_topic,
                    json.dumps(zone_configs[int_zone]),
                    qos=1, retain=True,
                )
