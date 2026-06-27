from abc import ABC, abstractmethod
from dataclasses import dataclass


class AuthenticationError(Exception):
    """Raised when a device rejects credentials (distinct from BLE/connectivity errors).

    The bridge treats this differently from BleakError/OSError/timeout: it is not
    retried at full speed and is surfaced to MQTT as an auth failure rather than a
    generic offline transition.
    """


@dataclass
class StateMessage:
    """A single MQTT publish produced by a device handler.

    Handlers own their own topic shapes. The bridge only routes, publishes, and
    logs these messages — it does not inspect device-specific payloads (e.g. zones).
    """

    topic: str
    payload: str
    retain: bool = False
    qos: int = 1


class BleDeviceHandler(ABC):
    """Base class for LibreCoach BLE device handlers."""

    # --- Class-level attributes (set by each subclass) ---

    @staticmethod
    @abstractmethod
    def device_type() -> str:
        """Short identifier used in MQTT topics. e.g. 'microair'"""

    @staticmethod
    @abstractmethod
    def match_name(name: str) -> bool:
        """Return True if the BLE advertisement name belongs to this handler.
        Called during device discovery.
        Example: name.startswith("EasyTouch")
        """

    # --- Instance methods ---

    @abstractmethod
    async def authenticate(self, client) -> bool:
        """Authenticate with device after connection.
        Called by bridge's _ensure_connected.
        Return True on success, False on authentication failure.
        Raising AuthenticationError is equivalent to returning False.
        Connectivity problems should raise BleakError/OSError/TimeoutError instead.
        """

    @abstractmethod
    async def poll(self, client) -> dict | None:
        """Read device status.
        `client` is a connected, authenticated BleakClient.
        Return parsed state dict, or None on failure.
        """

    @abstractmethod
    async def handle_command(self, client, command: dict) -> dict | bool:
        """Handle an inbound MQTT command.
        `client` is a connected, authenticated BleakClient.
        `command` is the parsed JSON from the MQTT /set topic.
        Return parsed state dict for verification, or True on success.
        """

    @abstractmethod
    def parse_status(self, raw: dict) -> dict:
        """Parse raw device JSON into the state dict published to MQTT.
        Pure function — no BLE or async needed.
        """

    @abstractmethod
    def state_messages(self, parsed: dict) -> list[StateMessage]:
        """Translate a parsed state dict into the MQTT messages to publish.

        This is where device-specific topic construction lives (e.g. Micro-Air
        zone topics). The bridge calls this and publishes the result verbatim, so
        the bridge stays independent of any device's payload shape.
        """
