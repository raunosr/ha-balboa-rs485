"""Known supplemental observations, retaining their raw protocol evidence."""

import pytest

from balboa_rs485.protocol.frames import Frame
from balboa_rs485.protocol.messages import (
    FaultLogMessage,
    FilterCyclesMessage,
    MessageDecodeError,
    SetupMessage,
    decode_message,
)

SETUP = Frame(10, 191, 37, bytes.fromhex("00 00 32 63 50 68 00 02 00"))
FILTERS = Frame(10, 191, 35, bytes((8, 0, 2, 30, 0x80 | 20, 15, 1, 0)))
FAULT = Frame(10, 191, 40, bytes((1, 0, 17, 2, 10, 30, 0, 76, 72, 71)))


def test_setup_filter_and_fault_payloads_are_typed_observations():
    setup = decode_message(SETUP)
    assert isinstance(setup, SetupMessage)
    assert setup.low_range_f == (50, 99) and setup.high_range_f == (80, 104)
    filters = decode_message(FILTERS)
    assert isinstance(filters, FilterCyclesMessage)
    assert filters.cycles[0].duration_minutes == 150
    assert filters.cycles[1].start_hour == 20 and filters.cycles[1].enabled
    fault = decode_message(FAULT)
    assert isinstance(fault, FaultLogMessage)
    assert fault.code == 17 and fault.count == 1 and fault.entry == 0
    assert fault.frame is FAULT


@pytest.mark.parametrize("frame", [SETUP, FILTERS, FAULT])
@pytest.mark.parametrize("delta", [-1, 1])
def test_extended_messages_reject_wrong_lengths(frame, delta):
    extra = b"\0\0" if frame is SETUP else b"\0"
    data = frame.payload[:-1] if delta < 0 else frame.payload + extra
    with pytest.raises(MessageDecodeError):
        decode_message(Frame(frame.address, frame.family, frame.message_type, data))


def test_extended_setup_retains_opaque_byte_without_changing_temperature_bounds():
    # Documented ten-byte variant; only the agreed bound positions are interpreted.
    frame = Frame(22, 191, 37, SETUP.payload + b"\x02")
    setup = decode_message(frame, response_address=22)
    assert isinstance(setup, SetupMessage)
    assert setup.low_range_f == (50, 99)
    assert setup.high_range_f == (80, 104)
    assert setup.frame is frame


@pytest.mark.parametrize("size", [9, 10])
@pytest.mark.parametrize(
    "bounds", [b"\0\x63\x50\x68", b"\x64\x63\x50\x68", b"\x32\x63\x69\x68", b"\x32\x63\x50\xff"]
)
def test_setup_variants_still_reject_invalid_bounds(size, bounds):
    payload = bytearray(SETUP.payload + b"\0")[:size]
    payload[2:6] = bounds
    with pytest.raises(MessageDecodeError):
        decode_message(Frame(10, 191, 37, bytes(payload)))
