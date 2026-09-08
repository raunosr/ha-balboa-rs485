"""One owned socket runtime; optional participant owns physical command semantics."""

import asyncio
import random
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from enum import StrEnum
from types import TracebackType
from typing import Self

from ..protocol.configuration import Configuration, Query, encode_query
from ..protocol.frames import FrameParser, encode_frame
from ..protocol.messages import (
    CapabilitiesMessage,
    MessageDecodeError,
    ReadyMessage,
    StatusMessage,
    SystemInformationMessage,
    decode_message,
)
from .channel import AssignmentStatus
from .participant import Participant
from .policy import BusPolicy, Mode
from .timing import Backoff, Timing

_DEFAULT_TIMING = Timing()


class ConnectionState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    WAITING_FOR_FRAME = "WAITING_FOR_FRAME"
    DETECTING_PROTOCOL = "DETECTING_PROTOCOL"
    SYNCHRONIZING = "SYNCHRONIZING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    RECOVERING = "RECOVERING"


@dataclass(frozen=True, slots=True)
class ConnectionEvent:
    at: float
    epoch: int
    kind: str
    detail: str


@dataclass(frozen=True, slots=True)
class Health:
    last_rx: float | None
    last_valid_frame: float | None
    last_status: float | None
    last_ready: float | None
    status_stale: bool
    frames_per_second: float
    ready_interval_mean: float | None
    ready_interval_max: float | None
    ready_missing: bool


@dataclass(frozen=True, slots=True)
class Snapshot:
    state: ConnectionState
    mode: Mode
    candidate: Mode
    epoch: int
    configuration: Configuration | None
    configuration_revision: int
    status: StatusMessage | None
    tx_frames: int
    health: Health
    rx_frames: int
    crc_errors: int
    discarded_bytes: int
    invalid_messages: int
    received_bytes: int
    recoveries: int
    last_error: str | None
    status_sequence: int
    channel: int | None
    channel_failure: str | None
    channel_assignment: AssignmentStatus
    assignment_requests: int

    @property
    def available(self) -> bool:
        return self.state == ConnectionState.READY

    @property
    def observed_status(self) -> StatusMessage | None:
        """Fresh decoded telemetry, independent of configuration/control readiness."""
        if (
            self.state
            in (
                ConnectionState.DISCONNECTED,
                ConnectionState.CONNECTING,
                ConnectionState.WAITING_FOR_FRAME,
                ConnectionState.RECOVERING,
            )
            or self.health.status_stale
        ):
            return None
        return self.status


class SpaConnection:
    """Async context owning exactly one background task and one TCP connection."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        mode: Mode = Mode.AUTO,
        timing: Timing = _DEFAULT_TIMING,
        jitter: Callable[[], float] = random.random,
        participant: Participant | None = None,
    ) -> None:
        if not host.strip() or not 1 <= port <= 65535:
            raise ValueError("host must be nonempty and port must be 1..65535")
        self.host, self.port, self.requested_mode = host, port, Mode(mode)
        self.timing = timing
        self._participant = participant
        self._backoff = Backoff(timing, jitter=jitter)
        self._state = ConnectionState.DISCONNECTED
        self._policy = BusPolicy(self.requested_mode)
        self._parser = FrameParser()
        self._task: asyncio.Task[None] | None = None
        self._changed = asyncio.Event()
        self._events: deque[ConnectionEvent] = deque(maxlen=128)
        self._epoch = 0
        self._configuration: Configuration | None = None
        self._revision = 0
        self._last_signature: str | None = None
        self._status: StatusMessage | None = None
        self._last_status: float | None = None
        self._status_sequence = 0
        self._sync_status_sequence = 0
        self._sync_started: float | None = None
        self._information: SystemInformationMessage | None = None
        self._capabilities: CapabilitiesMessage | None = None
        self._pending: Query | None = None
        self._pending_since = 0.0
        self._attempts = 0
        self._tx_frames = 0
        self._last_rx: float | None = None
        self._last_valid: float | None = None
        self._last_ready: float | None = None
        self._now = 0.0
        self._healthy_since: float | None = None
        self._sync_active = False
        self._sync_committed = False
        self._refresh_at = 0.0
        self._traffic: deque[tuple[int, int]] = deque(maxlen=100)
        self._opened_at = 0.0
        self._invalid_messages = 0
        self._received_bytes = 0
        self._recoveries = 0
        self._last_error: str | None = None
        self._ready_intervals: deque[float] = deque(maxlen=128)
        self._healthy_reset_done = False
        self._wire_tail = b""
        self._assignment_requests = 0
        self._assignment_nonces: set[bytes] = set()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def snapshot(self) -> Snapshot:
        return Snapshot(
            self._state,
            self._policy.mode,
            self._policy.candidate,
            self._epoch,
            self._configuration,
            self._revision,
            self._status,
            self._tx_frames,
            Health(
                self._last_rx,
                self._last_valid,
                self._last_status,
                self._last_ready,
                self._last_status is None
                or self._now - self._last_status >= self.timing.stale_after,
                sum(count for _, count in self._traffic)
                / min(10, max(0.1, self._now - self._opened_at)),
                sum(self._ready_intervals) / len(self._ready_intervals)
                if self._ready_intervals
                else None,
                max(self._ready_intervals) if self._ready_intervals else None,
                self._policy.mode in (Mode.CLASSIC_RS485, Mode.CHANNEL_RS485)
                and self._now
                - (self._last_ready if self._last_ready is not None else self._opened_at)
                >= self.timing.degrade_after,
            ),
            self._parser.counters.rx_frames,
            self._parser.counters.crc_errors,
            self._parser.counters.discarded_bytes,
            self._invalid_messages,
            self._received_bytes,
            self._recoveries,
            self._last_error,
            self._status_sequence,
            self._policy.channel.channel,
            self._policy.channel.failure,
            self._policy.channel.assignment_status,
            self._assignment_requests,
        )

    @property
    def events(self) -> tuple[ConnectionEvent, ...]:
        return tuple(self._events)

    def _publish(self) -> None:
        self._changed.set()
        self._changed = asyncio.Event()

    def _event(self, kind: str, detail: str) -> None:
        self._events.append(
            ConnectionEvent(asyncio.get_running_loop().time(), self._epoch, kind, detail)
        )

    def _transition(self, state: ConnectionState) -> None:
        if self._state != state:
            self._state = state
            self._event("state", state.value)
            self._publish()

    async def wait_for(
        self,
        predicate: Callable[[Snapshot], bool],
        *,
        timeout: float = 12,  # noqa: ASYNC109 -- bounded observation helper
    ) -> Snapshot:
        """Wait for an observed snapshot; cancellation does not stop the connection."""
        async with asyncio.timeout(timeout):
            while True:
                changed = self._changed
                snapshot = self.snapshot
                if predicate(snapshot):
                    return snapshot
                if self._task is not None and self._task.done():
                    await self._task
                    raise RuntimeError("Connection stopped before the requested observation")
                await changed.wait()

    async def __aenter__(self) -> Self:
        if self._task is not None:
            raise RuntimeError("Connection already started; use a new instance")
        self._task = asyncio.create_task(self._run(), name="balboa-connection")
        self._task.add_done_callback(lambda _: self._publish())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._task is not None
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task

    async def _run(self) -> None:
        while True:
            try:
                await self._session()
            except (OSError, TimeoutError):
                delay = self._backoff.next_delay()
                self._event("backoff", f"{delay:.3f}s")
                await asyncio.sleep(delay)

    def _begin_sync(self, now: float) -> None:
        self._sync_started = now
        self._sync_status_sequence = self._status_sequence
        self._information = self._capabilities = None
        self._sync_active, self._sync_committed = True, False
        self._attempts = 0
        self._pending = None
        self._transition(ConnectionState.SYNCHRONIZING)

    async def _session(self) -> None:
        writer: asyncio.StreamWriter | None = None
        self._policy = BusPolicy(self.requested_mode)
        # A random collision must not make an old socket's reply look current.
        while self._policy.channel.nonce in self._assignment_nonces:
            nonce = (int.from_bytes(self._policy.channel.nonce, "big") + 1) % 65536
            self._policy.channel.nonce = nonce.to_bytes(2, "big")
        self._sync_started = None
        self._sync_active = self._sync_committed = False
        self._last_status = None
        self._last_rx = self._last_valid = self._last_ready = None
        self._healthy_since = None
        self._information = None
        self._capabilities = None
        self._attempts = 0
        self._traffic.clear()
        self._wire_tail = b""
        self._ready_intervals.clear()
        self._healthy_reset_done = False
        try:
            self._transition(ConnectionState.CONNECTING)
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), self.timing.connect
            )
            self._epoch += 1
            opened_at = asyncio.get_running_loop().time()
            self._opened_at = opened_at
            assert writer is not None
            self._transition(ConnectionState.WAITING_FOR_FRAME)
            while True:
                try:
                    async with asyncio.timeout(self.timing.tick):
                        chunk = await reader.read(4096)
                except TimeoutError:
                    chunk = None
                if chunk == b"":
                    raise ConnectionError("EOF")
                now = asyncio.get_running_loop().time()
                self._now = now
                if self._last_valid is None and now - opened_at >= self.timing.first_frame:
                    raise TimeoutError("first valid frame deadline")
                if chunk:
                    self._last_rx = now
                    self._received_bytes += len(chunk)
                    self._wire_tail = (self._wire_tail + chunk)[-127:]
                frames = self._parser.feed(chunk) if chunk else []
                bucket = int(now * 10)
                while self._traffic and self._traffic[0][0] <= bucket - 100:
                    self._traffic.popleft()
                if frames:
                    self._last_valid = now
                    if self._traffic and self._traffic[-1][0] == bucket:
                        stamp, count = self._traffic.pop()
                        self._traffic.append((stamp, count + len(frames)))
                    else:
                        self._traffic.append((bucket, len(frames)))
                if frames and self._state == ConnectionState.WAITING_FOR_FRAME:
                    self._transition(ConnectionState.DETECTING_PROTOCOL)
                if (
                    self._pending is not None
                    and now - self._pending_since >= self.timing.query_timeout
                ):
                    self._event("query_timeout", self._pending.name)
                    self._pending = None
                    if self._attempts >= self.timing.query_attempts:
                        raise TimeoutError("configuration query attempts exhausted")
                previous_channel = self._policy.channel_seen
                for frame in frames:
                    try:
                        message = decode_message(
                            frame,
                            response_address=self._policy.address,
                            ready_address=self._policy.cts_address,
                        )
                    except MessageDecodeError:
                        self._invalid_messages += 1
                        continue
                    self._policy.observe(frame)
                    if self._participant is not None:
                        self._participant.received(message, self._epoch, now)
                    if isinstance(message, StatusMessage):
                        self._status, self._last_status = message, now
                        self._status_sequence += 1
                    elif isinstance(message, ReadyMessage):
                        if self._last_ready is not None:
                            self._ready_intervals.append(now - self._last_ready)
                        self._last_ready = now
                    elif (
                        isinstance(message, SystemInformationMessage)
                        and self._pending == Query.INFORMATION
                    ):
                        self._information, self._pending = message, None
                        self._attempts = 0
                    elif (
                        isinstance(message, CapabilitiesMessage)
                        and self._pending == Query.CAPABILITIES
                    ):
                        self._capabilities, self._pending = message, None
                        self._attempts = 0
                if (
                    self._policy.channel_seen
                    and not previous_channel
                    and self.requested_mode != Mode.CHANNEL_RS485
                ):
                    self._pending = None
                    self._configuration = None
                    self._information = self._capabilities = None
                    self._sync_active = self._sync_committed = False
                    self._event(
                        "mode_veto", "Channel evidence: query transmission disabled for epoch"
                    )
                ages = [now - (self._last_valid if self._last_valid is not None else opened_at)]
                batch_fresh = (
                    bool(frames)
                    and not self._parser.buffered_bytes
                    and (self._wire_tail.endswith(encode_frame(frames[-1])))
                )
                management_sent = False
                self._policy.channel.consider_assignments(frames, at=now)
                if (
                    self.requested_mode == Mode.CHANNEL_RS485
                    and self._policy.channel.assignment_expired
                    and self._assignment_requests < 3
                ):
                    # Retire the missed slot and nonce; reconnect/back off using
                    # the existing lifetime budget, never retry a stale ACK.
                    raise TimeoutError("Channel assignment slot missed; bounded reconnect")
                if self.requested_mode == Mode.CHANNEL_RS485 and batch_fresh:
                    channel = self._policy.channel
                    response = channel.reply(frames, at=now)
                    if response is not None and (
                        asyncio.get_running_loop().time() - now <= self.timing.cts_window
                    ):
                        if response.message_type == 1 and self._assignment_requests >= 3:
                            channel.failure = (
                                "Lifetime assignment budget exhausted; restart explicitly"
                            )
                        else:
                            writer.write(encode_frame(response))
                            channel.sent(response, at=now)
                            self._assignment_requests += int(response.message_type == 1)
                            if response.message_type == 1:
                                self._assignment_nonces.add(channel.nonce)
                            self._tx_frames += 1
                            self._event("channel_tx", str(response.message_type))
                            management_sent = True
                            async with asyncio.timeout(self.timing.cts_window):
                                await writer.drain()
                supported = self._policy.supported
                if supported:
                    ages.append(
                        now - (self._last_status if self._last_status is not None else opened_at)
                    )
                    if self._policy.mode in (Mode.CLASSIC_RS485, Mode.CHANNEL_RS485):
                        ages.append(
                            now - (self._last_ready if self._last_ready is not None else opened_at)
                        )
                if max(ages) >= self.timing.recover_after:
                    raise TimeoutError("required traffic hard deadline")
                degraded = max(ages) >= self.timing.degrade_after
                if supported:
                    if (
                        self._sync_started is None
                        or not self._sync_active
                        and now >= self._refresh_at
                        and (self._participant is None or not self._participant.busy)
                    ):
                        self._begin_sync(now)
                    if not self._sync_committed and self._information and self._capabilities:
                        self._configuration = Configuration(self._information, self._capabilities)
                        if self._configuration.signature != self._last_signature:
                            self._revision += 1
                            self._last_signature = self._configuration.signature
                        self._event("configuration", self._last_signature)
                        self._sync_committed = True
                    ready = (
                        self._sync_committed and self._status_sequence > self._sync_status_sequence
                    )
                    if ready and self._sync_active:
                        self._sync_active = False
                        self._refresh_at = now + self.timing.refresh_interval
                    if (
                        self._sync_active
                        and self._sync_started is not None
                        and now - self._sync_started >= self.timing.sync_timeout
                    ):
                        raise TimeoutError("configuration synchronization deadline")
                    self._transition(
                        ConnectionState.DEGRADED
                        if degraded
                        else (ConnectionState.READY if ready else ConnectionState.SYNCHRONIZING)
                    )
                    if (
                        not degraded
                        and not management_sent
                        and not self._sync_committed
                        and self._pending is None
                        and self._policy.allows_query(
                            frames,
                            received_at=now,
                            now=asyncio.get_running_loop().time(),
                            residual=int(not batch_fresh),
                            cts_window=self.timing.cts_window,
                        )
                    ):
                        self._pending = (
                            Query.INFORMATION if self._information is None else Query.CAPABILITIES
                        )
                        self._pending_since = now
                        self._attempts += 1
                        writer.write(
                            encode_frame(
                                replace(
                                    encode_query(self._pending),
                                    address=self._policy.address,
                                )
                            )
                        )
                        self._tx_frames += 1
                        self._event("query_tx", self._pending.name)
                        async with asyncio.timeout(self.timing.cts_window):
                            await writer.drain()
                elif self._last_valid is not None:
                    self._transition(
                        ConnectionState.DEGRADED if degraded else ConnectionState.DETECTING_PROTOCOL
                    )
                if self._state == ConnectionState.READY:
                    if self._healthy_since is None:
                        self._healthy_since = now
                    elif (
                        not self._healthy_reset_done
                        and now - self._healthy_since >= self.timing.healthy_reset
                    ):
                        self._backoff.reset()
                        self._healthy_reset_done = True
                        self._event("backoff_reset", "Sustained READY health")
                else:
                    self._healthy_since = None
                    self._healthy_reset_done = False
                if self._participant is not None:
                    self._participant.update(self.snapshot, now)
                    if self._participant.recovery_epoch == self._epoch:
                        raise ConnectionError("Physical command requests state resynchronization")
                    if self._state == ConnectionState.READY:
                        outbound = self._participant.prepare(now)
                        if (
                            outbound is not None
                            and not management_sent
                            and self._policy.allows_query(
                                frames,
                                received_at=now,
                                now=asyncio.get_running_loop().time(),
                                residual=int(not batch_fresh),
                                cts_window=self.timing.cts_window,
                            )
                        ):
                            outbound = replace(
                                outbound,
                                frame=replace(outbound.frame, address=self._policy.address),
                            )
                            writer.write(encode_frame(outbound.frame))
                            self._tx_frames += 1
                            self._participant.sent(
                                outbound,
                                asyncio.get_running_loop().time(),
                                now if self._policy.mode != Mode.BWA_TCP else None,
                            )
                            async with asyncio.timeout(self.timing.cts_window):
                                await writer.drain()
                if self.requested_mode == Mode.CHANNEL_RS485 and not management_sent:
                    idle = self._policy.channel.idle_reply(frames)
                    if idle is not None and self._policy.allows_query(
                        frames,
                        received_at=now,
                        now=asyncio.get_running_loop().time(),
                        residual=int(not batch_fresh),
                        cts_window=self.timing.cts_window,
                    ):
                        writer.write(encode_frame(idle))
                        self._tx_frames += 1
                        async with asyncio.timeout(self.timing.cts_window):
                            await writer.drain()
                self._publish()
        except (OSError, TimeoutError) as error:
            self._recoveries += 1
            self._last_error = str(error)
            self._event("recovery", str(error))
            self._transition(ConnectionState.RECOVERING)
            raise
        finally:
            self._parser.reset()
            self._pending = None
            self._configuration = None
            self._status = None
            self._transition(ConnectionState.DISCONNECTED)
            if self._participant is not None:
                self._participant.disconnected(self._epoch, asyncio.get_running_loop().time())
            if writer is not None:
                writer.close()
                try:
                    async with asyncio.timeout(self.timing.close):
                        await writer.wait_closed()
                except (TimeoutError, ConnectionError):
                    writer.transport.abort()
