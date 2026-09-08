"""Persist intent before submitting observed-state goals to an existing runtime.

This layer owns neither sockets nor raw commands. The caller supplies storage,
wall-clock time, the controls policy, and periodic calls to async_tick.
"""

import asyncio
from collections.abc import Awaitable, Callable

from .command.engine import Stage
from .protocol.messages import TemperatureUnit
from .range_session import RangeSession, SessionConflict
from .runtime import SpaRuntime
from .session import Session, SessionPhase
from .state.model import Control, Value

type SessionIntent = Session | RangeSession
type SaveSession = Callable[[SessionIntent | None], Awaitable[None]]
_TERMINAL = (Stage.VERIFIED, Stage.FAILED, Stage.CANCELLED, Stage.SUPERSEDED)


class SessionRunner:
    def __init__(
        self,
        runtime: SpaRuntime,
        *,
        save: SaveSession,
        enabled: Callable[[], bool],
        now: Callable[[], float],
        session: SessionIntent | None = None,
    ) -> None:
        self.runtime = runtime
        self.session = session
        self._save = save
        self._enabled = enabled
        self._now = now
        self._lock = asyncio.Lock()
        self._intent: int | None = None
        self._attempt: tuple[SessionIntent, Control, Value, int] | None = None
        self._closed = False
        self._expired = False
        self.storage_failed = False
        self.blocked_reason: str | None = None

    def _writable(self) -> None:
        if self._closed:
            raise ValueError("Session controller is closed")
        if self.storage_failed:
            raise ValueError("Session storage is unavailable; reload after repairing storage")

    def pause(self) -> None:
        if self._intent is not None:
            intent = self.runtime.engine.intent(self._intent)
            if intent is not None and intent.stage not in _TERMINAL:
                self.runtime.engine.cancel(intent.control)
            self._intent = None
        self._attempt = None

    def close(self) -> None:
        self._closed = True
        self.pause()

    async def _replace(self, session: SessionIntent | None) -> None:
        self._writable()
        self.pause()
        try:
            await self._save(session)
        except asyncio.CancelledError:
            # A cancelled storage await may have reached disk. Do not choose a
            # conflicting in-memory intent until a new owner reloads the record.
            self.storage_failed = True
            self.blocked_reason = "storage_error"
            raise
        except Exception as err:
            self.storage_failed = True
            self.blocked_reason = "storage_error"
            raise ValueError("Session storage could not be verified") from err
        self.session = session
        if session is None:
            self._expired = False
            self.blocked_reason = None

    async def async_start(
        self, *, end: float, target: float, maintenance: float, unit: TemperatureUnit
    ) -> None:
        async with self._lock:
            self._writable()
            if not self._enabled():
                raise ValueError("Physical controls are disabled")
            if self.session is not None:
                raise ValueError("A heating session is already active")
            await self._replace(
                Session.start(
                    now=self._now(),
                    end=end,
                    target=target,
                    maintenance=maintenance,
                    unit=unit,
                    state=self.runtime.state,
                )
            )
        await self.async_tick()

    async def async_cancel(self) -> None:
        async with self._lock:
            self._writable()
            if self.session is None:
                raise ValueError("No active heating session")
            await self._replace(self.session.cancel())
        await self.async_tick()

    async def async_start_bathing(self, *, end: float, minimum_c: float = 36.5) -> None:
        async with self._lock:
            self._writable()
            if not self._enabled():
                raise ValueError("Physical controls are disabled")
            if self.session is not None:
                raise ValueError("A heating session is already active")
            await self._replace(
                RangeSession.start(
                    now=self._now(), end=end, minimum_c=minimum_c, state=self.runtime.state
                )
            )
        await self.async_tick()

    async def async_adjust(self, *, seconds: float) -> None:
        async with self._lock:
            self._writable()
            if self.session is None:
                raise ValueError("No active heating session")
            if self._expired:
                raise ValueError("An ended session cannot be adjusted")
            await self._replace(self.session.adjust(now=self._now(), seconds=seconds))
        await self.async_tick()

    async def async_abandon(self) -> None:
        """Forget durable intent before an explicit manual setpoint, without restoring."""
        async with self._lock:
            self._writable()
            if self.session is not None:
                await self._replace(None)

    async def async_manual_change(
        self,
        control: Control,
        desired: Value,
        *,
        apply: Callable[[Control, Value], Awaitable[None]],
    ) -> None:
        """Serialize settings with durable session creation, including the write await."""
        async with self._lock:
            self._writable()
            if control not in (
                Control.TARGET,
                Control.HIGH_RANGE,
                Control.HEAT_MODE,
                Control.TEMPERATURE_UNIT,
                Control.HOLD,
                Control.NORMAL_OPERATION,
                Control.SOAK,
            ):
                raise ValueError("Not a session-related setting")
            state = self.runtime.state
            if not self._enabled() or state is None:
                raise ValueError("Physical controls are disabled or observed state is unavailable")
            state.validate(control, desired)
            if self.session is not None:
                if control != Control.TARGET:
                    if state.hold and (
                        control == Control.HOLD
                        and desired is False
                        or control == Control.NORMAL_OPERATION
                        and desired is True
                    ):
                        # Explicit exit from externally entered Hold can unblock restoration.
                        await apply(control, desired)
                        return
                    raise ValueError(
                        "End the heating session before changing range, heat mode or unit"
                    )
                if isinstance(self.session, RangeSession):
                    if not state.status.high_range:
                        raise ValueError(
                            "End the session before editing an externally selected range"
                        )
                    await self._replace(self.session.release_target())
                else:
                    await self._replace(None)
            await apply(control, desired)

    def _guard(self, session: SessionIntent, epoch: int) -> Callable[[], bool]:
        expired = False

        def valid() -> bool:
            nonlocal expired
            expired |= self._now() >= session.end_time
            if self.session == session:
                self._expired |= expired
            return (
                not self._closed
                and not self.storage_failed
                and self._enabled()
                and self.session == session
                and self.runtime.connection.snapshot.epoch == epoch
                and (session.phase == SessionPhase.RESTORING or not expired)
            )

        return valid

    async def async_tick(self) -> None:
        async with self._lock:
            if self._closed or self.storage_failed or self.session is None:
                return
            state = self.runtime.state
            # A sent old goal can still arrive after cancellation. Do not declare
            # restoration complete using its pre-send observation.
            settled = not self.runtime.engine.busy and self.runtime.engine.resync_epoch is None
            now = max(self._now(), self.session.end_time) if self._expired else self._now()
            updated = self.session.reconcile(now=now, state=state if settled else None)
            if updated != self.session:
                await self._replace(updated)
            if self.session is None:
                return
            self.blocked_reason = None
            if not self._enabled() or not self.runtime.connection.snapshot.available:
                self.blocked_reason = "controls_disabled" if not self._enabled() else "unavailable"
                self.pause()
                return
            if self.runtime.engine.busy or self.runtime.engine.resync_epoch is not None:
                self.blocked_reason = "waiting_for_verification"
                return
            try:
                control, goal = self.session.goal(self.runtime.state)
                attempt = (
                    self.session,
                    control,
                    goal,
                    self.runtime.connection.snapshot.epoch,
                )
                if self.runtime.state is not None and self.runtime.state.value(control) == goal:
                    self._attempt = attempt
                elif self._attempt != attempt:
                    self._intent = self.runtime.request(
                        control,
                        goal,
                        valid=self._guard(self.session, self.runtime.connection.snapshot.epoch),
                    ).id
                    self._attempt = attempt
                    self.blocked_reason = "waiting_for_verification"
                else:
                    intent = self.runtime.engine.intent(self._intent) if self._intent else None
                    self.blocked_reason = (
                        "command_failed"
                        if intent and intent.stage == Stage.FAILED
                        else "waiting_for_verification"
                        if intent and intent.stage not in _TERMINAL
                        else "setpoint_changed"
                    )
            except SessionConflict:
                self.pause()
                self.blocked_reason = "external_change"
            except ValueError:
                self.pause()
                self.blocked_reason = "unsupported_state"
