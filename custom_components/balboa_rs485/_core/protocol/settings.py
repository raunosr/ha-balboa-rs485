"""Known whole-record filter settings. Pure transformations, never transmission."""

from dataclasses import dataclass, replace
from typing import Self

from .frames import Frame
from .messages import FilterCycle


def _minute(value: int) -> int:
    if type(value) is not int or not 0 <= value < 1440:
        raise ValueError("Time must be whole minutes from midnight, 0..1439")
    return value


@dataclass(frozen=True, slots=True)
class FilterSchedule:
    cycles: tuple[FilterCycle, FilterCycle]

    def __post_init__(self) -> None:
        if not isinstance(self.cycles, tuple) or len(self.cycles) != 2:
            raise ValueError("Both filter cycles are required")
        for cycle in self.cycles:
            if (
                not isinstance(cycle, FilterCycle)
                or type(cycle.start_hour) is not int
                or not 0 <= cycle.start_hour <= 23
                or type(cycle.start_minute) is not int
                or not 0 <= cycle.start_minute <= 59
                or type(cycle.duration_minutes) is not int
                or not 0 <= cycle.duration_minutes <= 1440
                or type(cycle.enabled) is not bool
            ):
                raise ValueError("Invalid filter record")
        if not self.cycles[0].enabled:
            raise ValueError("Cycle 1 has no independent enable flag")

    def _cycle(self, index: int) -> FilterCycle:
        if type(index) is not int or index not in (1, 2):
            raise ValueError("Cycle index must be 1 or 2")
        return self.cycles[index - 1]

    def end(self, index: int) -> int:
        cycle = self._cycle(index)
        return (cycle.start_hour * 60 + cycle.start_minute + cycle.duration_minutes) % 1440

    def update(
        self,
        index: int,
        *,
        start: int | None = None,
        end: int | None = None,
        enabled: bool | None = None,
    ) -> Self:
        cycle = self._cycle(index)
        if start is not None:
            hour, minute = divmod(_minute(start), 60)
            cycle = replace(cycle, start_hour=hour, start_minute=minute)
        if end is not None:
            duration = (_minute(end) - cycle.start_hour * 60 - cycle.start_minute) % 1440
            if duration == 0:
                raise ValueError("Equal start/end is ambiguous; 0/24-hour writes are not supported")
            cycle = replace(cycle, duration_minutes=duration)
        if enabled is not None:
            if type(enabled) is not bool or index == 1:
                raise ValueError("Only Cycle 2 has an enable flag")
            cycle = replace(cycle, enabled=enabled)
        if cycle.duration_minutes in (0, 1440) and cycle != self._cycle(index):
            raise ValueError(
                "Keep observed 0/24-hour cycles read-only until an explicit end is set"
            )
        first, second = self.cycles
        return type(self)((cycle, second) if index == 1 else (first, cycle))

    def frame(self) -> Frame:
        first, second = self.cycles
        return Frame(
            10,
            0xBF,
            0x23,
            bytes(
                (
                    first.start_hour,
                    first.start_minute,
                    *divmod(first.duration_minutes, 60),
                    second.start_hour | (0x80 if second.enabled else 0),
                    second.start_minute,
                    *divmod(second.duration_minutes, 60),
                )
            ),
        )
