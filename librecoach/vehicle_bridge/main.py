import asyncio
import json
import logging
import signal

from mqtt_client import MqttClient
from can_bridge import CanBridge
from microair_bridge import MicroAirBridge
# from onecontrol_bridge import OneControlBridge

# NOTE: TrumaBridge (LIN serial) is on hold — not yet implemented.
# When ready, add: from truma_bridge import TrumaBridge


def _load_config():
    with open("/data/options.json", "r", encoding="utf-8") as f:
        return json.load(f)


def _configure_logging(config):
    level = logging.DEBUG if config.get("debug_logging") else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )


async def main():
    config = _load_config()
    _configure_logging(config)
    log = logging.getLogger("vehicle_bridge")

    mqtt = MqttClient(config)
    await mqtt.connect()

    modules = [
        CanBridge(config, mqtt),
        MicroAirBridge(config, mqtt),
        # OneControlBridge(config, mqtt),
        # TrumaBridge(config, mqtt),  # On hold
    ]

    active = []
    for module in modules:
        if module.is_enabled():
            log.info("Starting module: %s", module.name)
            try:
                await module.start()
                active.append(module)
            except Exception:
                log.exception("Failed to start %s", module.name)
        else:
            log.info("Module disabled: %s", module.name)

    mqtt.publish("librecoach/bridge/status", "online", retain=True)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    try:
        await stop_event.wait()
    finally:
        for module in active:
            try:
                await module.stop()
            except Exception:
                log.exception("Error stopping %s", module.name)
        mqtt.publish("librecoach/bridge/status", "offline", retain=True)
        await mqtt.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
