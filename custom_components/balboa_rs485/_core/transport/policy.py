"""Conservative protocol detection. Recognition is not write authorization."""

import secrets
from enum import StrEnum

from ..protocol.frames import Frame
from .channel import ChannelSession


class Mode(StrEnum):
    AUTO = "auto"
    UNKNOWN_READ_ONLY = "unknown-read-only"
    BWA_TCP = "bwa-tcp"
    CLASSIC_RS485 = "classic-rs485"
    CHANNEL_RS485 = "channel-rs485"
    DIRECT_RS485_TCP_LAB = "direct-rs485-tcp-lab"


class DirectRs485TcpLabTransport:
    """Fixed 0x0A transmission experiment, not RS485 arbitration or hardware proof.

    The connection enforces literal loopback endpoints. Pace complete receive
    batches so a busy stream cannot turn this lab into a tight write loop.
    """

    def __init__(self) -> None:
        self._last_tx = float("-inf")

    def allows_query(self, frames: list[Frame], *, now: float, residual: int) -> bool:
        if not frames or residual or now - self._last_tx < 0.1:
            return False
        self._last_tx = now
        return True


class ClassicRs485Transport:
    """Consume at most one eligible opportunity from each receive batch."""

    def __init__(self) -> None:
        self._consumed_at = float("-inf")

    def allows_query(
        self,
        frames: list[Frame],
        *,
        received_at: float,
        now: float,
        residual: int,
        cts_window: float,
        address: int = 16,
    ) -> bool:
        if (
            not frames
            or frames[-1] != Frame(address, 191, 6)
            or residual
            or not 0 <= now - received_at <= cts_window
            or received_at <= self._consumed_at
        ):
            return False
        self._consumed_at = received_at
        return True


class BwaTcpTransport:
    """The actual BWA Wi-Fi module arbitrates its downstream bus, not raw Elfin TCP."""

    @staticmethod
    def allows_query() -> bool:
        return True


class ChannelRs485Transport(ChannelSession):
    """Strict correlated negotiation; no channel is invented or reused."""

    @staticmethod
    def allows_query() -> bool:
        return False


class BusPolicy:
    """Epoch-scoped evidence; auto never guesses which overlapping CTS owns the bus."""

    def __init__(self, requested: Mode) -> None:
        self.requested = Mode(requested)
        self.status_seen = False
        self.ready_count = 0
        self.channel_seen = False
        self._direct_blocked = False
        self._direct = DirectRs485TcpLabTransport()
        self._classic = ClassicRs485Transport()
        self.channel = ChannelRs485Transport(nonce=secrets.token_bytes(2))

    def observe(self, frame: Frame) -> None:
        if self.requested == Mode.DIRECT_RS485_TCP_LAB and (
            frame.family in (175, 191)
            and frame.message_type in (0xC4, 0xCA, 0xCC, 0x16)
            or frame.address == 10
            and frame.family == 191
            # BF23 is bidirectional filter data, not proof of another sender.
            and frame.message_type in (3, 5, 7, 17, 32, 33, 34, 39)
        ):
            # A second sender or an echo is ambiguous. Fail closed for this epoch.
            self._direct_blocked = True
        if self.requested == Mode.CHANNEL_RS485:
            self.channel.observe(frame)
        if (
            frame.family == 0xBF
            and (
                frame.message_type in (0, 1, 2, 3, 5, 7)
                or frame.message_type == 6
                and frame.address != 16
            )
            or frame.family in (0xAF, 0xBF)
            and frame.message_type in (0xC4, 0xCA, 0xCC)
        ):
            self.channel_seen = True
        if (frame.address, frame.family, frame.message_type) == (255, 175, 19):
            self.status_seen = True
        if frame == Frame(16, 191, 6):
            self.ready_count = min(3, self.ready_count + 1)

    @property
    def candidate(self) -> Mode:
        if self.channel_seen:
            return Mode.CHANNEL_RS485
        if self.status_seen and self.ready_count >= 3:
            return Mode.CLASSIC_RS485
        return Mode.UNKNOWN_READ_ONLY

    @property
    def mode(self) -> Mode:
        if self.requested == Mode.DIRECT_RS485_TCP_LAB:
            return (
                self.requested
                if self.status_seen and not self._direct_blocked
                else Mode.UNKNOWN_READ_ONLY
            )
        if self.requested == Mode.CHANNEL_RS485:
            return self.requested
        if self.channel_seen:
            return Mode.UNKNOWN_READ_ONLY
        if self.status_seen and self.requested in (Mode.CLASSIC_RS485, Mode.BWA_TCP):
            return self.requested
        return Mode.UNKNOWN_READ_ONLY

    @property
    def supported(self) -> bool:
        return self.mode in (Mode.BWA_TCP, Mode.CLASSIC_RS485, Mode.DIRECT_RS485_TCP_LAB) or (
            self.mode == Mode.CHANNEL_RS485 and self.channel.ready and self.status_seen
        )

    @property
    def address(self) -> int:
        return self.channel.channel if self.channel.channel is not None else 10

    @property
    def cts_address(self) -> int:
        return self.address if self.requested == Mode.CHANNEL_RS485 else 16

    def allows_query(
        self,
        frames: list[Frame],
        *,
        received_at: float,
        now: float,
        residual: int,
        cts_window: float,
    ) -> bool:
        if self.mode == Mode.BWA_TCP:
            return BwaTcpTransport.allows_query()
        if self.mode == Mode.DIRECT_RS485_TCP_LAB:
            return self._direct.allows_query(frames, now=now, residual=residual)
        if self.mode == Mode.CHANNEL_RS485:
            if not self.supported:
                return False
            return self._classic.allows_query(
                frames,
                received_at=received_at,
                now=now,
                residual=residual,
                cts_window=cts_window,
                address=self.cts_address,
            )
        return self.mode == Mode.CLASSIC_RS485 and self._classic.allows_query(
            frames,
            received_at=received_at,
            now=now,
            residual=residual,
            cts_window=cts_window,
        )
