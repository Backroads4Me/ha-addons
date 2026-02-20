from abc import ABC, abstractmethod

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
    async def poll(self, client) -> dict | None:
        """Connect, authenticate, read status.
        `client` is a connected BleakClient.
        Return parsed state dict, or None on failure.
        """

    @abstractmethod
    async def handle_command(self, client, command: dict) -> bool:
        """Handle an inbound MQTT command.
        `client` is a connected BleakClient.
        `command` is the parsed JSON from the MQTT /set topic.
        Return True on success.
        """

    @abstractmethod
    def parse_status(self, raw: dict) -> dict:
        """Parse raw device JSON into the state dict published to MQTT.
        Pure function — no BLE or async needed.
        """
