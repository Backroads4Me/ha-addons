import asyncio
import json
import logging
import os
import shutil
from datetime import datetime
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

    The integration is always loaded. Individual BLE device types start and stop
    dynamically from retained librecoach/config/*_enabled MQTT topics.
    """
    _LOGGER.info("LibreCoach BLE integration loading")

    # Read config for credentials and addon slug
    conf = await _read_config(hass)
    if not conf:
        _LOGGER.warning("Config file not found at %s — add-on may not have started yet", CONFIG_PATH)
        conf = {}

    _LOGGER.info(
        "Config loaded: microair_enabled=%s, hughes_enabled=%s, addon_slug=%s",
        conf.get("microair_enabled"), conf.get("hughes_enabled"), conf.get("addon_slug"),
    )

    hass.data[DOMAIN] = {"config": conf, "manager": None, "enabled_types": set()}

    # Suicide pattern monitor
    slug = conf.get("addon_slug")
    if slug:
        # Background task: must NOT be awaited during bootstrap (it sleeps for
        # hours) and must be cancelled on shutdown. async_create_task would hold
        # the startup phase open and survive shutdown, blocking HA from wrapping
        # up start-up and from a clean stop.
        hass.async_create_background_task(
            _monitor_addon_status(hass, slug), name="librecoach_ble_addon_monitor"
        )

    # After HA is fully started (Bluetooth + MQTT ready), subscribe to config toggle.
    # The retained MQTT message triggers bridge start or confirms disabled state.
    async def _on_ha_started(event=None):
        _LOGGER.info("HA started — subscribing to BLE integration toggles")
        for device_type in ("microair", "hughes"):
            await mqtt.async_subscribe(
                hass, f"librecoach/config/{device_type}_enabled",
                _make_config_callback(hass, device_type), qos=1,
            )

    hass.bus.async_listen_once("homeassistant_started", _on_ha_started)

    async def _on_ha_stop(event=None):
        manager = hass.data.get(DOMAIN, {}).get("manager")
        if manager:
            _LOGGER.info("HA stopping — shutting down BLE bridge")
            await manager.stop()

    hass.bus.async_listen_once("homeassistant_stop", _on_ha_stop)
    _LOGGER.info("BLE bridge will activate when MQTT config message arrives")

    return True


# ------------------------------------------------------------------
# MQTT config callback
# ------------------------------------------------------------------

def _make_config_callback(hass: HomeAssistant, device_type: str):
    """Create an MQTT callback that enables or disables one BLE device type."""

    async def _on_config_toggle(msg):
        payload = msg.payload
        if isinstance(payload, bytes):
            payload = payload.decode()
        enabled = str(payload).strip() == "true"

        data = hass.data.get(DOMAIN, {})
        manager = data.get("manager")
        enabled_types = data.setdefault("enabled_types", set())

        if enabled:
            enabled_types.add(device_type)
            if manager is None:
                _LOGGER.info("%s enabled via MQTT — starting BLE bridge", device_type)
                await _start_bridge(hass)
            else:
                manager.enable_device_type(device_type)
                _LOGGER.info("%s enabled — scanning for devices", device_type)
        else:
            enabled_types.discard(device_type)
            if manager is not None:
                await manager.disable_device_type(device_type)
                _LOGGER.info("%s disabled — released its BLE devices", device_type)
                if not enabled_types:
                    await _stop_bridge(hass)
            else:
                _LOGGER.info("%s disabled — bridge not running", device_type)

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

    manager = BleBridgeManager(hass, conf, data.get("enabled_types", set()))
    data["manager"] = manager
    await manager.start()
    _LOGGER.info("BLE bridge started — enabled types: %s", sorted(data.get("enabled_types", set())))


async def _stop_bridge(hass: HomeAssistant):
    """Stop the shared BLE bridge after all device types are disabled."""
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
            _LOGGER.info("Removing %d LibreCoach BLE device(s) from HA registry", len(devices))
            for device in devices:
                device_reg.async_remove_device(device.id)
    except Exception as exc:
        _LOGGER.error("Failed to clean up LibreCoach BLE devices: %s", exc)


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

    # Destructive cleanup requires repeated, unambiguous confirmations spread
    # across hours — Supervisor restarts and HA updates can briefly report
    # incomplete add-on data, and a few seconds of bad answers must never be
    # enough to edit the user's configuration.yaml.
    max_retries = 3
    retry_delay = 3600  # 1 hour between confirmations
    confirmed_missing = 0

    for attempt in range(max_retries):
        try:
            # Gate: only trust an "add-on absent" answer when the Supervisor
            # itself reports healthy. An unhealthy/booting Supervisor returns
            # incomplete data that looks like absence.
            supervisor_healthy = False
            async with session.get(
                f"{supervisor}/supervisor/ping",
                headers=headers, timeout=timeout
            ) as resp:
                supervisor_healthy = resp.status == 200

            if not supervisor_healthy:
                _LOGGER.warning(
                    "Double-Lock (attempt %d/%d): Supervisor ping failed — result inconclusive, not counting as absence.",
                    attempt + 1, max_retries)
                continue

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
                    if not addons:
                        # An empty installed-add-ons list on a system running this
                        # integration is implausible (Supervisor still initializing
                        # or partial response) — treat as inconclusive.
                        _LOGGER.warning(
                            "Double-Lock (attempt %d/%d): Supervisor returned an empty add-on list — inconclusive, not counting as absence.",
                            attempt + 1, max_retries)
                        continue
                    is_in_list = any(a.get("slug") == slug for a in addons)

            if is_in_info or is_in_list:
                _LOGGER.debug("LibreCoach add-on (%s) verified present.", slug)
                return

            confirmed_missing += 1
            _LOGGER.warning(
                "Double-Lock (attempt %d/%d): Supervisor healthy (GET /supervisor/ping), but %s absent from both GET /addons/%s/info and GET /addons. Confirmed absences: %d/%d.",
                attempt + 1, max_retries, slug, slug, confirmed_missing, max_retries)
        except Exception as exc:
            _LOGGER.warning("Double-Lock check error (Attempt %d/%d): [%s] %s", attempt + 1, max_retries, type(exc).__name__, exc)
        finally:
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)

    # Destructive cleanup ONLY if every retry definitively confirmed the add-on
    # is missing while the Supervisor reported healthy. Any inconclusive or
    # errored attempt means we assume present and let the bridge continue.
    if confirmed_missing == max_retries:
        _LOGGER.warning(
            "Double-Lock: %s confirmed absent %d times over ~%d hours with a healthy Supervisor (endpoints checked: /supervisor/ping, /addons/%s/info, /addons). Proceeding with cleanup.",
            slug, confirmed_missing, (max_retries - 1) * retry_delay // 3600, slug)
        await _perform_self_cleanup(hass, slug)
    else:
        _LOGGER.warning(
            "Double-Lock: Could not definitively confirm %s absence (%d/%d confirmed; rest inconclusive or errored). Assuming present — bridge continues.",
            slug, confirmed_missing, max_retries)


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
                # Timestamped safety copy before any edit to configuration.yaml
                backup = f"{config_yaml}.librecoach-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                shutil.copy2(config_yaml, backup)
                Path(config_yaml).write_text("\n".join(new_lines), encoding="utf-8")
            Path(CONFIG_PATH).unlink(missing_ok=True)
            return True
        except Exception as exc:
            return exc

    result = await hass.async_add_executor_job(_do_file_cleanup)
    if result is True:
        _LOGGER.info(
            "Removed 'librecoach_ble:' from configuration.yaml (timestamped backup saved alongside it) and deleted marker file")
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
