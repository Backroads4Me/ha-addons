from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from can_routing import (
    TOPIC_RAW,
    TOPIC_TIMESTAMPED,
    format_timestamped_frame,
    timestamped_topic_for_can_id,
    topic_for_can_id,
)


def test_all_can_identifiers_use_raw_topic():
    for can_id in (
        0x19FECA21,  # RV-C DM_RV
        0x18FECA21,  # J1939 DM1
        0x19FFB821,  # DIGITAL_INPUT_STATUS
        0x19FFFF21,  # DATE_TIME_STATUS
        0x18E84DFE,  # ACKNOWLEDGEMENT
        0x123,       # standard identifier
    ):
        assert topic_for_can_id(can_id) == TOPIC_RAW


def test_all_can_identifiers_use_timestamped_companion_topic():
    for can_id in (0x19FECA21, 0x18FECA21, 0x19FFB821, 0x19FFFF21, 0x123):
        assert timestamped_topic_for_can_id(can_id) == TOPIC_TIMESTAMPED


def test_timestamped_frame_is_candump_compatible():
    class Message:
        arbitration_id = 0x19FEDB21
        is_extended_id = True
        timestamp = 1704067200.125
        data = bytes.fromhex("0102030405060708")

    assert format_timestamped_frame(Message(), "can0") == (
        "(1704067200.125000) can0 19FEDB21#0102030405060708"
    )


def test_standard_identifier_is_published_and_uses_three_hex_digits():
    class Message:
        arbitration_id = 0x123
        is_extended_id = False
        timestamp = 1704067200.5
        data = bytes.fromhex("0102")

    assert format_timestamped_frame(Message(), "can0") == (
        "(1704067200.500000) can0 123#0102"
    )
