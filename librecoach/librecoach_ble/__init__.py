"""LibreCoach BLE Bridge — generic Bluetooth-to-MQTT bridge for RV devices."""
import json
import logging
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, CONFIG_PATH
from .bridge import BleBridgeManager

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up LibreCoach BLE from configuration.yaml."""
    # Read config written by the add-on
    try:
        conf = json.loads(Path(CONFIG_PATH).read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        _LOGGER.warning("LibreCoach BLE config not found or invalid: %s", exc)
        _LOGGER.warning("Ensure the LibreCoach add-on is installed and MicroAir is enabled")
        return True  # Don't fail HA startup

    if not conf.get("microair_enabled"):
        _LOGGER.info("LibreCoach BLE: MicroAir disabled in add-on config")
        return True

    manager = BleBridgeManager(hass, conf)
    hass.data[DOMAIN] = manager

    # Start after HA is fully running (Bluetooth + MQTT ready)
    async def _start_bridge(event=None):
        await manager.start()
        _LOGGER.info("LibreCoach BLE bridge started")

    hass.bus.async_listen_once("homeassistant_started", _start_bridge)

    return True

async def async_unload(hass: HomeAssistant) -> bool:
    """Unload the integration."""
    manager = hass.data.get(DOMAIN)
    if manager:
        await manager.stop()
    return True
