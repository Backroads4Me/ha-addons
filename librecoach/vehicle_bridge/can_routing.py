"""CAN-to-MQTT topic routing."""

TOPIC_RAW = "can/raw"
TOPIC_TIMESTAMPED = "can/timestamped"


def topic_for_can_id(_arbitration_id):
    """Return the unfiltered topic for an inbound CAN frame."""
    return TOPIC_RAW


def timestamped_topic_for_can_id(_arbitration_id):
    """Return the timestamp-preserving companion topic for an inbound frame."""
    return TOPIC_TIMESTAMPED


def format_timestamped_frame(message, interface):
    """Format python-can input as a candump -L compatible source record."""
    can_id = (
        f"{message.arbitration_id:08X}"
        if message.is_extended_id
        else f"{message.arbitration_id:03X}"
    )
    return (
        f"({message.timestamp:.6f}) {interface} "
        f"{can_id}#{message.data.hex().upper()}"
    )
