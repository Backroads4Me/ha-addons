import asyncio
import json
import logging

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

from .const import TOPIC_STATE, TOPIC_SET, TOPIC_AVAILABLE, TOPIC_BRIDGE
from .devices import DEVICE_HANDLERS

_LOGGER = logging.getLogger(__name__)

class BleBridgeManager:
    """Manages discovered BLE devices, their poll loops, and MQTT communication."""

    def __init__(self, hass: HomeAssistant, config: dict):
        self.hass = hass
        self.config = config
        self._active_devices = {}   # address -> {"handler": ..., "task": ...}
        self._cancel_callbacks = []
        self._stopping = False

    async def start(self):
        """Register BLE advertisement callbacks for all device handlers."""
        for handler_class in DEVICE_HANDLERS:
            # Register a callback for each handler's BLE name pattern
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
        # Uses wildcard: librecoach/ble/+/+/set
        await mqtt.async_subscribe(
            self.hass,
            "librecoach/ble/+/+/set",
            self._on_mqtt_command,
            qos=1,
        )

    async def stop(self):
        """Cancel all poll loops and callbacks."""
        self._stopping = True
        for cancel in self._cancel_callbacks:
            cancel()
        for address, entry in self._active_devices.items():
            entry["task"].cancel()
            try:
                await entry["task"]
            except asyncio.CancelledError:
                pass

    def _on_ble_advertisement(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """Called when HA sees a BLE advertisement."""
        name = service_info.name or ""
        address = service_info.address.lower()

        if address in self._active_devices:
            # Update stored BLE device reference (keeps it fresh for next poll)
            self._active_devices[address]["ble_device"] = service_info.device
            return

        # Find matching handler
        for handler_class in DEVICE_HANDLERS:
            if handler_class.match_name(name):
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
                }
                return

    def _get_ble_device(self, address: str):
        """Get BLE device, trying HA's cache first then falling back to stored ref."""
        # Try HA's Bluetooth manager first (picks best adapter/proxy)
        ble_device = async_ble_device_from_address(
            self.hass, address, connectable=True
        )
        if ble_device:
            return ble_device

        # Fall back to device reference from last advertisement
        entry = self._active_devices.get(address)
        if entry and entry.get("ble_device"):
            _LOGGER.debug("Using stored BLE device for %s", address)
            return entry["ble_device"]

        return None

    async def _poll_loop(self, handler, address: str):
        """Poll a device at regular intervals, publish state to MQTT."""
        device_type = handler.device_type()
        poll_interval = int(self.config.get("ble_scan_interval", 30))
        failure_count = 0

        while not self._stopping:
            try:
                ble_device = self._get_ble_device(address)
                if not ble_device:
                    raise Exception(f"BLE device {address} not available")

                # Connect via Bleak (routed through best proxy)
                client = await establish_connection(
                    BleakClientWithServiceCache,
                    ble_device,
                    address,
                    timeout=20.0,
                )

                try:
                    parsed = await handler.poll(client)
                finally:
                    await client.disconnect()

                if not parsed:
                    raise Exception("No status response")

                # Publish each zone state to MQTT
                zones = parsed.get("zones", {})
                for zone_num, zone_state in zones.items():
                    zone_state["zone"] = zone_num
                    topic = TOPIC_STATE.format(
                        device_type=device_type, address=address
                    )
                    await mqtt.async_publish(
                        self.hass, topic, json.dumps(zone_state), qos=1, retain=False
                    )

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
                handler._authenticated = False  # Force re-auth on reconnect

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

            await asyncio.sleep(poll_interval)

    async def _on_mqtt_command(self, msg):
        """Handle inbound MQTT commands on librecoach/ble/+/+/set."""
        # Parse topic: librecoach/ble/{device_type}/{address}/set
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
            ble_device = self._get_ble_device(address)
            if not ble_device:
                _LOGGER.warning("BLE device %s not available for command", address)
                return

            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                address,
                timeout=20.0,
            )
            try:
                await handler.handle_command(client, command)
            finally:
                await client.disconnect()

        except Exception as exc:
            _LOGGER.warning("Command failed for %s: %s", address, exc)
