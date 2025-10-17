
import os
import json
import urllib.request
import urllib.parse
import urllib.error
import time

from ..utils.logger import mLOG

class SupervisorAPI:
    """
    Helper class for interacting with Home Assistant Supervisor REST API
    Replaces nmcli commands for network management within HA addons
    """
    BASE_URL = "http://supervisor"
    def __init__(self):
        self.token = os.environ.get('SUPERVISOR_TOKEN', '')
        if not self.token:
            mLOG.log("WARNING: SUPERVISOR_TOKEN not found in environment", level=mLOG.INFO)
        self.interface = self._get_wireless_interface()

    def _get_wireless_interface(self):
        """Discover the name of the first wireless interface."""
        success, data, error = self._make_request('/network/info')
        if not success:
            mLOG.log(f"Failed to get network info: {error}", level=mLOG.CRITICAL)
            return "wlan0"  # Fallback

        try:
            interfaces = data.get('data', {}).get('interfaces', [])
            for iface in interfaces:
                if iface.get('type') == 'wireless':
                    mLOG.log(f"Found wireless interface: {iface.get('interface')}")
                    return iface.get('interface')
        except Exception as e:
            mLOG.log(f"Error parsing network info: {e}", level=mLOG.CRITICAL)

        mLOG.log("No wireless interface found, falling back to wlan0", level=mLOG.INFO)
        return "wlan0"  # Fallback if no wireless interface is found

    def _make_request(self, endpoint, method='GET', data=None):
        """
        Make authenticated HTTP request to Supervisor API
        Returns: (success: bool, response_data: dict or None, error_msg: str or None)
        """
        url = f"{self.BASE_URL}{endpoint}"
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }

        try:
            if method == 'POST':
                json_data = json.dumps(data).encode('utf-8') if data else b'{}'
                req = urllib.request.Request(url, data=json_data, headers=headers, method='POST')
            else:
                req = urllib.request.Request(url, headers=headers, method='GET')

            with urllib.request.urlopen(req, timeout=30) as response:
                response_body = response.read().decode('utf-8')
                result = json.loads(response_body) if response_body else {}
                mLOG.log(f"API {method} {endpoint}: success")
                return (True, result, None)

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ''
            mLOG.log(f"API {method} {endpoint} failed: HTTP {e.code} - {error_body}", level=mLOG.INFO)
            return (False, None, f"HTTP {e.code}: {error_body}")
        except urllib.error.URLError as e:
            mLOG.log(f"API {method} {endpoint} failed: {str(e.reason)}", level=mLOG.INFO)
            return (False, None, f"Connection error: {str(e.reason)}")
        except Exception as e:
            mLOG.log(f"API {method} {endpoint} failed: {str(e)}", level=mLOG.INFO)
            return (False, None, str(e))

    def get_access_points(self):
        """
        Scan for WiFi access points
        Returns: list of dict with keys: ssid, signal, encrypted (bool)
        """
        success, data, error = self._make_request(f'/network/interface/{self.interface}/accesspoints')
        if not success:
            mLOG.log(f"Failed to scan access points: {error}", level=mLOG.INFO)
            return []

        access_points = []
        try:
            # Supervisor returns: {"result": "ok", "data": {"accesspoints": [...]}}
            aps = data.get('data', {}).get('accesspoints', [])
            for ap in aps:
                # Map Supervisor AP format to our internal format
                ssid = ap.get('ssid', '')
                if not ssid or ssid == '--':
                    continue

                # Signal strength: Supervisor gives dBm (-100 to 0), convert to 0-5 scale
                signal_dbm = ap.get('signal', -100)
                signal_strength = max(0, min(5, int((signal_dbm + 100) / 20)))

                # Check if network is encrypted (mode != 'open')
                auth_mode = ap.get('mode', 'wpa-psk').lower()
                encrypted = (auth_mode != 'open')

                access_points.append({
                    'ssid': ssid,
                    'signal': signal_strength,
                    'encrypt': encrypted
                })

            mLOG.log(f"Found {len(access_points)} access points")
            return access_points

        except Exception as e:
            mLOG.log(f"Error parsing access points: {e}", level=mLOG.INFO)
            return []

    def get_interface_info(self):
        """
        Get current interface configuration and connection status
        Returns: dict with connection info or None on error
        """
        success, data, error = self._make_request(f'/network/interface/{self.interface}/info')
        if not success:
            mLOG.log(f"Failed to get interface info: {error}", level=mLOG.INFO)
            return None

        try:
            # Returns: {"result": "ok", "data": {...}}
            interface_data = data.get('data', {})
            return interface_data
        except Exception as e:
            mLOG.log(f"Error parsing interface info: {e}", level=mLOG.INFO)
            return None

    def update_interface(self, ssid, password="", auth_mode="wpa-psk", hidden=False):
        """
        Configure and connect to a WiFi network
        Args:
            ssid: Network SSID
            password: Network password (empty for open networks)
            auth_mode: Authentication mode ('open' or 'wpa-psk')
            hidden: Whether network broadcasts SSID
        Returns: (success: bool, error_msg: str or None)
        """
        # Build the configuration payload
        config = {
            "ipv4": {"method": "auto"},
            "ipv6": {"method": "auto"},
            "wifi": {
                "mode": "infrastructure",
                "ssid": ssid
            }
        }

        # Add authentication if not open network
        if password and auth_mode != "open":
            config["wifi"]["auth"] = auth_mode
            config["wifi"]["psk"] = password
        else:
            config["wifi"]["auth"] = "open"

        # Hidden network support
        if hidden:
            config["wifi"]["hidden"] = True

        mLOG.log(f"Updating interface with SSID: {ssid}, auth: {config['wifi'].get('auth', 'open')}, hidden: {hidden}")

        success, data, error = self._make_request(
            f'/network/interface/{self.interface}/update',
            method='POST',
            data=config
        )

        if not success:
            return (False, error)

        # Wait briefly for connection to establish
        time.sleep(2)
        return (True, None)

    def disconnect_interface(self):
        """
        Disconnect from current WiFi network
        Returns: (success: bool, error_msg: str or None)
        """
        # To disconnect, we set the interface to disabled or manual with no config
        config = {
            "enabled": False,
            "ipv4": {"method": "disabled"},
            "ipv6": {"method": "disabled"}
        }

        success, data, error = self._make_request(
            f'/network/interface/{self.interface}/update',
            method='POST',
            data=config
        )

        if not success:
            return (False, error)

        return (True, None)

    def test_connection(self):
        """
        Test if Supervisor API is accessible
        Returns: bool
        """
        success, _, _ = self._make_request('/supervisor/ping')
        return success
