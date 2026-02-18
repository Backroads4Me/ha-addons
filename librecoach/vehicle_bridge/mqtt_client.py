import asyncio
import json
import logging

import paho.mqtt.client as mqtt

log = logging.getLogger("vehicle_bridge.mqtt")


class MqttClient:
    def __init__(self, config):
        self.config = config
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="vehicle_bridge",
        )
        self._subscriptions = {}
        self._loop = None
        self._connected = False

        user = config.get("mqtt_user")
        password = config.get("mqtt_pass")
        if user:
            self.client.username_pw_set(user, password)

        self.client.will_set(
            "librecoach/bridge/status", "offline", qos=1, retain=True
        )

        self.client.on_message = self._on_message
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        self._host = config.get("mqtt_host", "core-mosquitto")
        self._port = int(config.get("mqtt_port", 1883))

    async def connect(self):
        self._loop = asyncio.get_running_loop()
        while True:
            try:
                await self._loop.run_in_executor(
                    None, self.client.connect, self._host, self._port, 60
                )
                self.client.loop_start()
                log.info("Connected to MQTT broker at %s:%s", self._host, self._port)
                return
            except Exception as exc:
                log.error("MQTT connection failed: %s, retrying in 10s", exc)
                await asyncio.sleep(10)

    def publish(self, topic, payload, qos=1, retain=False):
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        self.client.publish(topic, payload, qos=qos, retain=retain)

    def subscribe(self, topic_filter, callback):
        self._subscriptions[topic_filter] = callback
        if self._connected:
            self.client.subscribe(topic_filter, qos=1)

    def unsubscribe(self, topic_filter):
        self._subscriptions.pop(topic_filter, None)
        if self._connected:
            self.client.unsubscribe(topic_filter)

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", errors="replace")
        if not self._loop:
            return
        for topic_filter, callback in list(self._subscriptions.items()):
            if mqtt.topic_matches_sub(topic_filter, msg.topic):
                asyncio.run_coroutine_threadsafe(
                    self._safe_callback(callback, msg.topic, payload),
                    self._loop,
                )

    @staticmethod
    async def _safe_callback(callback, topic, payload):
        try:
            await callback(topic, payload)
        except Exception:
            log.exception("Error in MQTT callback for %s", topic)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            self._connected = True
            log.info("MQTT connected")
            for topic_filter in self._subscriptions:
                self.client.subscribe(topic_filter, qos=1)
        else:
            log.error("MQTT connect failed with reason code %s", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self._connected = False
        if reason_code != 0:
            log.warning("MQTT unexpected disconnect (rc=%s), auto-reconnecting", reason_code)

    async def disconnect(self):
        # Allow pending publishes to drain
        await asyncio.sleep(0.5)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.client.loop_stop)
        self.client.disconnect()
