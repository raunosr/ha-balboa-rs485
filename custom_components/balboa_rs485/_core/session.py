"""Immutable heating-session intent; no clocks, storage, or transport ownership."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum

from .protocol.messages import TemperatureUnit
from .state.model import Control, SpaState


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Session values must be finite numbers")
    return float(value)


class SessionPhase(StrEnum):
    PREHEATING = "preheating"
    TARGET_REACHED = "target_reached"
    HOLDING = "holding"
    RESTORING = "restoring"


@dataclass(frozen=True, slots=True)
class Session:
    start_time: float
    end_time: float
    target: float
    maintenance: float
    unit: TemperatureUnit
    phase: SessionPhase = SessionPhase.PREHEATING

    def __post_init__(self) -> None:
        start, end = _number(self.start_time), _number(self.end_time)
        if not 0 <= start <= end <= 253402300799:
            raise ValueError("Invalid session time range")
        if not isinstance(self.unit, TemperatureUnit) or not isinstance(self.phase, SessionPhase):
            raise ValueError("Unknown session unit or phase")
        for value in (self.target, self.maintenance):
            number = _number(value)
            low, high, scale = (10, 40, 2) if self.unit == TemperatureUnit.CELSIUS else (50, 104, 1)
            if not low <= number <= high or not (number * scale).is_integer():
                raise ValueError("Unrepresentable session temperature")

    @classmethod
    def start(
        cls,
        *,
        now: float,
        end: float,
        target: float,
        maintenance: float,
        unit: TemperatureUnit,
        state: SpaState | None,
    ) -> Session:
        if _number(end) <= _number(now):
            raise ValueError("Session end must be in the future")
        if state is None or state.status.unit != unit:
            raise ValueError("Session requires an observed spa with matching temperature units")
        state.validate(Control.TARGET, target)
        state.validate(Control.TARGET, maintenance)
        return cls(now, end, target, maintenance, unit)

    def cancel(self) -> Session:
        return replace(self, phase=SessionPhase.RESTORING)

    def adjust(self, *, now: float, seconds: float) -> Session:
        if self.phase == SessionPhase.RESTORING or _number(now) >= self.end_time:
            raise ValueError("An ended session cannot be adjusted")
        end = max(self.start_time, self.end_time + _number(seconds))
        _number(end)
        return replace(
            self, end_time=end, phase=SessionPhase.RESTORING if end <= now else self.phase
        )

    def goal(self, state: SpaState | None) -> tuple[Control, float]:
        if state is None or state.status.unit != self.unit:
            raise ValueError("Session requires an observed spa with matching temperature units")
        target = self.maintenance if self.phase == SessionPhase.RESTORING else self.target
        state.validate(Control.TARGET, target)
        return Control.TARGET, target

    def desired(self, state: SpaState | None) -> float | None:
        _, target = self.goal(state)
        assert state is not None
        return target if state.target_temperature != target else None

    def reconcile(self, *, now: float, state: SpaState | None) -> Session | None:
        current = self.cancel() if _number(now) >= self.end_time else self
        try:
            desired = current.desired(state)
        except ValueError:
            return current
        if current.phase == SessionPhase.RESTORING and desired is None:
            return None
        if (
            current.phase in (SessionPhase.PREHEATING, SessionPhase.TARGET_REACHED)
            and desired is None
            and state is not None
            and state.current_temperature is not None
            and state.current_temperature >= self.target
        ):
            return replace(
                current,
                phase=SessionPhase.TARGET_REACHED
                if current.phase == SessionPhase.PREHEATING
                else SessionPhase.HOLDING,
            )
        return current

    def to_record(self) -> dict[str, object]:
        return {
            "version": 1,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "target": self.target,
            "maintenance": self.maintenance,
            "unit": self.unit.value,
            "phase": self.phase.value,
        }

    @classmethod
    def from_record(cls, record: object) -> Session:
        fields = {"version", "start_time", "end_time", "target", "maintenance", "unit", "phase"}
        if (
            not isinstance(record, dict)
            or set(record) != fields
            or type(record["version"]) is not int
            or record["version"] != 1
        ):
            raise ValueError("Invalid or unsupported session storage")
        return cls(
            _number(record["start_time"]),
            _number(record["end_time"]),
            _number(record["target"]),
            _number(record["maintenance"]),
            TemperatureUnit(record["unit"]),
            SessionPhase(record["phase"]),
        )
