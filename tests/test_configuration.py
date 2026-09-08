"""Configuration facts are independent of transport and accessory assumptions."""

import pytest

from balboa_rs485.protocol.configuration import Configuration, Query, encode_query
from balboa_rs485.protocol.frames import Frame
from balboa_rs485.protocol.messages import (
    CapabilitiesMessage,
    MessageDecodeError,
    SystemInformationMessage,
    UnknownMessage,
    decode_message,
)

INFO = Frame(
    0x0A,
    0xBF,
    0x24,
    bytes.fromhex("64 dc 01 02") + b"BP SIM  " + bytes.fromhex("01 12 34 56 78 01 0a 00 01"),
)
CAPS = Frame(0x0A, 0xBF, 0x2E, bytes.fromhex("e4 81 41 82 01 03"))


def test_configuration_decodes_agreed_fields_and_preserves_disputed_bits():
    info, caps = decode_message(INFO), decode_message(CAPS)
    assert isinstance(info, SystemInformationMessage)
    assert isinstance(caps, CapabilitiesMessage)
    assert info.model == "BP SIM"
    assert info.software_id == (100, 220)
    assert info.software_version == (1, 2)
    assert info.setup == 1
    assert info.controller_signature == bytes.fromhex("12 34 56 78")
    assert caps.pumps_raw == (0, 1, 2, 3, 1, 2)
    assert caps.frame is CAPS
    config = Configuration(info, caps)
    assert config.signature.startswith("v1:")
    assert config.signature == Configuration(decode_message(INFO), decode_message(CAPS)).signature
    changed = decode_message(Frame(10, 191, 46, CAPS.payload[:-1] + b"\x04"))
    assert config.signature != Configuration(info, changed).signature


@pytest.mark.parametrize("frame", [INFO, CAPS])
@pytest.mark.parametrize("delta", [-1, 1])
def test_configuration_rejects_wrong_lengths(frame, delta):
    payload = frame.payload[:-1] if delta == -1 else frame.payload + b"\0"
    with pytest.raises(MessageDecodeError):
        decode_message(Frame(frame.address, frame.family, frame.message_type, payload))


def test_configuration_does_not_decode_other_addresses_or_replace_raw_model():
    assert isinstance(decode_message(Frame(11, 191, 36, INFO.payload)), UnknownMessage)
    frame = Frame(10, 191, 36, INFO.payload[:4] + b"\xffP SIM  " + INFO.payload[12:])
    message = decode_message(frame)
    assert message.model == "\ufffdP SIM"
    assert message.frame.payload == frame.payload


def test_only_supported_read_queries_can_be_encoded():
    assert encode_query(Query.INFORMATION) == Frame(10, 191, 34, b"\x02\0\0")
    assert encode_query(Query.CAPABILITIES) == Frame(10, 191, 34, b"\0\0\x01")
    with pytest.raises(ValueError):
        encode_query("pump")
