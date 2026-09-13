"""Passive nameplate-power estimate; missing observations are never zero consumption."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from .protocol.messages import HeatState
from .state.model import Control, PumpState, SpaState

DEFAULT_POWERS: dict[str, float] = {
    "heater_w": 3000,
    "electronics_w": 20,
    "circulation_w": 250,
    "light_w": 10,
    **{
        f"pump{i}_{speed}_w": watts
        for i in range(1, 7)
        for speed, watts in (("low", 350), ("high", 1300))
    },
    "blower_w": 0,
    "mister_w": 0,
    "aux1_w": 0,
    "aux2_w": 0,
}


def powers(values: Mapping[str, object]) -> dict[str, float]:
    """Zero accessory rating means unconfigured, not a free active load."""
    result = DEFAULT_POWERS.copy()
    for key, value in values.items():
        if key not in result or isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Invalid power profile")
        if not math.isfinite(value) or not 0 <= value <= 25000:
            raise ValueError("Power must be finite and between 0 and 25000 W")
        result[key] = float(value)
    return result


def estimate(state: SpaState, profile: Mapping[str, float]) -> float | None:
    """Use normalized observed actuator states, never control intent or water temperature."""
    if state.status.heat_state == HeatState.UNKNOWN:
        return None
    loads = ["electronics_w"]
    if state.status.heat_state == HeatState.HEATING:
        loads.append("heater_w")
    for i, count in enumerate(state.configuration.capabilities.pumps_raw, 1):
        if count == 0:
            continue
        value = state.value(Control(f"pump{i}"))
        if value is None:
            return None
        if value != PumpState.OFF:
            speed = "low" if value == PumpState.LOW else "high"
            loads.append(f"pump{i}_{speed}_w")
    circ = state.configuration.capabilities.frame.payload[3] >> 6
    if circ not in (0, 2):
        return None
    if circ == 2 and state.status.circulation_pump:
        loads.append("circulation_w")
    for control in (
        Control.LIGHT1,
        Control.LIGHT2,
        Control.BLOWER,
        Control.MISTER,
        Control.AUX1,
        Control.AUX2,
    ):
        if not state.options(control):
            # An active but unmapped light must not silently disappear from watts.
            if (
                control in (Control.LIGHT1, Control.LIGHT2)
                and state.status.lights_raw[0 if control == Control.LIGHT1 else 1]
            ):
                return None
            continue
        value = state.value(control)
        if value is None:
            return None
        if value:
            loads.append(
                "light_w" if control in (Control.LIGHT1, Control.LIGHT2) else f"{control.value}_w"
            )
    if any(profile[key] == 0 for key in loads if key != "electronics_w"):
        return None
    return sum(profile[key] for key in loads)


@dataclass
class EnergyCounter:
    """Left-rectangle integration only between consecutive fresh same-epoch samples.

    Long intervals are excluded in full. Restoring totals does not restore a live
    sample: an offline period cannot turn into invented energy after startup.
    """

    kwh: float = 0
    known_seconds: float = 0
    unknown_seconds: float = 0
    _previous: tuple[float, float | None, int] | None = None

    def sample(self, now: float, watts: float | None, epoch: int) -> None:
        if not math.isfinite(now) or (
            watts is not None and (not math.isfinite(watts) or watts < 0)
        ):
            raise ValueError("Invalid energy observation")
        previous = self._previous
        if previous is not None:
            at, power, previous_epoch = previous
            seconds = now - at
            if seconds <= 0:
                return
            if seconds <= 8 and power is not None and watts is not None and epoch == previous_epoch:
                self.kwh += power * seconds / 3_600_000
                self.known_seconds += seconds
            else:
                self.unknown_seconds += seconds
        self._previous = (now, watts, epoch)

    def break_interval(self) -> None:
        """Changing a profile cannot price the previous interval at a new rating."""
        self._previous = None

    def record(self) -> dict[str, float]:
        return {
            "kwh": self.kwh,
            "known_seconds": self.known_seconds,
            "unknown_seconds": self.unknown_seconds,
        }

    @classmethod
    def restore(cls, record: object) -> Self:
        if not isinstance(record, dict) or set(record) != {
            "kwh",
            "known_seconds",
            "unknown_seconds",
        }:
            raise ValueError("Invalid energy record")
        if any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
            for v in record.values()
        ):
            raise ValueError("Invalid energy totals")
        return cls(**record)
