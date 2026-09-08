"""Durable staged bathing intent; every next goal uses a fresh observation."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import StrEnum
from uuid import UUID, uuid4

from .protocol.messages import HeatMode, TemperatureUnit
from .session import Session, SessionPhase, _number
from .state.model import Control, SpaState, Value


class RangeStep(StrEnum):
    ACTIVATE_HIGH = "activate_high"
    SET_TARGET = "set_high_target"
    SET_MODE = "set_ready"
    ACTIVE = "active"
    RESTORE_HIGH = "restore_high_target"
    RESTORE_RANGE = "restore_range"
    RESTORE_MODE = "restore_mode"


class SessionConflict(ValueError):
    """An observed external change must not be overwritten by saved ownership."""


@dataclass(frozen=True, slots=True)
class RangeSession:
    start_time: float
    end_time: float
    minimum: float
    maintenance: float
    unit: TemperatureUnit
    original_range: bool
    original_mode: HeatMode
    original_high: float | None = None
    step: RangeStep = RangeStep.ACTIVATE_HIGH
    phase: SessionPhase = SessionPhase.PREHEATING
    target_owned: bool = False
    mode_owned: bool = False
    operation_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        Session(
            self.start_time, self.end_time, self.minimum, self.maintenance, self.unit, self.phase
        )
        if self.original_high is not None:
            Session(self.start_time, self.end_time, self.original_high, self.maintenance, self.unit)
        if (
            type(self.original_range) is not bool
            or type(self.target_owned) is not bool
            or type(self.mode_owned) is not bool
            or not isinstance(self.original_mode, HeatMode)
            or self.original_mode not in (HeatMode.READY, HeatMode.REST)
            or not isinstance(self.step, RangeStep)
            or not isinstance(self.operation_id, str)
            or UUID(hex=self.operation_id).hex != self.operation_id
        ):
            raise ValueError("Invalid bathing-session identity, ownership or mode")
        restoring = self.step in (
            RangeStep.RESTORE_HIGH,
            RangeStep.RESTORE_RANGE,
            RangeStep.RESTORE_MODE,
        )
        requires_high = self.step in (
            RangeStep.SET_TARGET,
            RangeStep.SET_MODE,
            RangeStep.ACTIVE,
            RangeStep.RESTORE_HIGH,
        )
        if (
            restoring != (self.phase == SessionPhase.RESTORING)
            or (requires_high or self.original_range)
            and self.original_high is None
            or self.target_owned
            and (self.original_high is None or self.original_high >= self.minimum)
            or self.mode_owned
            and self.original_mode != HeatMode.REST
            or self.step == RangeStep.RESTORE_MODE
            and not self.mode_owned
            or not restoring
            and self.step != RangeStep.ACTIVE
            and self.phase != SessionPhase.PREHEATING
            or self.step in (RangeStep.SET_TARGET, RangeStep.SET_MODE, RangeStep.ACTIVE)
            and self.target_owned
            != (self.original_high is not None and self.original_high < self.minimum)
            or self.step in (RangeStep.ACTIVATE_HIGH, RangeStep.SET_TARGET)
            and self.mode_owned
            or self.step in (RangeStep.SET_MODE, RangeStep.ACTIVE)
            and self.mode_owned != (self.original_mode == HeatMode.REST)
        ):
            raise ValueError("Inconsistent bathing-session checkpoint")

    @property
    def target(self) -> float:
        return (
            max(self.minimum, self.original_high)
            if self.original_high is not None
            else self.minimum
        )

    @classmethod
    def start(
        cls, *, now: float, end: float, minimum_c: float, state: SpaState | None
    ) -> RangeSession:
        if state is None or state.target_temperature is None:
            raise ValueError("A fresh observed target is required")
        unit = state.status.unit
        minimum = _number(minimum_c)
        if not 10 <= minimum <= 40 or not (minimum * 2).is_integer():
            raise ValueError("Minimum bathing temperature must be 10..40 C in half-degree steps")
        if unit == TemperatureUnit.FAHRENHEIT:
            minimum = float(math.ceil(minimum * 1.8 + 32))
        Session.start(
            now=now,
            end=end,
            target=state.target_temperature,
            maintenance=state.target_temperature,
            unit=unit,
            state=state,
        )
        state.validate(Control.HIGH_RANGE, True)
        state.validate(Control.HEAT_MODE, HeatMode.READY)
        replace(state, status=replace(state.status, high_range=True)).validate(
            Control.TARGET, minimum
        )
        high = state.target_temperature if state.status.high_range else None
        return cls(
            now,
            end,
            minimum,
            state.target_temperature,
            unit,
            state.status.high_range,
            HeatMode.READY if state.status.heat_mode == HeatMode.READY else HeatMode.REST,
            high,
            RangeStep.SET_TARGET if high is not None else RangeStep.ACTIVATE_HIGH,
            target_owned=high is not None and high < minimum,
        )

    def cancel(self) -> RangeSession:
        if self.phase == SessionPhase.RESTORING:
            return self
        return replace(
            self,
            phase=SessionPhase.RESTORING,
            step=RangeStep.RESTORE_HIGH if self.target_owned else RangeStep.RESTORE_RANGE,
        )

    def to_record(self) -> dict[str, object]:
        return {
            "version": 2,
            "operation_id": self.operation_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "minimum": self.minimum,
            "maintenance": self.maintenance,
            "unit": self.unit.value,
            "original_range": self.original_range,
            "original_mode": self.original_mode.name,
            "original_high": self.original_high,
            "step": self.step.value,
            "phase": self.phase.value,
            "target_owned": self.target_owned,
            "mode_owned": self.mode_owned,
        }

    def adjust(self, *, now: float, seconds: float) -> RangeSession:
        adjusted = Session(
            self.start_time, self.end_time, self.minimum, self.maintenance, self.unit, self.phase
        ).adjust(now=now, seconds=seconds)
        updated = replace(self, end_time=adjusted.end_time)
        return updated.cancel() if adjusted.phase == SessionPhase.RESTORING else updated

    def release_target(self) -> RangeSession:
        """Explicit manual High edits relinquish only target restoration ownership."""
        return replace(
            self, target_owned=False, phase=SessionPhase.RESTORING, step=RangeStep.RESTORE_RANGE
        )

    @classmethod
    def from_record(cls, record: object) -> RangeSession:
        fields = {
            "version",
            "operation_id",
            "start_time",
            "end_time",
            "minimum",
            "maintenance",
            "unit",
            "original_range",
            "original_mode",
            "original_high",
            "step",
            "phase",
            "target_owned",
            "mode_owned",
        }
        if (
            not isinstance(record, dict)
            or set(record) != fields
            or type(record["version"]) is not int
            or record["version"] != 2
        ):
            raise ValueError("Invalid or unsupported bathing-session storage")
        try:
            return cls(
                start_time=_number(record["start_time"]),
                end_time=_number(record["end_time"]),
                minimum=_number(record["minimum"]),
                maintenance=_number(record["maintenance"]),
                unit=TemperatureUnit(record["unit"]),
                original_range=record["original_range"],
                original_mode=HeatMode[record["original_mode"]],
                original_high=None
                if record["original_high"] is None
                else _number(record["original_high"]),
                step=RangeStep(record["step"]),
                phase=SessionPhase(record["phase"]),
                target_owned=record["target_owned"],
                mode_owned=record["mode_owned"],
                operation_id=record["operation_id"],
            )
        except (KeyError, TypeError, AttributeError) as err:
            raise ValueError("Invalid bathing-session fields") from err

    def goal(self, state: SpaState | None) -> tuple[Control, Value]:
        if state is None or state.status.unit != self.unit:
            raise ValueError("Session requires fresh matching-unit observations")
        if self.step == RangeStep.ACTIVATE_HIGH:
            goal: tuple[Control, Value] = (Control.HIGH_RANGE, True)
        elif self.step in (RangeStep.SET_TARGET, RangeStep.ACTIVE, RangeStep.RESTORE_HIGH):
            if not state.status.high_range:
                raise SessionConflict("Temperature range changed outside the session")
            if self.original_high is None:
                raise ValueError("Original High target has not been captured")
            if state.target_temperature not in (self.original_high, self.target):
                raise SessionConflict("High target changed outside the session")
            if self.step == RangeStep.ACTIVE and state.status.heat_mode != HeatMode.READY:
                raise SessionConflict("Heat mode changed outside the session")
            goal = (
                Control.TARGET,
                self.original_high if self.step == RangeStep.RESTORE_HIGH else self.target,
            )
        elif self.step == RangeStep.SET_MODE:
            if not state.status.high_range or state.target_temperature != self.target:
                raise SessionConflict("Range or target changed before enabling heating")
            goal = (Control.HEAT_MODE, HeatMode.READY)
        elif self.step == RangeStep.RESTORE_RANGE:
            goal = (Control.HIGH_RANGE, self.original_range)
        else:
            if state.status.high_range != self.original_range:
                raise SessionConflict("Range changed during restoration")
            goal = (Control.HEAT_MODE, self.original_mode)
        state.validate(*goal)
        return goal

    def reconcile(self, *, now: float, state: SpaState | None) -> RangeSession | None:
        current = self.cancel() if _number(now) >= self.end_time else self
        try:
            control, desired = current.goal(state)
        except ValueError:
            return current
        assert state is not None
        if state.value(control) != desired:
            return current
        if current.step == RangeStep.ACTIVATE_HIGH:
            high = state.target_temperature
            if high is None:
                return current
            return replace(
                current,
                original_high=high,
                target_owned=high < current.minimum,
                step=RangeStep.SET_TARGET,
            )
        if current.step == RangeStep.SET_TARGET:
            return replace(
                current, mode_owned=current.original_mode != HeatMode.READY, step=RangeStep.SET_MODE
            )
        if current.step == RangeStep.SET_MODE:
            return replace(current, step=RangeStep.ACTIVE)
        if current.step == RangeStep.RESTORE_HIGH:
            return replace(current, step=RangeStep.RESTORE_RANGE)
        if current.step == RangeStep.RESTORE_RANGE:
            return replace(current, step=RangeStep.RESTORE_MODE) if current.mode_owned else None
        if current.step == RangeStep.RESTORE_MODE:
            return None
        if state.current_temperature is not None and state.current_temperature >= current.target:
            return replace(
                current,
                phase=SessionPhase.HOLDING
                if current.phase != SessionPhase.PREHEATING
                else SessionPhase.TARGET_REACHED,
            )
        return current
