"""Strict subset of documented channel assignment; no quiet-channel adoption."""

from dataclasses import dataclass

from ..protocol.frames import Frame


@dataclass(frozen=True, slots=True)
class AssignmentStatus:
    """Bounded epoch evidence without raw frames, addresses or client nonces."""

    requested: bool
    responses: int
    correlated: int
    reply_opportunities: int
    pending: bool = False
    ack_on_cts: bool = False


class ChannelSession:
    """One request per socket epoch; ambiguous/non-echoing assignments fail closed."""

    def __init__(self, *, nonce: bytes) -> None:
        if not isinstance(nonce, bytes) or len(nonce) != 2:
            raise ValueError("A two-byte client nonce is required")
        self.nonce = nonce
        self.channel: int | None = None
        self.ready = False
        self._requested_at: float | None = None
        self._acked = False
        self.failure: str | None = None
        self.assignment_expired = False
        self._clients: set[int] = set()
        self._responses = 0
        self._correlated = 0
        self._reply_opportunities = 0
        self._pending_channel: int | None = None
        self._ack_on_cts = False
        self._reply_on_cts = False

    @property
    def assignment_status(self) -> AssignmentStatus:
        return AssignmentStatus(
            self._requested_at is not None,
            self._responses,
            self._correlated,
            self._reply_opportunities,
            self._pending_channel is not None and not self._acked and not self.failure,
            self._ack_on_cts,
        )

    def consider_assignments(self, frames: list[Frame], *, at: float) -> None:
        """Remember correlation, not a TX credit, across coalesced TCP reads.

        A candidate is not ownership. Only an immediate assignment reply or a
        fresh CTS for that explicitly offered address may carry its single ACK.
        Firmware which never polls an unacknowledged address still fails closed.
        """
        self.expire(at=at)
        if self.failure or self._acked or self._requested_at is None:
            return
        if not 0 <= at - self._requested_at < 2:
            return
        for frame in frames:
            if (
                (frame.address, frame.family, frame.message_type) == (254, 191, 2)
                and len(frame.payload) == 3
                and frame.payload[1:] == self.nonce
            ):
                if self._pending_channel not in (None, frame.payload[0]):
                    self.failure = "Conflicting correlated channel assignments"
                    return
                if 0x10 <= frame.payload[0] <= 0x2F and frame.payload[0] not in self._clients:
                    self._pending_channel = frame.payload[0]

    def expire(self, *, at: float) -> None:
        """Report a missed handshake; never turn a timeout into a blind retry."""
        if (
            not self.failure
            and self._requested_at is not None
            and not self._acked
            and at - self._requested_at >= 2
        ):
            self.assignment_expired = True
            self.failure = "Channel assignment timed out; physical controls remain blocked"

    def reply(self, frames: list[Frame], *, at: float) -> Frame | None:
        self.consider_assignments(frames, at=at)
        if not frames or self.failure:
            return None
        frame = frames[-1]
        if self.channel is not None and self._acked and frame == Frame(self.channel, 191, 4):
            return Frame(frame.address, 191, 5, b"\x04\x08\0")
        if self._requested_at is None and frame == Frame(254, 191, 0):
            return Frame(254, 191, 1, b"\x02" + self.nonce)
        if (
            self._requested_at is not None
            and not self._acked
            and 0 <= at - self._requested_at < 2
            and self._pending_channel is not None
            and self._pending_channel not in self._clients
            and frame
            in (
                Frame(254, 191, 2, bytes((self._pending_channel,)) + self.nonce),
                Frame(self._pending_channel, 191, 6),
            )
        ):
            self._reply_opportunities = min(1_000_000, self._reply_opportunities + 1)
            self._reply_on_cts = frame.message_type == 6
            return Frame(self._pending_channel, 191, 3)
        return None

    def idle_reply(self, frames: list[Frame]) -> Frame | None:
        if (
            self._acked
            and self.channel is not None
            and not self.failure
            and frames
            and frames[-1] == Frame(self.channel, 191, 6)
        ):
            return Frame(frames[-1].address, 191, 7)
        return None

    def sent(self, frame: Frame, *, at: float) -> None:
        if frame.message_type == 1:
            self._requested_at = at
        elif frame.message_type == 3:
            self.channel = frame.address
            self._acked = True
            self._ack_on_cts = self._reply_on_cts

    def observe(self, frame: Frame) -> None:
        if (frame.address, frame.family, frame.message_type) == (254, 191, 2):
            self._responses = min(1_000_000, self._responses + 1)
            if (
                self._requested_at is not None
                and len(frame.payload) == 3
                and frame.payload[1:] == self.nonce
            ):
                self._correlated = min(1_000_000, self._correlated + 1)
        if frame.family in (175, 191) and frame.message_type in (0xC4, 0xCA, 0xCC, 0x16):
            self.failure = "Alternative status/control family unsupported"
            self.ready = False
        if frame.family == 191 and frame.message_type in (3, 5, 7, 17, 32, 34):
            if 0x10 <= frame.address <= 0x2F:
                self._clients.add(frame.address)
            if self.channel is not None and frame.address == self.channel:
                self.failure = "Client traffic on owned channel (collision or echo)"
                self.ready = False
        if not self.failure and self.channel is not None and frame == Frame(self.channel, 191, 6):
            self.ready = True
