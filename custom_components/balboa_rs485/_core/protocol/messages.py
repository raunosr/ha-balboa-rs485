"""Minimal immutable interpretations; header facts never imply permission to write."""

from dataclasses import dataclass
from enum import IntEnum, StrEnum

from .frames import Frame


class MessageDecodeError(ValueError):
    """A known message has an unsupported payload shape."""


class TemperatureUnit(StrEnum):
    CELSIUS = "C"
    FAHRENHEIT = "F"


class HeatMode(IntEnum):
    UNKNOWN = -1
    READY = 0
    REST = 1
    READY_IN_REST = 2


class HeatState(IntEnum):
    UNKNOWN = -1
    OFF = 0
    HEATING = 1
    WAITING = 2


FAULT_NAMES = {
    15: "sensor_out_of_sync",
    16: "low_flow",
    17: "flow_failed",
    18: "settings_reset",
    19: "priming_mode",
    20: "clock_failed",
    21: "settings_reset",
    22: "memory_failure",
    26: "service_sensor_sync",
    27: "heater_dry",
    28: "heater_may_be_dry",
    29: "water_too_hot",
    30: "heater_too_hot",
    31: "sensor_a_fault",
    32: "sensor_b_fault",
    34: "pump_stuck",
    35: "hot_fault",
    36: "gfci_test_failed",
    37: "standby_mode",
}

# Standard maintenance reminders, not active fault codes. Code 3 is "Change the
# filter" in Balboa's TP700/BP user guide; 4/9/10 also have wire-source agreement.
REMINDER_NAMES = {3: "change_filter", 4: "clean_filter", 9: "check_sanitizer", 10: "check_ph"}


@dataclass(frozen=True, slots=True)
class ReadyMessage:
    """Observed classic CTS signature; not a runtime availability state."""

    frame: Frame


@dataclass(frozen=True, slots=True)
class UnknownMessage:
    """Preserve unrecognized frames without interpreting their payload."""

    frame: Frame


@dataclass(frozen=True, slots=True)
class StatusMessage:
    """Observation only. Raw pump/light slots do not establish capabilities."""

    frame: Frame
    current_temperature: float | None
    target_temperature: float | None
    unit: TemperatureUnit
    heat_mode: HeatMode
    heat_state: HeatState
    high_range: bool
    pumps_raw: tuple[int, ...]
    lights_raw: tuple[int, ...]
    circulation_pump: bool
    hour: int
    minute: int

    @property
    def hold(self) -> bool:
        return self.frame.payload[0] == 5

    @property
    def priming(self) -> bool:
        return self.frame.payload[1] == 1

    @property
    def clock_24h(self) -> bool:
        return bool(self.frame.payload[9] & 2)

    @property
    def clock(self) -> str | None:
        if self.hour > 23 or self.minute > 59:
            return None
        return f"{self.hour:02d}:{self.minute:02d}"

    @property
    def filter_running_consensus(self) -> tuple[bool | None, bool | None]:
        """Only claim a result when the two documented bit layouts agree."""
        flags = self.frame.payload[9]
        one = bool(flags & 4) if bool(flags & 4) == bool(flags & 8) else None
        two = bool(flags & 8) if bool(flags & 8) == bool(flags & 16) else None
        return one, two

    def filter_running_for_model(self, model: str | None) -> tuple[bool | None, bool | None]:
        """BP6013G2 cycle-2 boundary selects the Ruby/pybalboa layout.

        Cycle 1 is source-inferred within that layout; it is not a safety guard.
        Other models retain the conservative consensus until separately checked.
        """
        if model == "BP6013G2":
            flags = self.frame.payload[9]
            return bool(flags & 4), bool(flags & 8)
        return self.filter_running_consensus

    @property
    def panel_locked(self) -> bool:
        return bool(self.frame.payload[9] & 0x20)

    @property
    def settings_locked(self) -> bool:
        return bool(self.frame.payload[21] & 8)

    @property
    def reminder_code(self) -> int | None:
        return self.frame.payload[6] if self.frame.payload[1] == 3 else None

    @property
    def reminder(self) -> str:
        code = self.reminder_code
        if code is None or code == 0 or self.unrecognized_reminder_ignored:
            return "none"
        return REMINDER_NAMES.get(code, "unknown")

    @property
    def unrecognized_reminder_ignored(self) -> bool:
        """Compatibility policy, not a guessed description of a reminder.

        Unknown maintenance-range codes display as none and must not stop
        ordinary controls. Keep fault-code space (15+) and any fault/unknown
        notification flags conservative. The original bytes remain available.
        """
        code = self.reminder_code
        return (
            code is not None
            and 0 <= code < 15
            and code not in REMINDER_NAMES
            and self.frame.payload[18] == 1
        )

    @property
    def routine_reminder(self) -> bool:
        """Known maintenance notification, with no fault/unknown notification flags."""
        return self.reminder_code in REMINDER_NAMES and self.frame.payload[18] == 1


@dataclass(frozen=True, slots=True)
class SystemInformationMessage:
    """Common 21-byte information response; retain all hardware descriptors."""

    frame: Frame
    model: str
    software_id: tuple[int, int]
    software_version: tuple[int, int]
    setup: int
    controller_signature: bytes


@dataclass(frozen=True, slots=True)
class CapabilitiesMessage:
    """Six agreed pump descriptors, with disputed accessory bits left raw."""

    frame: Frame
    pumps_raw: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SetupMessage:
    frame: Frame
    low_range_f: tuple[int, int]
    high_range_f: tuple[int, int]


@dataclass(frozen=True, slots=True)
class FilterCycle:
    start_hour: int
    start_minute: int
    duration_minutes: int
    enabled: bool


@dataclass(frozen=True, slots=True)
class FilterCyclesMessage:
    frame: Frame
    cycles: tuple[FilterCycle, FilterCycle]


@dataclass(frozen=True, slots=True)
class FaultLogMessage:
    frame: Frame
    count: int
    entry: int
    code: int

    @property
    def name(self) -> str:
        return "none" if self.count == 0 else FAULT_NAMES.get(self.code, "unrecognized")


type Message = (
    ReadyMessage
    | StatusMessage
    | SystemInformationMessage
    | CapabilitiesMessage
    | UnknownMessage
    | SetupMessage
    | FilterCyclesMessage
    | FaultLogMessage
)


def decode_message(frame: Frame, *, response_address: int = 10, ready_address: int = 16) -> Message:
    """Recognize the exact supported signatures only."""
    if (frame.address, frame.family) == (response_address, 0xBF):
        data = frame.payload
        if frame.message_type == 0x25:
            if (
                len(data) not in (9, 10)
                or not 0 < data[2] <= data[3] < 255
                or not 0 < data[4] <= data[5] < 255
            ):
                raise MessageDecodeError("SETUP requires 9 or 10 bytes and ordered nonzero bounds")
            return SetupMessage(frame, (data[2], data[3]), (data[4], data[5]))
        if frame.message_type == 0x23:
            if (
                len(data) != 8
                or data[0] > 23
                or data[4] & 127 > 23
                or any(data[i] > 59 for i in (1, 3, 5, 7))
                or data[2] * 60 + data[3] > 1440
                or data[6] * 60 + data[7] > 1440
            ):
                raise MessageDecodeError("FILTERS requires 8 bytes with valid times/durations")
            return FilterCyclesMessage(
                frame,
                (
                    FilterCycle(data[0], data[1], data[2] * 60 + data[3], True),
                    FilterCycle(
                        data[4] & 127, data[5], data[6] * 60 + data[7], bool(data[4] & 128)
                    ),
                ),
            )
        if frame.message_type == 0x28:
            if len(data) != 10:
                raise MessageDecodeError("FAULT LOG requires 10 bytes")
            return FaultLogMessage(frame, data[0], data[1], data[2])
        if frame.message_type == 0x24:
            if len(data) != 21:
                raise MessageDecodeError("INFORMATION requires 21 payload bytes")
            return SystemInformationMessage(
                frame,
                data[4:12].decode("ascii", errors="replace").strip(" \0"),
                (data[0], data[1]),
                (data[2], data[3]),
                data[12],
                data[13:17],
            )
        if frame.message_type == 0x2E:
            if len(data) != 6:
                raise MessageDecodeError("CAPABILITIES requires 6 payload bytes")
            return CapabilitiesMessage(
                frame,
                tuple((data[0] >> (2 * i)) & 3 for i in range(4))
                + (data[1] & 3, (data[1] >> 6) & 3),
            )
    if (frame.address, frame.family, frame.message_type) == (ready_address, 0xBF, 0x06):
        if frame.payload:
            raise MessageDecodeError("READY must have an empty payload")
        return ReadyMessage(frame)
    if (frame.address, frame.family, frame.message_type) == (0xFF, 0xAF, 0x13):
        data = frame.payload
        if not 23 <= len(data) <= 32:
            raise MessageDecodeError("STATUS requires 23..32 payload bytes")
        unit = TemperatureUnit.CELSIUS if data[9] & 1 else TemperatureUnit.FAHRENHEIT
        divisor = 2 if unit is TemperatureUnit.CELSIUS else 1
        mode, heat = data[5] & 3, (data[10] >> 4) & 3
        return StatusMessage(
            frame=frame,
            current_temperature=None if data[2] == 0xFF else data[2] / divisor,
            target_temperature=None if data[20] == 0xFF else data[20] / divisor,
            unit=unit,
            heat_mode=HeatMode(mode) if mode < 3 else HeatMode.UNKNOWN,
            heat_state=HeatState(heat) if heat < 3 else HeatState.UNKNOWN,
            high_range=bool(data[10] & 4),
            pumps_raw=tuple((data[11 + i // 4] >> (2 * (i % 4))) & 3 for i in range(6)),
            lights_raw=(data[14] & 3, (data[14] >> 2) & 3),
            circulation_pump=bool(data[13] & 2),
            hour=data[3],
            minute=data[4],
        )
    return UnknownMessage(frame)
