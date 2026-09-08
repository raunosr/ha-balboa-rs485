"""Immutable Balboa envelopes and incremental stream framing."""

from dataclasses import dataclass

from .crc import crc8

DELIMITER = 0x7E
MIN_LENGTH = 5
MAX_LENGTH = 125


@dataclass(frozen=True, slots=True)
class Frame:
    """Header octets retained separately for classic and future channel policies."""

    address: int
    family: int
    message_type: int
    payload: bytes = b""

    def __post_init__(self) -> None:
        for octet in (self.address, self.family, self.message_type):
            if type(octet) is not int or not 0 <= octet <= 255:
                raise ValueError("header fields must be integer octets (0..255)")
        if not isinstance(self.payload, bytes):
            raise TypeError("payload must be immutable bytes")
        if len(self.payload) > MAX_LENGTH - MIN_LENGTH:
            raise ValueError("payload exceeds the supported 120-byte limit")


def encode_frame(frame: Frame) -> bytes:
    """Serialize an envelope; this function performs no I/O."""
    body = bytes((len(frame.payload) + 5, frame.address, frame.family, frame.message_type))
    body += frame.payload
    return bytes((DELIMITER,)) + body + bytes((crc8(body), DELIMITER))


class FrameParser:
    """Accumulate TCP chunks independently of message boundaries."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.counters = FrameCounters()

    @property
    def buffered_bytes(self) -> int:
        """Number of residual bytes waiting for completion."""
        return len(self._buffer)

    def reset(self) -> None:
        """Discard a connection's unfinished bytes; preserve cumulative counters."""
        self._discard(len(self._buffer))

    def feed(self, chunk: bytes) -> list[Frame]:
        """Return completed envelopes and retain any unfinished tail."""
        self._buffer.extend(chunk)
        frames = []
        while self._buffer:
            offset = self._buffer.find(DELIMITER)
            if offset == -1:
                self._discard(len(self._buffer))
                break
            if offset:
                self._discard(offset)
            if len(self._buffer) < 2:
                break
            length = self._buffer[1]
            if not MIN_LENGTH <= length <= MAX_LENGTH:
                self.counters.invalid_length += 1
                self._discard(1)
                continue
            if len(self._buffer) < length + 2:
                break
            wire = bytes(self._buffer[: length + 2])
            if wire[-1] != DELIMITER:
                self.counters.invalid_end += 1
                self._discard(1)
                continue
            if crc8(wire[1:-2]) != wire[-2]:
                self.counters.crc_errors += 1
                self._discard(1)
                continue
            frames.append(Frame(wire[2], wire[3], wire[4], wire[5:-2]))
            self.counters.rx_frames += 1
            del self._buffer[: length + 2]
        return frames

    def _discard(self, count: int) -> None:
        self.counters.discarded_bytes += count
        del self._buffer[:count]


@dataclass(slots=True)
class FrameCounters:
    """Rejected candidates can overlap; counters are not mutually exclusive."""

    rx_frames: int = 0
    crc_errors: int = 0
    invalid_length: int = 0
    invalid_end: int = 0
    discarded_bytes: int = 0
