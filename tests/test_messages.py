"""Decode only known message signatures; retain raw wire facts."""

import pytest

from balboa_rs485.protocol.frames import Frame
from balboa_rs485.protocol.messages import (
    HeatMode,
    HeatState,
    MessageDecodeError,
    ReadyMessage,
    StatusMessage,
    TemperatureUnit,
    UnknownMessage,
    decode_message,
)


def test_only_exact_classic_ready_is_recognized() -> None:
    classic = Frame(0x10, 0xBF, 0x06)
    assert decode_message(classic) == ReadyMessage(classic)
    for frame in (Frame(0x11, 0xBF, 0x06), Frame(0x10, 0xAF, 0x06), Frame(0x10, 0xBF, 0)):
        assert decode_message(frame) == UnknownMessage(frame)


def test_status_common_fields_from_synthetic_payload() -> None:
    payload = bytes.fromhex(
        "00 00 36 0c 22 02 00 00 00 01 14 24 09 02 0d 00 00 00 00 00 4c 00 00 00"
    )
    frame = Frame(0xFF, 0xAF, 0x13, payload)
    message = decode_message(frame)
    assert isinstance(message, StatusMessage)
    assert message.frame == frame
    assert message.current_temperature == 27.0
    assert message.target_temperature == 38.0
    assert message.unit is TemperatureUnit.CELSIUS
    assert message.heat_mode is HeatMode.READY_IN_REST
    assert message.heat_state is HeatState.HEATING
    assert message.high_range is True
    assert message.pumps_raw == (0, 1, 2, 0, 1, 2)
    assert message.lights_raw == (1, 3)
    assert message.circulation_pump is True
    assert message.hour == 12 and message.minute == 34


def test_ready_with_payload_is_malformed() -> None:
    with pytest.raises(MessageDecodeError, match="READY"):
        decode_message(Frame(0x10, 0xBF, 0x06, b"x"))


@pytest.mark.parametrize("size", [23, 24, 25, 32])
def test_fahrenheit_status_variants_keep_raw_extensions(size: int) -> None:
    payload = bytearray(size)
    payload[2], payload[20] = 100, 104
    payload[-1] = 0x7E
    message = decode_message(Frame(0xFF, 0xAF, 0x13, bytes(payload)))
    assert isinstance(message, StatusMessage)
    assert message.unit is TemperatureUnit.FAHRENHEIT
    assert message.current_temperature == 100.0
    assert message.target_temperature == 104.0
    assert message.frame.payload[-1] == 0x7E


@pytest.mark.parametrize("size", [0, 20, 22, 33, 120])
def test_unknown_status_lengths_are_rejected(size: int) -> None:
    with pytest.raises(MessageDecodeError, match="STATUS"):
        decode_message(Frame(0xFF, 0xAF, 0x13, bytes(size)))


def test_unknown_bits_and_missing_temperature_are_not_invented() -> None:
    data = bytearray(24)
    data[2] = data[20] = 255
    data[5], data[10], data[11] = 3, 0x30, 3
    message = decode_message(Frame(0xFF, 0xAF, 0x13, bytes(data)))
    assert isinstance(message, StatusMessage)
    assert message.current_temperature is None and message.target_temperature is None
    assert message.heat_mode is HeatMode.UNKNOWN
    assert message.heat_state is HeatState.UNKNOWN
    assert message.pumps_raw[0] == 3


def test_waiting_is_distinct_from_heating() -> None:
    data = bytearray(24)
    data[10] = 0x20
    message = decode_message(Frame(0xFF, 0xAF, 0x13, bytes(data)))
    assert isinstance(message, StatusMessage)
    assert message.heat_state is HeatState.WAITING


def test_unknown_address_and_type_remain_read_only_facts() -> None:
    frame = Frame(0x11, 0xAF, 0x13, b"opaque")
    assert decode_message(frame) == UnknownMessage(frame)


def test_status_exposes_read_only_safety_and_clock_observations() -> None:
    data = bytearray(24)
    data[0], data[1], data[6], data[9], data[21] = 5, 3, 4, 0x23, 8
    message = decode_message(Frame(0xFF, 0xAF, 0x13, bytes(data)))
    assert isinstance(message, StatusMessage)
    assert message.hold is True
    assert message.priming is False
    assert message.reminder == "clean_filter"
    assert message.reminder_code == 4
    assert message.clock_24h is True
    assert message.panel_locked is True
    assert message.settings_locked is True
    data[0], data[1], data[6] = 1, 1, 99
    message = decode_message(Frame(0xFF, 0xAF, 0x13, bytes(data)))
    assert message.hold is False  # Initializing is not Hold (no loose bit-mask test).
    assert message.priming is True
    assert message.reminder == "none"


@pytest.mark.parametrize(
    "hour, minute, expected", [(0, 0, "00:00"), (23, 59, "23:59"), (24, 0, None), (12, 60, None)]
)
def test_observed_clock_does_not_invent_a_time_for_invalid_bytes(hour, minute, expected):
    data = bytearray(24)
    data[3], data[4] = hour, minute
    message = decode_message(Frame(0xFF, 0xAF, 0x13, bytes(data)))
    assert message.clock == expected


@pytest.mark.parametrize(
    "code, expected",
    [(0, "none"), (4, "clean_filter"), (9, "check_sanitizer"), (10, "check_ph"), (99, "unknown")],
)
def test_reminder_keeps_unrecognized_codes_without_claiming_a_measurement(code, expected):
    data = bytearray(24)
    data[1], data[6] = 3, code
    message = decode_message(Frame(0xFF, 0xAF, 0x13, bytes(data)))
    assert message.reminder_code == code
    assert message.reminder == expected
