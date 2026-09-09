"""Latest desired values, one physical transaction, no optimistic observations."""

import math
from collections import deque
from dataclasses import dataclass, replace
from enum import StrEnum

from ..protocol.frames import Frame
from ..state.model import Control, SpaState, Value
from .planning import plan


class Stage(StrEnum):
    QUEUED = "QUEUED"
    WAITING_FOR_BUS = "WAITING_FOR_BUS"
    SENT = "SENT"
    WAITING_FOR_STATE = "WAITING_FOR_STATE"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class Intent:
    id: int
    control: Control
    desired: Value
    requested_at: float
    stage: Stage = Stage.QUEUED
    reason: str | None = None
    reminder_code: int | None = None


@dataclass(frozen=True, slots=True)
class Action:
    intent: Intent
    epoch: int
    sequence: int
    starting_value: Value
    expected: Value
    frame: Frame
    prepared_at: float


@dataclass(frozen=True, slots=True)
class Transaction:
    action: Action
    cts_at: float | None
    sent_at: float
    result: Stage = Stage.WAITING_FOR_STATE
    resulting_value: Value | None = None
    completed_at: float | None = None
    reason: str | None = None

    @property
    def starting_value(self) -> Value:
        return self.action.starting_value

    @property
    def latency(self) -> float | None:
        return None if self.completed_at is None else self.completed_at - self.sent_at

    @property
    def stages(self) -> tuple[tuple[Stage, float], ...]:
        trail = (
            (Stage.QUEUED, self.action.intent.requested_at),
            (Stage.WAITING_FOR_BUS, self.action.prepared_at),
            (Stage.SENT, self.sent_at),
            (Stage.WAITING_FOR_STATE, self.sent_at),
        )
        return trail if self.completed_at is None else trail + ((self.result, self.completed_at),)


class CommandEngine:
    """Pure monotonic state machine; a runtime supplies observations and TX receipts."""

    def __init__(
        self,
        *,
        confirmation_guard: float = 0.2,
        confirmation_timeout: float = 4,
        filter_confirmation_timeout: float | None = None,
        resync_settle: float = 0.5,
        state_max_age: float = 3,
        max_actions: int = 6,
    ) -> None:
        if (
            not all(
                math.isfinite(v) and v > 0
                for v in (confirmation_guard, confirmation_timeout, resync_settle, state_max_age)
            )
            or confirmation_guard >= confirmation_timeout
        ):
            raise ValueError("Require positive finite timing and guard < confirmation_timeout")
        self.confirmation_guard = confirmation_guard
        self.confirmation_timeout = confirmation_timeout
        self.filter_confirmation_timeout = (
            confirmation_timeout
            if filter_confirmation_timeout is None
            else filter_confirmation_timeout
        )
        if (
            not math.isfinite(self.filter_confirmation_timeout)
            or self.filter_confirmation_timeout <= confirmation_guard
        ):
            raise ValueError("Filter confirmation timeout must be finite and exceed guard")
        self.resync_settle = resync_settle
        self.state_max_age = state_max_age
        if type(max_actions) is not int or max_actions < 1:
            raise ValueError("max_actions must be a positive integer")
        self.max_actions = max_actions
        self._actions: dict[Control, int] = {}
        self.state: SpaState | None = None
        self._intents: deque[Intent] = deque(maxlen=100)
        self._latest: dict[Control, int] = {}
        self._active: dict[int, Intent] = {}
        self._history: deque[Transaction] = deque(maxlen=100)
        self._inflight: Transaction | None = None
        self._counter = 0
        self.resync_epoch: int | None = None
        self._settling: tuple[tuple[Value | None, ...], float, int, int] | None = None

    @property
    def history(self) -> tuple[Transaction, ...]:
        return tuple(self._history)

    @property
    def busy(self) -> bool:
        return self._inflight is not None

    @property
    def pending_transaction(self) -> Transaction | None:
        """Immutable receipt for transport-owned readback scheduling, never a TX queue."""
        return self._inflight

    def suspend(self, *, now: float) -> None:
        if self.state is not None:
            self.state = replace(self.state, available=False)
        if self._inflight is not None:
            pending = self._inflight
            self._history[-1] = replace(
                pending,
                result=Stage.CANCELLED,
                completed_at=now,
                reason="Connection lost; physical outcome ambiguous",
            )
            self.resync_epoch = pending.action.epoch
            self._settling = None
            self._inflight = None
            current = self.intent(pending.action.intent.id)
            if current and current.stage not in (Stage.SUPERSEDED, Stage.CANCELLED):
                self._update(
                    pending.action.intent.id,
                    Stage.FAILED if current.control == Control.ACK_REMINDER else Stage.QUEUED,
                    "Reminder acknowledgement outcome ambiguous; not retried"
                    if current.control == Control.ACK_REMINDER
                    else "Waiting for resynchronization",
                )

    def intent(self, identifier: int) -> Intent | None:
        return self._active.get(identifier) or next(
            (item for item in self._intents if item.id == identifier), None
        )

    def _update(self, identifier: int, stage: Stage, reason: str | None = None) -> None:
        if identifier in self._active:
            self._active[identifier] = replace(self._active[identifier], stage=stage, reason=reason)
        for index, item in enumerate(self._intents):
            if item.id == identifier:
                self._intents[index] = replace(item, stage=stage, reason=reason)
                return

    def request(self, control: Control, desired: Value, *, now: float) -> Intent:
        if (
            self.state is None
            or not self.state.available
            or not 0 <= now - self.state.observed_at < self.state_max_age
        ):
            raise ValueError("A fresh, synchronized physical state is required")
        if control == Control.FILTERS and (
            self.state.filters_at is None
            or not 0 <= now - self.state.filters_at < self.state_max_age
        ):
            raise ValueError("A fresh queried filter record is required")
        self.state.validate(control, desired)
        previous = self._latest.get(control)
        if previous is not None:
            existing = self.intent(previous)
            if existing and existing.stage not in (Stage.VERIFIED, Stage.FAILED, Stage.CANCELLED):
                self._update(previous, Stage.SUPERSEDED)
            self._active.pop(previous, None)
        self._counter += 1
        item = Intent(
            self._counter,
            control,
            desired,
            now,
            reminder_code=self.state.status.reminder_code
            if control == Control.ACK_REMINDER
            else None,
        )
        self._intents.append(item)
        self._latest[control] = item.id
        self._active[item.id] = item
        self._actions[control] = 0
        return item

    def cancel(self, control: Control) -> None:
        identifier = self._latest.get(control)
        if identifier is not None:
            self._update(identifier, Stage.CANCELLED, "Cancelled by caller")

    def observe(self, state: SpaState, *, now: float) -> None:
        if self.state is not None and (
            state.epoch < self.state.epoch
            or state.epoch == self.state.epoch
            and (state.sequence < self.state.sequence or state.observed_at < self.state.observed_at)
        ):
            return
        if self.state is not None and self.state.epoch != state.epoch:
            self.suspend(now=now)
        self.tick(now=now)
        self.state = state
        if self.resync_epoch is not None:
            if state.epoch <= self.resync_epoch or not state.available:
                return
            values = tuple(state.value(control) for control in self._latest)
            previous = self._settling
            if previous is None or previous[0] != values or previous[3] != state.epoch:
                self._settling = (values, state.observed_at, state.sequence, state.epoch)
                return
            if (
                state.observed_at - previous[1] < self.resync_settle
                or state.sequence <= previous[2]
            ):
                return
            self.resync_epoch = None
            self._settling = None
        pending = self._inflight
        if (
            pending is not None
            and state.available
            and state.epoch == pending.action.epoch
            and state.sequence > pending.action.sequence
            and state.observed_at - pending.sent_at >= self.confirmation_guard
            and (
                pending.action.intent.control != Control.FILTERS
                or state.filters_at is not None
                and state.filters_at > pending.sent_at
            )
            # Automatic filtration can skip an expected intermediate OFF. A
            # fresh final desired value is equally sufficient; never toggle it
            # away merely to force the hypothetical intermediate transition.
            and (
                self._reminder_acknowledged(pending.action.intent, state)
                if pending.action.intent.control == Control.ACK_REMINDER
                else state.value(pending.action.intent.control)
                in (pending.action.expected, pending.action.intent.desired)
            )
        ):
            self._history[-1] = replace(
                pending,
                result=Stage.VERIFIED,
                resulting_value=state.value(pending.action.intent.control),
                completed_at=now,
            )
            self._inflight = None
            if pending.action.intent.control == Control.ACK_REMINDER:
                current = self.intent(pending.action.intent.id)
                if current and current.stage not in (Stage.CANCELLED, Stage.SUPERSEDED):
                    self._update(current.id, Stage.VERIFIED)
        for control, identifier in self._latest.items():
            item = self.intent(identifier)
            if (
                item
                and item.stage not in (Stage.FAILED, Stage.CANCELLED)
                and state.safe_for(control)
                and state.value(control) == item.desired
                and self._inflight is None
            ):
                self._update(identifier, Stage.VERIFIED)

    @staticmethod
    def _reminder_acknowledged(intent: Intent, state: SpaState) -> bool:
        # A panel acknowledges the displayed reminder, not every queued one.
        # Fault/unsupported transitions are not positive acknowledgement evidence.
        # The explicit ignored-reminder policy exposes only a non-blocking none.
        return state.controls_safe and (
            state.status.reminder == "none"
            or state.status.routine_reminder
            and state.status.reminder_code != intent.reminder_code
        )

    def next_action(self, *, now: float) -> Action | None:
        self.tick(now=now)
        if (
            self.resync_epoch is not None
            or self._inflight is not None
            or self.state is None
            or not self.state.available
            or not 0 <= now - self.state.observed_at < self.state_max_age
        ):
            return None
        for control, identifier in self._latest.items():
            item = self.intent(identifier)
            if item is None or item.stage in (
                Stage.VERIFIED,
                Stage.FAILED,
                Stage.CANCELLED,
                Stage.SUPERSEDED,
            ):
                continue
            if (
                control == Control.ACK_REMINDER
                and self.state.status.reminder_code != item.reminder_code
            ):
                self._update(
                    identifier, Stage.CANCELLED, "Displayed reminder changed before transmission"
                )
                continue
            if not self.state.safe_for(control):
                continue
            value = self.state.value(control)
            if value == item.desired:
                self._update(identifier, Stage.VERIFIED)
                continue
            if self._actions[control] >= self.max_actions:
                self._update(identifier, Stage.FAILED, "Physical action budget exhausted")
                continue
            try:
                frame, expected = plan(self.state, control, item.desired)
            except ValueError as error:
                self._update(identifier, Stage.FAILED, str(error))
                continue
            assert value is not None
            self._update(identifier, Stage.WAITING_FOR_BUS)
            return Action(item, self.state.epoch, self.state.sequence, value, expected, frame, now)
        return None

    def sent(self, action: Action, *, at: float, cts_at: float | None) -> None:
        if self._inflight is not None:
            raise RuntimeError("A physical transaction is already in flight")
        current = self.intent(action.intent.id)
        if (
            self.state is None
            or not self.state.safe_for(action.intent.control)
            or (action.epoch, action.sequence) != (self.state.epoch, self.state.sequence)
            or self._latest.get(action.intent.control) != action.intent.id
            or current is None
            or current.stage != Stage.WAITING_FOR_BUS
            or at < action.prepared_at
            or cts_at is not None
            and cts_at > at
        ):
            raise ValueError("Stale physical action or invalid transmission receipt")
        self._inflight = Transaction(action, cts_at, at)
        self._actions[action.intent.control] += 1
        self._history.append(self._inflight)
        self._update(action.intent.id, Stage.WAITING_FOR_STATE)

    def tick(self, *, now: float) -> None:
        pending = self._inflight
        if pending is None:
            return
        timeout = (
            self.filter_confirmation_timeout
            if pending.action.intent.control == Control.FILTERS
            else self.confirmation_timeout
        )
        if now - pending.sent_at >= timeout:
            self._history[-1] = replace(
                pending,
                result=Stage.FAILED,
                completed_at=now,
                reason="Confirmation timeout; physical outcome ambiguous",
            )
            self._inflight = None
            self.resync_epoch = pending.action.epoch
            self._settling = None
            current = self.intent(pending.action.intent.id)
            if current is not None and current.stage not in (Stage.SUPERSEDED, Stage.CANCELLED):
                self._update(
                    pending.action.intent.id,
                    Stage.FAILED if current.control == Control.ACK_REMINDER else Stage.QUEUED,
                    "Reminder acknowledgement outcome ambiguous; not retried"
                    if current.control == Control.ACK_REMINDER
                    else "Waiting for resynchronization",
                )
