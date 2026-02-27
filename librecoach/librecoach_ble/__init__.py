import asyncio
import json
import logging
import os
from pathlib import Path

import aiohttp
from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, CONFIG_PATH
from .bridge import BleBridgeManager

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up LibreCoach BLE from configuration.yaml.

    The integration is always loaded. The BLE bridge starts/stops dynamically
    based on the retained MQTT topic librecoach/config/microair_enabled.
    """
    _LOGGER.info("LibreCoach BLE integration loading")

    # Read config for credentials and addon slug
    conf = await _read_config(hass)
    if not conf:
        _LOGGER.warning("Config file not found at %s — add-on may not have started yet", CONFIG_PATH)
        conf = {}

    _LOGGER.info("Config loaded: microair_enabled=%s, addon_slug=%s",
                 conf.get("microair_enabled"), conf.get("addon_slug"))

    hass.data[DOMAIN] = {"config": conf, "manager": None}

    # Suicide pattern monitor
    slug = conf.get("addon_slug")
    if slug:
        hass.async_create_task(_monitor_addon_status(hass, slug))

    # After HA is fully started (Bluetooth + MQTT ready), subscribe to config toggle.
    # The retained MQTT message triggers bridge start or confirms disabled state.
    async def _on_ha_started(event=None):
        _LOGGER.info("HA started — subscribing to MicroAir config toggle")
        await mqtt.async_subscribe(
            hass, "librecoach/config/microair_enabled",
            _make_config_callback(hass), qos=1,
        )

    hass.bus.async_listen_once("homeassistant_started", _on_ha_started)
    _LOGGER.info("BLE bridge will activate when MQTT config message arrives")

    return True


# ------------------------------------------------------------------
# MQTT config callback
# ------------------------------------------------------------------

def _make_config_callback(hass: HomeAssistant):
    """Create the MQTT callback that starts/stops the bridge."""

    async def _on_config_toggle(msg):
        payload = msg.payload
        if isinstance(payload, bytes):
            payload = payload.decode()
        enabled = str(payload).strip() == "true"

        data = hass.data.get(DOMAIN, {})
        manager = data.get("manager")

        if enabled and manager is None:
            _LOGGER.info("MicroAir enabled via MQTT — starting BLE bridge")
            await _start_bridge(hass)
        elif not enabled and manager is not None:
            _LOGGER.info("MicroAir disabled via MQTT — stopping BLE bridge")
            await _stop_bridge(hass)
        elif not enabled and manager is None:
            _LOGGER.info("MicroAir disabled — bridge not running")

    return _on_config_toggle


# ------------------------------------------------------------------
# Bridge lifecycle
# ------------------------------------------------------------------

async def _start_bridge(hass: HomeAssistant):
    """Re-read config for latest credentials, create and start bridge."""
    data = hass.data[DOMAIN]

    # Re-read config file in case credentials changed since integration loaded
    conf = await _read_config(hass)
    if conf:
        data["config"] = conf
    else:
        conf = data["config"]

    if not conf:
        _LOGGER.error("Cannot start bridge — no config available")
        return

    manager = BleBridgeManager(hass, conf)
    data["manager"] = manager
    await manager.start()
    _LOGGER.info("BLE bridge started — listening for MicroAir advertisements")


async def _stop_bridge(hass: HomeAssistant):
    """Stop bridge, remove devices, clear locked addresses."""
    data = hass.data[DOMAIN]
    manager = data.get("manager")

    if manager:
        await manager.stop()
        data["manager"] = None
        _LOGGER.info("BLE bridge stopped")

    # Remove entities and devices from HA registry
    try:
        from homeassistant.helpers import device_registry as dr

        device_reg = dr.async_get(hass)
        devices = [
            device
            for device in device_reg.devices.values()
            if any(id_tuple[0] == DOMAIN for id_tuple in device.identifiers)
        ]

        if devices:
            _LOGGER.info("Removing %d MicroAir device(s) from HA registry", len(devices))
            for device in devices:
                device_reg.async_remove_device(device.id)
    except Exception as exc:
        _LOGGER.error("Failed to clean up MicroAir devices: %s", exc)


# ------------------------------------------------------------------
# Config file helper
# ------------------------------------------------------------------

async def _read_config(hass: HomeAssistant):
    """Read the JSON config file written by the add-on. Returns dict or None."""
    try:
        def _read():
            path = Path(CONFIG_PATH)
            if not path.exists():
                return None
            return path.read_text(encoding="utf-8")

        text = await hass.async_add_executor_job(_read)
        if text is None:
            return None
        return json.loads(text)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        _LOGGER.warning("Config file error: %s", exc)
        return None


# ------------------------------------------------------------------
# Suicide pattern — monitor add-on presence
# ------------------------------------------------------------------

async def _monitor_addon_status(hass: HomeAssistant, slug: str):
    """Monitor add-on status and perform cleanup if uninstalled.

    Uses the Supervisor REST API directly to avoid dependency on internal
    HA Python APIs (is_hassio, hass.components.hassio) that change between releases.
    """
    # Wait for HA to fully start and Add-ons to initialize
    await asyncio.sleep(120)

    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        _LOGGER.warning("No SUPERVISOR_TOKEN — not running on HA OS. Cannot verify add-on status.")
        return

    supervisor = os.environ.get("SUPERVISOR", "http://supervisor")
    if not supervisor.startswith("http://") and not supervisor.startswith("https://"):
        supervisor = f"http://{supervisor}"
    headers = {"Authorization": f"Bearer {token}"}
    session = async_get_clientsession(hass)
    timeout = aiohttp.ClientTimeout(total=10)

    max_retries = 3
    retry_delay = 30
    confirmed_missing = 0

    for attempt in range(max_retries):
        try:
            # Source 1: Check individual add-on info
            is_in_info = False
            async with session.get(
                f"{supervisor}/addons/{slug}/info",
                headers=headers, timeout=timeout
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # An add-on info endpoint can return 200 even if uninstalled (if it's in the store)
                    # The definitive check is if it has a non-null "version"
                    if data.get("data", {}).get("version"):
                        is_in_info = True

            # Source 2: Check the full installed add-ons list
            is_in_list = False
            async with session.get(
                f"{supervisor}/addons",
                headers=headers, timeout=timeout
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    addons = data.get("data", {}).get("addons", [])
                    is_in_list = any(a.get("slug") == slug for a in addons)

            if is_in_info or is_in_list:
                _LOGGER.debug("LibreCoach add-on (%s) verified present.", slug)
                return

            _LOGGER.warning("LibreCoach add-on (%s) not found in Double-Lock check (Attempt %d/%d).", slug, attempt + 1, max_retries)
            confirmed_missing += 1
        except Exception as exc:
            _LOGGER.warning("Double-Lock check error (Attempt %d/%d): [%s] %s", attempt + 1, max_retries, type(exc).__name__, exc)

        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)

    # Destructive cleanup ONLY if every retry definitively confirmed the add-on is missing.
    # If any attempt errored (ambiguous), assume present and let the bridge continue.
    if confirmed_missing == max_retries:
        await _perform_self_cleanup(hass, slug)
    else:
        _LOGGER.warning("Double-Lock: Could not definitively confirm %s status after %d retries (API errors). Assuming present — bridge continues.", slug, max_retries)


async def _perform_self_cleanup(hass: HomeAssistant, slug: str):
    """Clean up configuration if original add-on is gone."""
    _LOGGER.critical("Automated Cleanup: Removing LibreCoach BLE configuration as add-on is no longer installed")

    # 1. Notify User
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": "LibreCoach BLE: Automated Cleanup",
            "message": (
                f"The LibreCoach add-on ({slug}) was uninstalled. "
                "The accompanying Bluetooth integration has automatically removed its entry from configuration.yaml. "
                "The integration will be completely gone following the next Home Assistant restart."
            ),
            "notification_id": "librecoach_ble_cleanup",
        }
    )

    # 2. Cleanup configuration.yaml and marker file
    config_yaml = hass.config.path("configuration.yaml")

    def _do_file_cleanup():
        try:
            content = Path(config_yaml).read_text(encoding="utf-8")
            lines = content.splitlines()
            new_lines = [l for l in lines if not l.strip().startswith("librecoach_ble:")]
            if len(lines) != len(new_lines):
                Path(config_yaml).write_text("\n".join(new_lines), encoding="utf-8")
            Path(CONFIG_PATH).unlink(missing_ok=True)
            return True
        except Exception as exc:
            return exc

    result = await hass.async_add_executor_job(_do_file_cleanup)
    if result is True:
        _LOGGER.info("Removed 'librecoach_ble:' from configuration.yaml and deleted marker file")
    else:
        _LOGGER.error("Failed to clean up files: %s", result)

    # Note: As per HA standards and best practices, we avoid deleting
    # the custom_component files themselves during runtime.


async def async_unload(hass: HomeAssistant) -> bool:
    """Unload the integration."""
    data = hass.data.get(DOMAIN, {})
    manager = data.get("manager")
    if manager:
        await manager.stop()
    return True
