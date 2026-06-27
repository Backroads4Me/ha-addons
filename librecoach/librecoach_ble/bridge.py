import asyncio
import json
import logging
import os
from datetime import datetime, timezone

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
from homeassistant.core import HomeAssistant, callback

from .const import (
    MQTT_BASE,
    TOPIC_STATE, TOPIC_SET, TOPIC_AVAILABLE, TOPIC_BRIDGE,
    TOPIC_LAST_SUCCESS, TOPIC_FAILURE_COUNT, TOPIC_LAST_ERROR,
    TOPIC_RESET_LOCKS, TOPIC_RECONNECT, TOPIC_CLEAR_ERRORS,
    RETAINED_SCAN_WAIT,
    CONFIG_PATH, BLE_POLL_INTERVAL, BLE_BACKOFF_SCHEDULE, OFFLINE_AFTER_FAILURES,
    PAYLOAD_ONLINE, PAYLOAD_OFFLINE,
    ERROR_NONE, ERROR_AUTH_FAILED, ERROR_CONNECTIVITY,
)
from .devices import DEVICE_HANDLERS
from .devices.base import AuthenticationError

_LOGGER = logging.getLogger(__name__)


class BleBridgeManager:
    """Manages discovered BLE devices with persistent connections and serialized operations."""

    def __init__(self, hass: HomeAssistant, config: dict, enabled_types=None):
        self.hass = hass
        self.config = config
        self._active_devices = {}   # address -> device entry dict
        self._cancel_callbacks = []
        self._unsub_mqtt = []
        self._stopping = False
        self._enabled_types = set(enabled_types or ())
        self._locked_devices = self.config.get("locked_devices", {})  # device_type -> address
        # Debug counters for advertisement handling (B-1).
        self._adv_matched = 0
        self._adv_ignored = 0

    def _save_locked_device_sync(self, device_type: str, address: str):
        """Save a locked device address to config file (preserving other settings)."""
        self._locked_devices[device_type] = address
        try:
            data = {}
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data["locked_devices"] = self._locked_devices
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f)
            _LOGGER.info("Locked %s device address: %s", device_type, address)
        except Exception as exc:
            _LOGGER.warning("Failed to save locked device: %s", exc)

    def _clear_locked_devices_sync(self):
        """Remove only the persisted BLE device locks, preserving all other settings."""
        self._locked_devices = {}
        try:
            data = {}
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data["locked_devices"] = {}
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f)
            _LOGGER.info("Cleared persisted BLE device locks")
        except Exception as exc:
            _LOGGER.warning("Failed to clear locked devices: %s", exc)

    async def _retire_stale_addresses(self, device_type: str, keep_address: str):
        """Clear retained MQTT topics for stale addresses of one device type.

        Rather than guess topic shapes, this subscribes to the device type's retained
        subtree and lets the broker tell us what's actually there. That covers
        bridge-owned topics, handler-specific dynamic topics (e.g. Micro-Air per-zone
        configs), and leftovers from earlier sessions or add-on versions. Every
        retained topic whose address segment differs from ``keep_address`` is
        overwritten with an empty payload, which deletes it from the broker.

        ``keep_address`` is the anchor that defines what is legitimate. Without a
        valid anchor we cannot tell a stale ghost from the real device, so a missing
        or empty anchor is a hard no-op: we must never wipe a whole device type just
        because no lock is in effect (e.g. the real device is merely offline).
        """
        if not keep_address:
            _LOGGER.warning(
                "Refusing to retire %s topics without a locked address (no-op)",
                device_type,
            )
            return
        keep = keep_address.lower()
        found: set[str] = set()

        @callback
        def _collect(msg):
            # Only non-empty retained messages need clearing.
            if getattr(msg, "retain", False) and msg.payload:
                found.add(msg.topic)

        trees = [
            f"{MQTT_BASE}/{device_type}/#",
            f"librecoach/bridge/{device_type}/#",
        ]
        unsubs = []
        for tree in trees:
            unsubs.append(await mqtt.async_subscribe(self.hass, tree, _collect, qos=1))
        try:
            # Retained messages flush on subscribe; wait briefly for them to land.
            await asyncio.sleep(RETAINED_SCAN_WAIT)
        finally:
            for unsub in unsubs:
                unsub()

        for topic in found:
            # Address is always the 4th segment: librecoach/{ble|bridge}/{type}/{addr}/...
            parts = topic.split("/")
            addr = parts[3].lower() if len(parts) > 3 else None
            if addr == keep:
                continue
            await mqtt.async_publish(self.hass, topic, "", qos=1, retain=True)
            _LOGGER.info("Retired stale retained topic %s", topic)

    async def start(self):
        """Register a single BLE advertisement callback and subscribe to command topics."""
        # B-1: one callback for the whole bridge; the callback iterates handlers.
        cancel = async_register_callback(
            self.hass,
            self._on_ble_advertisement,
            BluetoothCallbackMatcher(connectable=True),
            BluetoothChange.ADVERTISEMENT,
        )
        self._cancel_callbacks.append(cancel)

        # Per-device command topic (forwarded to the owning handler).
        self._unsub_mqtt.append(await mqtt.async_subscribe(
            self.hass, "librecoach/ble/+/+/set", self._on_mqtt_command, qos=1,
        ))
        # Recovery controls (F-6).
        self._unsub_mqtt.append(await mqtt.async_subscribe(
            self.hass, TOPIC_RECONNECT.format(device_type="+", address="+"),
            self._on_reconnect, qos=1,
        ))
        self._unsub_mqtt.append(await mqtt.async_subscribe(
            self.hass, TOPIC_CLEAR_ERRORS.format(device_type="+", address="+"),
            self._on_clear_errors, qos=1,
        ))
        # Reset BLE locks (B-3/BL-3).
        self._unsub_mqtt.append(await mqtt.async_subscribe(
            self.hass, TOPIC_RESET_LOCKS, self._on_reset_locks, qos=1,
        ))

        # On startup, sweep retained topics left by any address other than the one
        # we're locked to. Discovery ignores non-locked addresses, so they would
        # otherwise linger forever as "disconnected" ghosts in the UI. Runs in the
        # background so it never delays startup. Skip falsy/corrupted lock values so
        # an absent anchor never triggers a wipe of every device of that type.
        for device_type, address in self._locked_devices.items():
            if not address:
                continue
            self.hass.async_create_task(
                self._retire_stale_addresses(device_type, address)
            )

    async def stop(self):
        """Cancel all poll loops, disconnect all devices, and unregister callbacks."""
        self._stopping = True
        for cancel in self._cancel_callbacks:
            cancel()
        self._cancel_callbacks = []
        for unsub in self._unsub_mqtt:
            try:
                unsub()
            except Exception:  # pragma: no cover - defensive
                pass
        self._unsub_mqtt = []
        for address in list(self._active_devices):
            await self._teardown_device(address)

    def enable_device_type(self, device_type: str):
        """Allow discovery and connections for one handler type."""
        self._enabled_types.add(device_type)

    async def disable_device_type(self, device_type: str):
        """Stop and disconnect devices owned by one handler type."""
        self._enabled_types.discard(device_type)
        for address, entry in list(self._active_devices.items()):
            if entry["handler"].device_type() == device_type:
                await self._publish(
                    TOPIC_AVAILABLE, device_type, address, PAYLOAD_OFFLINE, retain=True,
                )
                await self._publish(
                    TOPIC_BRIDGE, device_type, address, "disabled", retain=True,
                )
                await self._teardown_device(address)

    async def _teardown_device(self, address: str):
        """Cancel a device's poll loop and disconnect it."""
        entry = self._active_devices.pop(address, None)
        if not entry:
            return
        task = entry.get("task")
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self._disconnect(address, entry)

    # --- Device Discovery ---

    def _on_ble_advertisement(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """Single callback for all handlers; each handler decides if the advert applies (B-1)."""
        name = service_info.name or ""
        address = service_info.address.lower()

        if address in self._active_devices:
            self._active_devices[address]["ble_device"] = service_info.device
            return

        for handler_class in DEVICE_HANDLERS:
            if not handler_class.match_name(name):
                continue

            device_type = handler_class.device_type()
            if device_type not in self._enabled_types:
                continue

            # If we have a locked address for this device type, ignore others.
            locked_addr = self._locked_devices.get(device_type)
            if locked_addr and locked_addr != address:
                self._adv_ignored += 1
                _LOGGER.debug(
                    "Ignoring %s device %s (locked to %s) [ignored=%d]",
                    device_type, address, locked_addr, self._adv_ignored,
                )
                return

            self._adv_matched += 1
            _LOGGER.info(
                "Discovered %s device: %s (%s) [matched=%d]",
                device_type, address, name, self._adv_matched,
            )
            handler_config = dict(self.config)
            handler_config["_device_name"] = name
            handler = handler_class(address, handler_config)
            entry = {
                "handler": handler,
                "task": None,
                "ble_device": service_info.device,
                "client": None,
                "lock": asyncio.Lock(),
                "authenticated": False,
                "failure_count": 0,
                "availability": None,      # None=unknown until first poll result
                "last_error": ERROR_NONE,
                "wake": asyncio.Event(),   # set to interrupt backoff sleep (reconnect)
            }
            self._active_devices[address] = entry
            entry["task"] = self.hass.async_create_task(
                self._poll_loop(handler, address)
            )
            return

        # No handler claimed this advertisement.
        self._adv_ignored += 1

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

        ble_device = self._get_ble_device(address)
        if not ble_device:
            raise BleakError(f"BLE device {address} not available")

        _LOGGER.debug("Establishing connection to %s", address)
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            address,
            timeout=20.0,
        )

        # Authenticate. A False/raised result means credentials were rejected (B-5),
        # which is distinct from a connectivity failure and must not be retried fast.
        handler = entry["handler"]
        try:
            ok = await handler.authenticate(client)
        except AuthenticationError:
            await self._disconnect(address, entry)
            raise
        if not ok:
            await self._disconnect(address, entry)
            raise AuthenticationError(f"Authentication failed for {address}")

        entry["client"] = client
        entry["authenticated"] = True
        _LOGGER.debug("Connected and authenticated to %s", address)
        return client

    async def _disconnect(self, address: str, entry: dict | None = None):
        """Safely disconnect and clear connection state."""
        if entry is None:
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
        """Acquire lock, ensure connection, run operation. Retry once on BLE error.

        AuthenticationError is NOT retried here — it propagates to the caller so the
        poll loop can surface an auth failure and back off.
        """
        entry = self._active_devices[address]
        async with entry["lock"]:
            for attempt in range(2):  # 1 try + 1 retry
                try:
                    client = await self._ensure_connected(address)
                    return await operation(client)
                except (BleakError, OSError, asyncio.TimeoutError) as exc:
                    if attempt == 0:
                        _LOGGER.debug(
                            "BLE operation failed for %s, retrying: %s", address, exc,
                        )
                        await self._disconnect(address, entry)
                    else:
                        raise

    # --- Poll Loop ---

    def _next_delay(self, entry: dict) -> float:
        """Healthy cadence when no failures, otherwise capped backoff (B-4)."""
        fc = entry["failure_count"]
        if fc <= 0:
            return BLE_POLL_INTERVAL
        idx = min(fc - 1, len(BLE_BACKOFF_SCHEDULE) - 1)
        return BLE_BACKOFF_SCHEDULE[idx]

    async def _poll_loop(self, handler, address: str):
        """Poll a device, publish state, and manage availability/backoff."""
        device_type = handler.device_type()
        entry = self._active_devices[address]

        while not self._stopping:
            try:
                async def _do_poll(client):
                    return await handler.poll(client)

                parsed = await self._execute_with_lock(address, _do_poll)
                if not parsed:
                    raise Exception("No status response")

                await self._publish_messages(handler, parsed)

                # Lock this address on first successful poll and retire stale peers.
                if device_type not in self._locked_devices:
                    await self.hass.async_add_executor_job(
                        self._save_locked_device_sync, device_type, address
                    )
                    # Tear down any competing devices discovered during the unlocked
                    # window so only the winner keeps polling.
                    for other_addr in list(self._active_devices):
                        entry_other = self._active_devices[other_addr]
                        if other_addr != address and entry_other["handler"].device_type() == device_type:
                            await self._teardown_device(other_addr)
                    # Clear any retained MQTT topics left by those losing addresses.
                    await self._retire_stale_addresses(device_type, address)

                await self._on_poll_success(device_type, address)

            except AuthenticationError as exc:
                await self._on_poll_failure(
                    device_type, address, exc, ERROR_AUTH_FAILED,
                )
            except Exception as exc:
                await self._on_poll_failure(
                    device_type, address, exc, ERROR_CONNECTIVITY,
                )

            # Sleep OUTSIDE the lock so commands can run between polls. A reconnect
            # command sets the wake event to retry immediately.
            delay = self._next_delay(entry)
            try:
                await asyncio.wait_for(entry["wake"].wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            entry["wake"].clear()

    async def _on_poll_success(self, device_type: str, address: str):
        """Reset failure state and publish online on transition."""
        entry = self._active_devices.get(address)
        if not entry:
            return
        entry["failure_count"] = 0
        now = datetime.now(timezone.utc).isoformat()

        await self._publish(TOPIC_LAST_SUCCESS, device_type, address, now, retain=True)
        await self._publish(TOPIC_FAILURE_COUNT, device_type, address, "0", retain=True)

        if entry["availability"] != PAYLOAD_ONLINE:
            entry["availability"] = PAYLOAD_ONLINE
            entry["last_error"] = ERROR_NONE
            await self._publish(TOPIC_AVAILABLE, device_type, address, PAYLOAD_ONLINE, retain=True)
            await self._publish(TOPIC_BRIDGE, device_type, address, "connected", retain=True)
            await self._publish(TOPIC_LAST_ERROR, device_type, address, ERROR_NONE, retain=True)
            _LOGGER.info("%s %s is online", device_type, address)

    async def _on_poll_failure(self, device_type: str, address: str, exc, error_kind: str):
        """Track failures and publish offline once on transition (B-4/B-5)."""
        entry = self._active_devices.get(address)
        if not entry:
            return
        entry["failure_count"] += 1
        fc = entry["failure_count"]
        entry["last_error"] = error_kind

        log = _LOGGER.debug if fc <= 3 else _LOGGER.warning
        log("%s poll failed for %s (count %d, %s): %s", device_type, address, fc, error_kind, exc)

        await self._publish(TOPIC_FAILURE_COUNT, device_type, address, str(fc), retain=True)
        await self._publish(TOPIC_LAST_ERROR, device_type, address, error_kind, retain=True)

        # Auth failures will not self-heal by retrying, so surface immediately;
        # connectivity failures wait a couple of cycles to avoid flapping.
        threshold = 1 if error_kind == ERROR_AUTH_FAILED else OFFLINE_AFTER_FAILURES
        if fc >= threshold and entry["availability"] != PAYLOAD_OFFLINE:
            entry["availability"] = PAYLOAD_OFFLINE
            await self._publish(TOPIC_AVAILABLE, device_type, address, PAYLOAD_OFFLINE, retain=True)
            bridge_status = "auth_failed" if error_kind == ERROR_AUTH_FAILED else "disconnected"
            await self._publish(TOPIC_BRIDGE, device_type, address, bridge_status, retain=True)
            _LOGGER.warning("%s %s is offline (%s)", device_type, address, error_kind)

    # --- MQTT Command Handlers ---

    async def _on_mqtt_command(self, msg):
        """Handle inbound device commands on librecoach/ble/+/+/set."""
        parts = msg.topic.split("/")
        if len(parts) < 5:
            return
        device_type = parts[2]
        address = parts[3].lower()

        entry = self._active_devices.get(address)
        if not entry or entry["handler"].device_type() != device_type:
            _LOGGER.warning("Command for unknown device: %s/%s", device_type, address)
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

            # Publish verified state if the handler returned a parsed status dict.
            if isinstance(result, dict):
                await self._publish_messages(handler, result)

        except Exception as exc:
            _LOGGER.warning("Command failed for %s: %s", address, exc)

    async def _on_reconnect(self, msg):
        """Schedule an immediate retry for a device (F-6)."""
        parts = msg.topic.split("/")
        if len(parts) < 5:
            return
        device_type = parts[2]
        address = parts[3].lower()
        entry = self._active_devices.get(address)
        if not entry or entry["handler"].device_type() != device_type:
            _LOGGER.warning("Reconnect for unknown device: %s/%s", device_type, address)
            return
        _LOGGER.info("Manual reconnect requested for %s", address)
        entry["failure_count"] = 0          # retry at normal cadence
        await self._disconnect(address, entry)
        entry["wake"].set()                 # break the backoff sleep now

    async def _on_clear_errors(self, msg):
        """Clear failure/availability state for a device (F-6)."""
        parts = msg.topic.split("/")
        if len(parts) < 5:
            return
        device_type = parts[2]
        address = parts[3].lower()
        entry = self._active_devices.get(address)
        if not entry or entry["handler"].device_type() != device_type:
            return
        _LOGGER.info("Clearing error state for %s", address)
        entry["failure_count"] = 0
        entry["availability"] = None
        entry["last_error"] = ERROR_NONE
        await self._publish(TOPIC_FAILURE_COUNT, device_type, address, "0", retain=True)
        await self._publish(TOPIC_LAST_ERROR, device_type, address, ERROR_NONE, retain=True)
        entry["wake"].set()

    async def _on_reset_locks(self, msg):
        """Forget all saved BLE device locks and return to scanning (B-3/BL-3)."""
        _LOGGER.info("Reset BLE locks requested")
        # Clear only the locks; credentials/enable flags/other settings are preserved.
        await self.hass.async_add_executor_job(self._clear_locked_devices_sync)

        # Tear down active devices so replacements can be rediscovered and relocked.
        for address in list(self._active_devices):
            entry = self._active_devices.get(address)
            device_type = entry["handler"].device_type() if entry else None
            await self._teardown_device(address)
            if device_type:
                # Mark the forgotten device unavailable so HA does not show it healthy.
                await self._publish(
                    TOPIC_AVAILABLE, device_type, address, PAYLOAD_OFFLINE, retain=True,
                )
                await self._publish(
                    TOPIC_BRIDGE, device_type, address, "waiting_for_device", retain=True,
                )
        _LOGGER.info("BLE locks cleared; scanning for devices")

    # --- MQTT Publishing ---

    async def _publish(self, template: str, device_type: str, address: str, payload: str, retain: bool = False):
        """Publish a single formatted topic (bridge-owned diagnostic/status topics)."""
        topic = template.format(device_type=device_type, address=address)
        await mqtt.async_publish(self.hass, topic, payload, qos=1, retain=retain)

    async def _publish_messages(self, handler, parsed: dict):
        """Publish whatever the handler decides for this state — bridge stays generic (B-2)."""
        for message in handler.state_messages(parsed):
            await mqtt.async_publish(
                self.hass,
                message.topic,
                message.payload,
                qos=message.qos,
                retain=message.retain,
            )
