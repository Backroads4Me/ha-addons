import asyncio
import logging
import os
import subprocess

import can

log = logging.getLogger("vehicle_bridge.can")


class CanBridge:
    def __init__(self, config, mqtt):
        self.config = config
        self.mqtt = mqtt
        self.name = "can"

        self.can_interface = config.get("can_interface", "can0")
        self.can_bitrate = str(config.get("can_bitrate", "250000"))
        self.topic_raw = config.get("mqtt_topic_raw", "can/raw")
        self.topic_send = config.get("mqtt_topic_send", "can/send")
        self.topic_status = config.get("mqtt_topic_status", "can/status")

        self._bus = None
        self._read_task = None
        self._write_task = None
        self._send_queue = None
        self._stopping = False

        # PGN filter: skip these (pf, ps) pairs before MQTT publish
        # (0xFE, 0xCA) = DGN 1FECA (DM-RV diagnostic messages)
        self._filtered_pgns = {(0xFE, 0xCA)}

    def is_enabled(self):
        return bool(self.can_interface)

    async def start(self):
        loop = asyncio.get_running_loop()

        # Check if CAN interface exists
        if not os.path.exists(f"/sys/class/net/{self.can_interface}"):
            log.warning("CAN interface %s not found", self.can_interface)
            self.mqtt.publish(self.topic_status, "no_interface", retain=True)
            return

        # Initialize CAN interface (ported from can-mqtt-bridge run.sh)
        try:
            await loop.run_in_executor(None, self._setup_interface)
        except Exception as exc:
            log.error("Failed to initialize CAN interface %s: %s", self.can_interface, exc)
            self.mqtt.publish(self.topic_status, "no_interface", retain=True)
            return

        # Open socketcan bus
        try:
            self._bus = await loop.run_in_executor(
                None, lambda: can.Bus(channel=self.can_interface, bustype="socketcan")
            )
        except Exception as exc:
            log.warning("CAN interface %s not available: %s", self.can_interface, exc)
            self.mqtt.publish(self.topic_status, "no_interface", retain=True)
            return

        self._send_queue = asyncio.Queue()
        self.mqtt.subscribe(self.topic_send, self._on_send)

        self.mqtt.publish(self.topic_status, "online", retain=True)
        log.info(
            "CAN bridge started on %s @ %s bps", self.can_interface, self.can_bitrate
        )
        if self._filtered_pgns:
            filtered = ", ".join(
                f"1{pf:02X}{ps:02X}" for pf, ps in self._filtered_pgns
            )
            log.info("CAN DGN filter active — dropping: %s", filtered)

        self._read_task = asyncio.create_task(self._read_loop())
        self._write_task = asyncio.create_task(self._write_loop())

    def _setup_interface(self):
        """Configure and bring up the CAN interface (runs in executor)."""
        iface = self.can_interface

        # Bring down if already up
        subprocess.run(
            ["ip", "link", "set", iface, "down"],
            check=False, capture_output=True,
        )

        # Set type and bitrate
        subprocess.run(
            ["ip", "link", "set", iface, "type", "can", "bitrate", self.can_bitrate],
            check=True, capture_output=True,
        )

        # Bring up
        subprocess.run(
            ["ip", "link", "set", iface, "up"],
            check=True, capture_output=True,
        )

        log.info("CAN interface %s initialized at %s bps", iface, self.can_bitrate)

    async def stop(self):
        self._stopping = True
        tasks = [t for t in [self._read_task, self._write_task] if t]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("Error stopping CAN task")

        if self._bus:
            self._bus.shutdown()

        # Bring interface down on shutdown
        subprocess.run(
            ["ip", "link", "set", self.can_interface, "down"],
            check=False, capture_output=True,
        )

        self.mqtt.publish(self.topic_status, "offline", retain=True)

    async def _on_send(self, topic, payload):
        if self._send_queue is None:
            return
        await self._send_queue.put(payload)

    async def _read_loop(self):
        loop = asyncio.get_running_loop()
        while not self._stopping:
            try:
                msg = await loop.run_in_executor(None, self._bus.recv, 1.0)
                if msg is None:
                    continue

                # Drop filtered DGNs before MQTT publish
                pf = (msg.arbitration_id >> 16) & 0xFF
                ps = (msg.arbitration_id >> 8) & 0xFF
                if (pf, ps) in self._filtered_pgns:
                    continue

                if msg.is_extended_id:
                    can_id = f"{msg.arbitration_id:08X}"
                else:
                    can_id = f"{msg.arbitration_id:03X}"
                data_hex = msg.data.hex().upper()
                frame = f"{can_id}#{data_hex}"
                self.mqtt.publish(self.topic_raw, frame, qos=1, retain=False)
            except can.CanError as exc:
                log.warning("CAN read error: %s, retrying...", exc)
                await asyncio.sleep(1.0)
            except Exception as exc:
                if not self._stopping:
                    log.error("Unexpected CAN read error: %s", exc)
                    await asyncio.sleep(1.0)

    async def _write_loop(self):
        loop = asyncio.get_running_loop()
        while not self._stopping:
            payload = await self._send_queue.get()
            if payload is None:
                continue
            try:
                msg = self._parse_payload(payload)
                await loop.run_in_executor(None, self._bus.send, msg)
            except Exception as exc:
                log.warning("Failed to send CAN frame: %s", exc)

    @staticmethod
    def _parse_payload(payload):
        """Parse MQTT payload into a CAN message.

        Supports two formats:
        1. CANID#DATA (standard): 19FEDB94#06FFFA05FF00FFFF
        2. Raw hex (legacy): 19FEDB9406FFFA05FF00FFFF — first 8 chars are ID, rest is data
        """
        text = (payload or "").strip()

        if "#" in text:
            can_id_str, data_str = text.split("#", 1)
            can_id_str = can_id_str.strip()
            data_str = data_str.strip()
        elif len(text) > 8 and all(c in "0123456789ABCDEFabcdef" for c in text):
            # Legacy raw hex: first 8 chars = extended CAN ID, rest = data
            can_id_str = text[:8]
            data_str = text[8:]
        else:
            raise ValueError(f"Invalid CAN payload format: {text!r}")

        # Pad short IDs (7-char -> 8-char with leading zero)
        can_id_str = can_id_str.zfill(8) if len(can_id_str) > 3 else can_id_str

        can_id = int(can_id_str, 16)
        is_extended = len(can_id_str) > 3
        data = bytes.fromhex(data_str[:16]) if data_str else b""

        return can.Message(
            arbitration_id=can_id,
            data=data,
            is_extended_id=is_extended,
        )
