"""Framing behavior through the public byte stream interface."""

import random
from dataclasses import FrozenInstanceError

import pytest

from balboa_rs485.protocol.frames import MAX_LENGTH, Frame, FrameParser, encode_frame

GOLDEN = bytes.fromhex("7e1dffaf13000064082d00000100000400000000000000000064000000067e")


def test_external_frame_round_trip() -> None:
    wire = bytes.fromhex("7e 05 0a bf 04 77 7e")
    frame = Frame(address=0x0A, family=0xBF, message_type=0x04, payload=b"")
    assert FrameParser().feed(wire) == [frame]
    assert encode_frame(frame) == wire


def test_corrupt_frame_is_counted_and_next_frame_recovers() -> None:
    good = bytes.fromhex("7e 05 0a bf 04 77 7e")
    bad = good[:-2] + b"\x00\x7e"
    parser = FrameParser()
    assert parser.feed(bad + good) == [Frame(0x0A, 0xBF, 0x04)]
    assert parser.counters.crc_errors == 1
    assert parser.counters.rx_frames == 1


@pytest.mark.parametrize("split", range(len(GOLDEN) + 1))
def test_every_tcp_split_preserves_one_frame(split: int) -> None:
    parser = FrameParser()
    frames = parser.feed(GOLDEN[:split]) + parser.feed(GOLDEN[split:])
    assert len(frames) == 1
    assert encode_frame(frames[0]) == GOLDEN


def test_byte_at_a_time_and_coalesced_frames() -> None:
    parser = FrameParser()
    frames = [frame for byte in GOLDEN * 3 for frame in parser.feed(bytes([byte]))]
    assert len(frames) == 3
    assert parser.feed(GOLDEN * 20) == frames[:1] * 20


@pytest.mark.parametrize("prefix", [b"junk", b"\x00\xff", b"\x7e", b"\x7e\x7e"])
def test_garbage_or_duplicate_delimiter_recovers(prefix: bytes) -> None:
    parser = FrameParser()
    assert len(parser.feed(prefix + GOLDEN)) == 1
    assert parser.counters.discarded_bytes == len(prefix)


@pytest.mark.parametrize("length", [0, 1, 4, 126, 255])
def test_invalid_length_does_not_hide_next_frame(length: int) -> None:
    parser = FrameParser()
    assert len(parser.feed(bytes([0x7E, length]) + GOLDEN)) == 1
    assert parser.counters.invalid_length >= 1


def test_invalid_terminator_does_not_hide_next_frame() -> None:
    parser = FrameParser()
    assert len(parser.feed(GOLDEN[:-1] + b"x" + GOLDEN)) == 1
    assert parser.counters.invalid_end == 1


def test_delimiters_in_payload_are_data() -> None:
    frame = Frame(0x01, 0xBF, 0x99, b"\x7e\x05\x0a\xbf\x04\x77\x7e")
    wire = encode_frame(frame)
    parser = FrameParser()
    assert parser.feed(wire[:-1]) == []
    assert parser.feed(wire[-1:]) == [frame]


def test_partial_frame_reset_cannot_cross_connections() -> None:
    parser = FrameParser()
    assert parser.feed(GOLDEN[:12]) == []
    assert parser.buffered_bytes == 12
    parser.reset()
    assert parser.buffered_bytes == 0
    assert parser.counters.discarded_bytes == 12
    assert len(parser.feed(GOLDEN)) == 1


def test_empty_chunk_is_not_end_of_stream() -> None:
    parser = FrameParser()
    assert parser.feed(GOLDEN[:10]) == []
    assert parser.feed(b"") == []
    assert len(parser.feed(GOLDEN[10:])) == 1


def test_maximum_frame_and_bounded_residual() -> None:
    parser = FrameParser()
    frame = Frame(1, 2, 3, b"x" * (MAX_LENGTH - 5))
    wire = encode_frame(frame)
    assert parser.feed(wire[:-1]) == []
    assert parser.buffered_bytes < MAX_LENGTH + 2
    assert parser.feed(wire[-1:]) == [frame]
    parser.feed(b"garbage" * 100_000)
    assert parser.buffered_bytes == 0


def test_seeded_random_chunks_preserve_stream() -> None:
    rng = random.Random(42)
    frames = [Frame(1, 2, 3, rng.randbytes(rng.randrange(121))) for _ in range(200)]
    stream = b"".join(map(encode_frame, frames))
    parser = FrameParser()
    actual = []
    while stream:
        size = rng.randrange(1, 100)
        actual.extend(parser.feed(stream[:size]))
        stream = stream[size:]
    assert actual == frames


def test_frame_is_immutable() -> None:
    frame = Frame(1, 2, 3)
    with pytest.raises(FrozenInstanceError):
        frame.address = 4


@pytest.mark.parametrize("header", [(-1, 2, 3), (256, 2, 3), (1, -1, 3), (1, 2, 256)])
def test_invalid_header_is_rejected(header: tuple[int, int, int]) -> None:
    with pytest.raises(ValueError, match="octet"):
        Frame(*header)


def test_mutable_payload_is_rejected() -> None:
    with pytest.raises(TypeError, match="bytes"):
        Frame(1, 2, 3, bytearray(b"abc"))


def test_unsupported_payload_length_is_rejected() -> None:
    with pytest.raises(ValueError, match="payload"):
        Frame(1, 2, 3, b"x" * 121)
