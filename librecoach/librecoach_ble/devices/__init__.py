"""Device handler registry.

To add a new device type:
1. Create a new module in this directory
2. Implement a class that extends BleDeviceHandler
3. Import and add it to DEVICE_HANDLERS below
"""
from .microair import MicroAirHandler
from .hughes import HughesHandler

# All registered device handlers — bridge iterates this for discovery matching
DEVICE_HANDLERS = [
    MicroAirHandler,
    HughesHandler,
]
