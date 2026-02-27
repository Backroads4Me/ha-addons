import asyncio
import csv
import json
import logging
import math
import os
import urllib.request
import urllib.error

import websockets

log = logging.getLogger("vehicle_bridge.geo")

# Constants
POLL_INTERVAL = 60  # seconds
SUPERVISOR_URL = "http://supervisor/core/api"
STARTUP_RETRY_DELAY = 10  # seconds between retries waiting for Supervisor API
STARTUP_MAX_RETRIES = 12  # give up after ~2 minutes
MQTT_TOPIC = "can/status/geo"
EARTH_RADIUS_MILES = 3958.8
CSV_PATH = os.path.join(os.path.dirname(__file__), "us_cities.csv")


def _haversine(lat1, lon1, lat2, lon2):
    """Return distance in miles between two coordinates."""
    lat1, lon1, lat2, lon2 = (math.radians(v) for v in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_MILES * 2 * math.asin(math.sqrt(min(a, 1.0)))


class GeoBridge:
    def __init__(self, config, mqtt):
        self.config = config
        self.mqtt = mqtt
        self.name = "geo"

        self._primary = (config.get("geo_device_tracker_primary") or "").strip()
        self._secondary = (config.get("geo_device_tracker_secondary") or "").strip()
        self._threshold = float(config.get("geo_update_threshold", 10))
        self._token = os.environ.get("SUPERVISOR_TOKEN", "")

        self._cities = []
        self._last_lat = None
        self._last_lon = None
        self._poll_task = None
        self._stopping = False

    def is_enabled(self):
        return bool(self.config.get("geo_enabled")) and bool(self._primary)

    async def start(self):
        self._cities = await asyncio.get_running_loop().run_in_executor(
            None, self._load_cities
        )
        log.info("Loaded %d US cities for geo lookup", len(self._cities))

        if not self._token:
            log.error("SUPERVISOR_TOKEN not available — geo bridge cannot run")
            return

        # Fetch initial position with retries (Supervisor may not be ready)
        for attempt in range(1, STARTUP_MAX_RETRIES + 1):
            coords = await self._fetch_coordinates()
            if coords is not None:
                lat, lon, elev, tracker_id = coords
                if await self._check_and_update(lat, lon, elev, tracker_id, force=True):
                    break
            log.warning(
                "Waiting for HA API (attempt %d/%d), retrying in %ds",
                attempt, STARTUP_MAX_RETRIES, STARTUP_RETRY_DELAY,
            )
            await asyncio.sleep(STARTUP_RETRY_DELAY)
        else:
            log.warning("Could not update location at startup — will retry in poll loop")

        self._poll_task = asyncio.create_task(self._poll_loop())
        log.info(
            "Geo bridge started (primary=%s, secondary=%s, threshold=%.1f mi)",
            self._primary, self._secondary or "none", self._threshold,
        )

    async def stop(self):
        self._stopping = True
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        self.mqtt.publish(MQTT_TOPIC, json.dumps({"status": "offline"}), retain=True)

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    async def _poll_loop(self):
        while not self._stopping:
            try:
                await asyncio.sleep(POLL_INTERVAL)
                coords = await self._fetch_coordinates()
                if coords is None:
                    self.mqtt.publish(
                        MQTT_TOPIC,
                        json.dumps({"status": "unavailable"}),
                        retain=True,
                    )
                    continue
                lat, lon, elev, tracker_id = coords
                await self._check_and_update(lat, lon, elev, tracker_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Error in geo poll loop")

    # ------------------------------------------------------------------
    # Coordinate fetching
    # ------------------------------------------------------------------

    async def _fetch_coordinates(self):
        """Try primary, then secondary tracker. Returns (lat, lon, elev) or None."""
        for entity_id in (self._primary, self._secondary):
            if not entity_id:
                continue
            result = await self._get_tracker_coords(entity_id)
            if result is not None:
                return (*result, entity_id)
        return None

    async def _get_tracker_coords(self, entity_id):
        """Fetch a single device_tracker entity. Returns (lat, lon, elev) or None."""
        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(
                None, self._api_get, f"/states/{entity_id}"
            )
        except Exception as exc:
            log.debug("Failed to fetch %s: %s", entity_id, exc)
            return None

        if data is None:
            return None

        state = data.get("state", "")
        if state in ("unavailable", "unknown"):
            log.debug("Tracker %s state is %s", entity_id, state)
            return None

        attrs = data.get("attributes", {})
        lat = attrs.get("latitude")
        lon = attrs.get("longitude")
        if lat is None or lon is None:
            log.debug("Tracker %s missing lat/lon attributes", entity_id)
            return None

        lat = float(lat)
        lon = float(lon)

        # Elevation: try altitude/elevation attribute, convert if needed
        elev = self._extract_elevation(attrs)

        return (lat, lon, elev)

    @staticmethod
    def _extract_elevation(attrs):
        """Extract elevation in meters from entity attributes, or None."""
        raw = attrs.get("altitude")
        if raw is None:
            raw = attrs.get("elevation")
        if raw is None:
            return None
        try:
            value = float(raw)
        except (ValueError, TypeError):
            return None

        # Check unit — default to meters per HA convention
        unit = str(attrs.get("unit_of_measurement", "")).lower().strip()
        if unit in ("ft", "feet"):
            value *= 0.3048

        return round(value, 1)

    # ------------------------------------------------------------------
    # Update logic
    # ------------------------------------------------------------------

    async def _check_and_update(self, lat, lon, gps_elev, tracker_id, force=False):
        """Compare position to last known, update HA if threshold exceeded."""
        if self._last_lat is not None and not force:
            dist = _haversine(self._last_lat, self._last_lon, lat, lon)
            if dist < self._threshold:
                return

        distance_moved = 0.0
        if self._last_lat is not None:
            distance_moved = _haversine(self._last_lat, self._last_lon, lat, lon)

        # Find nearest city
        city = self._find_nearest_city(lat, lon)
        if city is None:
            log.warning("No city match found for %.4f, %.4f", lat, lon)
            timezone = None
            city_name = "Unknown"
            state_name = "Unknown"
            city_elev = None
        else:
            timezone = city["timezone"]
            city_name = city["name"]
            state_name = city["state"]
            city_elev = city["elevation_m"]

        # Elevation: prefer GPS, fall back to city DEM
        elevation = gps_elev if gps_elev is not None else city_elev

        # Build HA core config update
        ha_config = {"latitude": lat, "longitude": lon}
        if timezone:
            ha_config["time_zone"] = timezone
        if elevation is not None:
            ha_config["elevation"] = int(round(elevation))

        # Push to HA via WebSocket API (config/core/update is WebSocket-only)
        try:
            await self._ws_update_config(ha_config)
            log.info(
                "Updated HA location: %s, %s → %s (%.1f mi moved)",
                city_name, state_name, timezone, distance_moved,
            )
        except Exception:
            log.exception("Failed to update HA core config")
            return False

        self._last_lat = lat
        self._last_lon = lon

        # Publish status to MQTT
        payload = {
            "status": "online",
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "elevation": int(round(elevation)) if elevation is not None else None,
            "timezone": timezone,
            "city": city_name,
            "state": state_name,
            "tracker": tracker_id,
            "distance_moved": round(distance_moved, 1),
        }
        self.mqtt.publish(MQTT_TOPIC, json.dumps(payload), retain=True)
        return True

    # ------------------------------------------------------------------
    # City lookup
    # ------------------------------------------------------------------

    def _load_cities(self):
        """Load us_cities.csv into a list of dicts."""
        cities = []
        if not os.path.exists(CSV_PATH):
            log.error("City data file not found: %s", CSV_PATH)
            return cities
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    cities.append({
                        "lat": float(row["lat"]),
                        "lon": float(row["lon"]),
                        "name": row["name"],
                        "state": row["state"],
                        "timezone": row["timezone"],
                        "elevation_m": float(row["elevation_m"]),
                    })
                except (ValueError, KeyError) as exc:
                    log.debug("Skipping malformed city row: %s", exc)
        return cities

    def _find_nearest_city(self, lat, lon):
        """Find the nearest city by Haversine distance. Returns dict or None."""
        if not self._cities:
            return None
        best = None
        best_dist = float("inf")
        for city in self._cities:
            d = _haversine(lat, lon, city["lat"], city["lon"])
            if d < best_dist:
                best_dist = d
                best = city
        return best

    # ------------------------------------------------------------------
    # Supervisor API helpers
    # ------------------------------------------------------------------

    def _api_get(self, path):
        """GET from Supervisor API. Returns parsed JSON or None."""
        url = f"{SUPERVISOR_URL}{path}"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", f"Bearer {self._token}")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            log.debug("API GET %s failed: %s", path, exc)
            return None

    async def _ws_update_config(self, config_data):
        """Update HA core config via WebSocket API.
        
        NOTE: The HA REST API does not support updating core configuration 
        (like latitude, longitude, and elevation). The `config/core/update` 
        command is exclusively exposed via the WebSocket API.
        """
        url = "ws://supervisor/core/websocket"
        try:
            # 15s timeout protects the poll loop from hanging if the Supervisor proxy stalls
            async with asyncio.timeout(15):
                async with websockets.connect(
                    url,
                    additional_headers={
                        "Authorization": f"Bearer {self._token}",
                    },
                ) as ws:
                    # Step 1: Receive auth_required
                    msg = json.loads(await ws.recv())
                    if msg.get("type") != "auth_required":
                        raise RuntimeError(f"Expected auth_required, got: {msg}")

                    # Step 2: Authenticate with Supervisor token
                    await ws.send(json.dumps({
                        "type": "auth",
                        "access_token": self._token,
                    }))
                    msg = json.loads(await ws.recv())
                    if msg.get("type") != "auth_ok":
                        raise RuntimeError(f"Auth failed: {msg}")

                    # Step 3: Send config/core/update command
                    await ws.send(json.dumps({
                        "id": 1,
                        "type": "config/core/update",
                        **config_data,
                    }))
                    msg = json.loads(await ws.recv())
                    if not msg.get("success"):
                        raise RuntimeError(
                            f"config/core/update failed: {msg.get('error', msg)}"
                        )
        except TimeoutError:
            raise RuntimeError("WebSocket config update timed out after 15s")
