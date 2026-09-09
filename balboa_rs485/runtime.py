"""Compose the independent command/state layers with the transport lifecycle."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from types import TracebackType
from typing import Self

from .command.engine import TERMINAL, Action, CommandEngine, Intent, Stage
from .protocol.configuration import Query, encode_query
from .protocol.messages import FaultLogMessage, FilterCyclesMessage, Message, SetupMessage
from .protocol.settings import FilterSchedule
from .state.model import Control, SpaState, Value
from .transport.connection import Snapshot, SpaConnection
from .transport.participant import Transmission
from .transport.policy import Mode
from .transport.timing import Timing


class _Commands:
    def __init__(self, engine: CommandEngine, timing: Timing) -> None:
        self.engine = engine
        self.timing = timing
        self.setup: SetupMessage | None = None
        self.filters: FilterCyclesMessage | None = None
        self.filters_at: float | None = None
        self._refresh: Query | None = None
        self.refresh_version = 0
        self.refresh_success = False
        self.fault: FaultLogMessage | None = None
        self._epoch = 0
        self._next_metadata_refresh = 0.0
        self._configuration: str | None = None
        self._queries = (Query.SETUP, Query.FILTERS, Query.FAULT)
        self._query_index = 0
        self._pending: Query | None = None
        self._sent_at = 0.0
        self._attempts = 0
        self._filter_confirmation_reads = 0
        self.failures: list[str] = []
        self.guards: dict[Control, tuple[int, Callable[[], bool]]] = {}

    @property
    def recovery_epoch(self) -> int | None:
        return self.engine.resync_epoch

    @property
    def metadata_complete(self) -> bool:
        return self._query_index >= len(self._queries)

    @property
    def metadata_idle(self) -> bool:
        return self.metadata_complete and self._pending is None and self._refresh is None

    @property
    def busy(self) -> bool:
        return self.engine.busy or self._pending is not None

    def update(self, snapshot: Snapshot, now: float) -> None:
        signature = snapshot.configuration.signature if snapshot.configuration else None
        if (
            snapshot.epoch != self._epoch
            or signature is not None
            and signature != self._configuration
        ):
            self._epoch, self._configuration = snapshot.epoch, signature
            self.setup = None
            self.filters = None
            self.filters_at = None
            self._refresh = None
            self.refresh_success = False
            self.refresh_version += 1
            self.fault = None
            self._pending = None
            self._query_index = self._attempts = 0
            self._filter_confirmation_reads = 0
            self._next_metadata_refresh = now + self.timing.metadata_refresh_interval
            self.failures.clear()
        if self.metadata_idle and not self.engine.busy and now >= self._next_metadata_refresh:
            self._query_index = self._attempts = 0
            self._next_metadata_refresh = now + self.timing.metadata_refresh_interval
            self.failures.clear()
        if self._pending is not None and now - self._sent_at >= self.timing.query_timeout:
            self._pending = None
            if self._attempts >= self.timing.query_attempts:
                if self._refresh is not None:
                    self._refresh = None
                    self.refresh_success = False
                    self.refresh_version += 1
                else:
                    self.failures.append(self._queries[self._query_index].name)
                    self._query_index += 1
                self._attempts = 0
        if snapshot.configuration is not None and snapshot.status is not None:
            assert snapshot.health.last_status is not None
            state = SpaState(
                snapshot.status,
                snapshot.configuration,
                snapshot.epoch,
                snapshot.status_sequence,
                snapshot.health.last_status,
                snapshot.available,
                self.setup,
                self.filters,
                self.fault,
                self.filters_at,
            )
            self.engine.observe(state, now=now)
        else:
            self.engine.tick(now=now)
            self.engine.suspend(now=now)

    def prepare(self, now: float) -> Transmission | None:
        # Synchronous admission immediately before TX, including after reconnect.
        # A session deadline may pass between its periodic scheduler ticks.
        for control, (identifier, valid) in tuple(self.guards.items()):
            intent = self.engine.intent(identifier)
            if intent is None or intent.stage in (
                Stage.VERIFIED,
                Stage.FAILED,
                Stage.CANCELLED,
                Stage.SUPERSEDED,
            ):
                del self.guards[control]
            elif not valid():
                self.engine.cancel(control)
                del self.guards[control]
        if self._pending is not None:
            return None
        if self._query_index < len(self._queries):
            query = self._queries[self._query_index]
            return Transmission(encode_query(query), query)
        if self._refresh is not None:
            return Transmission(encode_query(self._refresh), self._refresh)
        action = self.engine.next_action(now=now)
        return Transmission(action.frame, action) if action is not None else None

    def sent(self, message: Transmission, at: float, cts_at: float | None) -> None:
        if isinstance(message.token, Query):
            self._pending, self._sent_at = message.token, at
            self._attempts += 1
            pending = self.engine.pending_transaction
            if (
                message.token == Query.FILTERS
                and pending is not None
                and pending.action.intent.control == Control.FILTERS
            ):
                self._filter_confirmation_reads += 1
            return
        assert isinstance(message.token, Action)
        self.engine.sent(replace(message.token, frame=message.frame), at=at, cts_at=cts_at)
        if message.token.intent.control == Control.FILTERS:
            self._filter_confirmation_reads = 0
            self.refresh_filters()

    def refresh_filters(self) -> None:
        if not self.metadata_complete or self._pending is not None or self._refresh is not None:
            raise ValueError("Metadata query already pending or not synchronized")
        self._refresh = Query.FILTERS
        self._attempts = 0
        self.refresh_success = False

    def received(self, message: Message, epoch: int, at: float) -> None:
        if epoch != self._epoch:
            return
        if isinstance(message, SetupMessage):
            self.setup = message
            matches = self._pending == Query.SETUP
        elif isinstance(message, FilterCyclesMessage):
            self.filters = message
            matches = self._pending == Query.FILTERS
            # A reflected write is not a queried readback/confirmation.
            self.filters_at = at if matches else None
        elif isinstance(message, FaultLogMessage):
            self.fault = message
            matches = self._pending == Query.FAULT
        else:
            return
        if matches:
            self._pending = None
            pending = self.engine.pending_transaction
            if (
                isinstance(message, FilterCyclesMessage)
                and self._refresh == Query.FILTERS
                and pending is not None
                and pending.action.epoch == epoch
                and pending.action.intent.control == Control.FILTERS
                and FilterSchedule(message.cycles) != pending.action.intent.desired
                and self._filter_confirmation_reads < self.timing.query_attempts
            ):
                # The write can precede its controller commit or a queued old
                # reply. Re-read at a fresh bus slot, never repeat the write.
                # Lost replies and mismatches share the same finite read budget;
                # neither resets the physical transaction's confirmation deadline.
                self._attempts = self._filter_confirmation_reads
                return
            self._attempts = 0
            if self._refresh is not None:
                self._refresh = None
                self.refresh_version += 1
                self.refresh_success = True
            else:
                self._query_index += 1

    def disconnected(self, epoch: int, now: float) -> None:
        self.engine.suspend(now=now)


class SpaRuntime:
    """Intent API. Auto stays passive; explicit modes are not hardware validation."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        mode: Mode = Mode.AUTO,
        allow_unarbitrated_writes: bool = False,
        timing: Timing | None = None,
        engine: CommandEngine | None = None,
    ) -> None:
        policy = timing or Timing()
        # Filter confirmation includes explicit read queries, unlike status-only
        # controls. Allow the existing finite query budget plus one healthy-status
        # window for bus admission/confirmation; never extend a sent deadline.
        self.engine = engine or CommandEngine(
            filter_confirmation_timeout=max(
                4.0, policy.query_timeout * policy.query_attempts + policy.degrade_after
            )
        )
        self._commands = _Commands(self.engine, policy)
        self._filter_lock = asyncio.Lock()
        self.connection = SpaConnection(
            host,
            port,
            mode=mode,
            timing=policy,
            participant=self._commands,
            allow_unarbitrated_writes=allow_unarbitrated_writes,
        )

    @property
    def metadata_complete(self) -> bool:
        return self._commands.metadata_complete

    @property
    def metadata_failures(self) -> tuple[str, ...]:
        return tuple(self._commands.failures)

    @property
    def state(self) -> SpaState | None:
        return self.engine.state

    def request(
        self,
        control: Control,
        desired: Value,
        *,
        valid: Callable[[], bool] | None = None,
        deadline: float | None = None,
        defer_for: float = 0,
        replace_pending: bool = False,
    ) -> Intent:
        existing = self.engine.latest(control)
        replacing_pump = (
            replace_pending
            and isinstance(control, Control)
            and control.value.startswith("pump")
            and existing is not None
            and existing.stage not in TERMINAL
        )
        if not self.connection.snapshot.available and not replacing_pump:
            raise ValueError("Connection is not READY for physical commands")
        if control in (
            Control.CLOCK_TIME,
            Control.SOAK,
            Control.NORMAL_OPERATION,
            Control.ACK_REMINDER,
        ):
            epoch, caller_valid = self.connection.snapshot.epoch, valid

            def clock_valid() -> bool:
                return self.connection.snapshot.epoch == epoch and (
                    caller_valid is None or caller_valid()
                )

            valid = clock_valid
        intent = self.engine.request(
            control,
            desired,
            now=asyncio.get_running_loop().time(),
            deadline=deadline,
            defer_for=defer_for,
            replace_pending=replace_pending,
        )
        if valid is None:
            self._commands.guards.pop(control, None)
        else:
            self._commands.guards[control] = (intent.id, valid)
        return intent

    async def async_update_filter(
        self,
        index: int,
        *,
        start: int | None = None,
        end: int | None = None,
        enabled: bool | None = None,
        valid: Callable[[], bool] | None = None,
    ) -> None:
        """Fresh read/modify/write/readback; never replay a whole record after reconnect."""
        async with self._filter_lock:
            snapshot = self.connection.snapshot
            if not snapshot.available or valid is not None and not valid():
                raise ValueError("Filter controls are unavailable")
            epoch = snapshot.epoch
            await self.connection.wait_for(
                lambda s: s.epoch != epoch or self._commands.metadata_idle, timeout=15
            )
            if self.connection.snapshot.epoch != epoch:
                raise ValueError("Connection changed while waiting for filter read")
            generation = self._commands.refresh_version
            self._commands.refresh_filters()
            await self.connection.wait_for(
                lambda s: s.epoch != epoch or self._commands.refresh_version != generation,
                timeout=15,
            )
            state = self.state
            if (
                self.connection.snapshot.epoch != epoch
                or not self._commands.refresh_success
                or state is None
                or state.filters is None
            ):
                raise ValueError("A fresh filter read could not be verified")
            original = FilterSchedule(state.filters.cycles)
            desired = original.update(index, start=start, end=end, enabled=enabled)

            def admitted() -> bool:
                return self.connection.snapshot.epoch == epoch and (valid is None or valid())

            if not admitted():
                raise ValueError("Filter controls were disabled during readback")
            intent = self.request(Control.FILTERS, desired, valid=admitted)
            try:
                result = await self.wait_for_intent(intent.id)
                if result.stage != Stage.VERIFIED:
                    raise ValueError("Filter change was not verified; read current settings")
            finally:
                current = self.engine.intent(intent.id)
                if current is not None and current.stage != Stage.VERIFIED:
                    self.engine.cancel(Control.FILTERS)

    async def wait_for_intent(self, identifier: int, *, timeout: float | None = None) -> Intent:  # noqa: ASYNC109
        def completed(_: Snapshot) -> bool:
            intent = self.engine.intent(identifier)
            if intent is None:
                raise ValueError("Intent is unknown or no longer in bounded history")
            return intent.stage in TERMINAL

        item = self.engine.intent(identifier)
        remaining = (
            max(0, item.deadline - asyncio.get_running_loop().time())
            if item and item.deadline is not None
            else (20.0 if timeout is None else timeout)
        )
        try:
            await self.connection.wait_for(
                completed, timeout=remaining if timeout is None else min(timeout, remaining)
            )
        except TimeoutError:
            self.engine.tick(now=asyncio.get_running_loop().time())
            if not completed(self.connection.snapshot):
                raise
        intent = self.engine.intent(identifier)
        assert intent is not None
        return intent

    async def __aenter__(self) -> Self:
        await self.connection.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.connection.__aexit__(exc_type, exc, tb)
