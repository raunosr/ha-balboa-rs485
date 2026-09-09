"""Physical state is derived exclusively from received messages."""

import math
from dataclasses import dataclass
from enum import StrEnum

from ..protocol.configuration import Configuration
from ..protocol.messages import (
    FaultLogMessage,
    FilterCyclesMessage,
    HeatMode,
    SetupMessage,
    StatusMessage,
    TemperatureUnit,
)
from ..protocol.settings import FilterSchedule


class PumpState(StrEnum):
    OFF = "off"
    LOW = "low"
    HIGH = "high"
    ON = "on"


class Control(StrEnum):
    PUMP1 = "pump1"
    PUMP2 = "pump2"
    PUMP3 = "pump3"
    PUMP4 = "pump4"
    PUMP5 = "pump5"
    PUMP6 = "pump6"
    TARGET = "target"
    LIGHT1 = "light1"
    LIGHT2 = "light2"
    BLOWER = "blower"
    MISTER = "mister"
    AUX1 = "aux1"
    AUX2 = "aux2"
    HEAT_MODE = "heat_mode"
    HIGH_RANGE = "high_range"
    FILTERS = "filters"
    CLOCK_TIME = "clock_time"
    CLOCK_FORMAT = "clock_format"
    TEMPERATURE_UNIT = "temperature_unit"
    HOLD = "hold"
    NORMAL_OPERATION = "normal_operation"
    SOAK = "soak"
    ACK_REMINDER = "ack_reminder"


type Value = PumpState | HeatMode | bool | int | float | FilterSchedule | TemperatureUnit


@dataclass(frozen=True, slots=True)
class SpaState:
    status: StatusMessage
    configuration: Configuration
    epoch: int
    sequence: int
    observed_at: float
    available: bool
    setup: SetupMessage | None = None
    filters: FilterCyclesMessage | None = None
    fault: FaultLogMessage | None = None
    filters_at: float | None = None

    @property
    def controls_safe(self) -> bool:
        # Unknown operating modes, hold, priming and unvalidated lock bits inhibit controls.
        data = self.status.frame.payload
        # Admission never acknowledges notifications. Unknown maintenance-range
        # reminders have an explicit non-blocking compatibility policy, while
        # operating modes, fault-code space and notification flags stay guarded.
        normal_or_reminder = (
            data[1] == 0
            or self.status.routine_reminder
            or self.status.unrecognized_reminder_ignored
        )
        return (
            self.available
            and data[0] == 0
            and normal_or_reminder
            and not data[9] & 0xF0
            and not data[21] & 8
        )

    @property
    def filter_running(self) -> tuple[bool, bool]:
        return (bool(self.status.frame.payload[9] & 4), bool(self.status.frame.payload[9] & 8))

    def safe_for(self, control: Control) -> bool:
        if self.controls_safe:
            return True
        data = self.status.frame.payload
        if control == Control.ACK_REMINDER:
            return (
                self.available
                and data[0] == 0
                and self.status.routine_reminder
                and not data[9] & 0xF0
                and not data[21] & 8
            )
        return (
            control in (Control.HOLD, Control.NORMAL_OPERATION)
            and self.available
            and data[0] == 5
            and (
                data[1] == 0
                or self.status.routine_reminder
                or self.status.unrecognized_reminder_ignored
            )
            and not data[9] & 0xF0
            and not data[21] & 8
        )

    @property
    def priming(self) -> bool:
        return self.status.priming

    @property
    def controls_blocked_reason(self) -> str | None:
        """Explain general admission without labelling historical faults as active."""
        if self.controls_safe:
            return None
        data = self.status.frame.payload
        if not self.available:
            return "state_not_synchronized"
        if self.priming:
            return "priming"
        if self.hold:
            return "hold"
        if self.status.panel_locked:
            return "panel_locked"
        if self.status.settings_locked:
            return "settings_locked"
        if data[1] == 3 and not self.status.routine_reminder:
            return f"unsupported_notification_{data[6]}"
        return "unsupported_operating_state"

    @property
    def hold(self) -> bool:
        return self.status.frame.payload[0] == 5

    @property
    def model(self) -> str:
        return self.configuration.information.model

    @property
    def has_circulation_pump(self) -> bool:
        return self.configuration.capabilities.frame.payload[3] >> 6 == 2

    @property
    def voltage(self) -> int | None:
        return 240 if self.configuration.information.frame.payload[17] == 1 else None

    @property
    def heater_type(self) -> str:
        return "standard" if self.configuration.information.frame.payload[18] == 10 else "unknown"

    @property
    def dip_settings(self) -> bytes:
        return self.configuration.information.frame.payload[19:21]

    @property
    def current_temperature(self) -> float | None:
        return self.status.current_temperature

    @property
    def target_temperature(self) -> float | None:
        return self.status.target_temperature

    def options(self, control: Control) -> tuple[Value, ...]:
        caps = self.configuration.capabilities.frame.payload
        if control == Control.ACK_REMINDER:
            return (True,) if self.status.reminder != "unknown" else ()
        if control == Control.HOLD:
            return (False, True) if self.status.frame.payload[0] in (0, 5) else ()
        if control == Control.NORMAL_OPERATION:
            return (True,) if self.status.frame.payload[0] in (0, 5) else ()
        if control == Control.SOAK:
            pumps = self.configuration.capabilities.pumps_raw
            return (True,) if any(pumps) and all(p in (0, 1, 2) for p in pumps) else ()
        if control == Control.CLOCK_TIME:
            return (self.status.hour * 60 + self.status.minute,) if self.status.clock else ()
        if control == Control.CLOCK_FORMAT:
            return (False, True) if self.status.clock else ()
        if control == Control.TEMPERATURE_UNIT:
            return (TemperatureUnit.CELSIUS, TemperatureUnit.FAHRENHEIT)
        if control == Control.FILTERS:
            return (FilterSchedule(self.filters.cycles),) if self.filters is not None else ()
        if control == Control.TARGET:
            if self.setup is None:
                return ()
            low, high = (
                self.setup.high_range_f if self.status.high_range else self.setup.low_range_f
            )
            low, high = max(50, low), min(104, high)
            if self.status.unit == TemperatureUnit.CELSIUS:
                return tuple(
                    i / 2
                    for i in range(
                        math.ceil((low - 32) / 1.8 * 2), math.floor((high - 32) / 1.8 * 2) + 1
                    )
                )
            return tuple(range(low, high + 1))
        if control == Control.HEAT_MODE:
            return (HeatMode.READY, HeatMode.REST)
        if control == Control.HIGH_RANGE:
            return (False, True)
        if control in (Control.LIGHT1, Control.LIGHT2):
            pair = caps[2] & 3 if control == Control.LIGHT1 else caps[2] >> 2 & 3
            if control == Control.LIGHT2 and pair != caps[2] >> 6 & 3:
                return ()
            return (False, True) if pair == 1 else ()
        if control == Control.BLOWER:
            count = caps[3] & 3
            return tuple(range(count + 1)) if count else ()
        if control in (Control.AUX1, Control.AUX2):
            return (False, True) if caps[4] & (1 if control == Control.AUX1 else 2) else ()
        if control == Control.MISTER:
            return (False, True) if (caps[4] >> 4) & 3 == 1 else ()
        index = int(control.value[-1]) - 1
        count = self.configuration.capabilities.pumps_raw[index]
        if count == 1:
            return (PumpState.OFF, PumpState.ON)
        if count == 2:
            return (PumpState.OFF, PumpState.LOW, PumpState.HIGH)
        return ()

    def value(self, control: Control) -> Value | None:
        data = self.status.frame.payload
        if control == Control.ACK_REMINDER:
            return self.status.reminder == "none" if self.options(control) else None
        if control in (Control.HOLD, Control.NORMAL_OPERATION):
            if data[0] not in (0, 5):
                return None
            return data[0] == (5 if control == Control.HOLD else 0)
        if control == Control.SOAK:
            if not self.options(control):
                return None
            values = [
                self.value(Control(f"pump{i + 1}"))
                for i, count in enumerate(self.configuration.capabilities.pumps_raw)
                if count
            ]
            return (
                None if any(v is None for v in values) else all(v == PumpState.OFF for v in values)
            )
        if control == Control.CLOCK_TIME:
            return self.status.hour * 60 + self.status.minute if self.status.clock else None
        if control == Control.CLOCK_FORMAT:
            return self.status.clock_24h
        if control == Control.TEMPERATURE_UNIT:
            return self.status.unit
        if control == Control.FILTERS:
            return FilterSchedule(self.filters.cycles) if self.filters is not None else None
        if control == Control.TARGET:
            return self.target_temperature
        if control == Control.HEAT_MODE:
            return self.status.heat_mode if self.status.heat_mode != HeatMode.UNKNOWN else None
        if control == Control.HIGH_RANGE:
            return self.status.high_range
        options = self.options(control)
        if not options:
            return None
        if control in (Control.LIGHT1, Control.LIGHT2):
            raw = self.status.lights_raw[0 if control == Control.LIGHT1 else 1]
            return False if raw == 0 else True if raw in (2, 3) else None
        if control == Control.BLOWER:
            raw = (data[13] >> 2) & 3
            return raw if raw in options else None
        if control == Control.MISTER:
            return bool(data[15] & 1)
        if control in (Control.AUX1, Control.AUX2):
            return bool(data[15] & (8 if control == Control.AUX1 else 16))
        raw = self.status.pumps_raw[int(control.value[-1]) - 1]
        if len(options) == 2 and raw in (1, 2):
            return PumpState.ON
        return options[raw] if raw < len(options) else None

    def validate(self, control: Control, desired: Value) -> None:
        if not isinstance(control, Control) or not self.safe_for(control):
            raise ValueError(
                "Controls require a fresh synchronized normal operating state"
                f" ({self.controls_blocked_reason or 'control_not_permitted'})"
            )
        if control == Control.CLOCK_TIME:
            if type(desired) is not int or not 0 <= desired < 1440 or self.status.clock is None:
                raise ValueError("Clock must be 0..1439 minutes with known observed clock")
            return
        if control == Control.FILTERS:
            if (
                not isinstance(desired, FilterSchedule)
                or self.filters is None
                or self.filters_at is None
                or self.observed_at - self.filters_at > 3
            ):
                raise ValueError("Filter writes require a freshly queried whole record")
            return
        if control.value.startswith("pump"):
            valid_type = isinstance(desired, PumpState)
        elif control == Control.TARGET:
            valid_type = (
                isinstance(desired, (int, float))
                and type(desired) is not bool
                and math.isfinite(desired)
            )
        elif control == Control.BLOWER:
            valid_type = type(desired) is int
        elif control == Control.HEAT_MODE:
            valid_type = isinstance(desired, HeatMode)
        elif control == Control.TEMPERATURE_UNIT:
            valid_type = isinstance(desired, TemperatureUnit)
        else:
            valid_type = type(desired) is bool
        if not valid_type or desired not in self.options(control) or self.value(control) is None:
            raise ValueError("Unsupported desired value, missing setup, or unknown physical state")
