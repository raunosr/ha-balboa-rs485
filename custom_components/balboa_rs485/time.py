"""Spa-local filter times, with whole-record reads/confirmation behind each edit."""

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._core.state.model import Control
from .coordinator import BalboaConfigEntry, SpaCoordinator
from .entity import BalboaEntity, BalboaFilterEntity

PARALLEL_UPDATES = 0


def minute_of_day(value: time) -> int:
    if value.second or value.microsecond or value.tzinfo is not None:
        raise ServiceValidationError("Use the spa's local HH:MM, without seconds or time zone")
    return value.hour * 60 + value.minute


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BalboaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        FilterTime(entry.runtime_data, cycle, field)
        for cycle in (1, 2)
        for field in ("start", "end")
    )
    async_add_entities([SpaClock(entry.runtime_data)])


class SpaClock(BalboaEntity, TimeEntity):
    _attr_translation_key = "clock"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SpaCoordinator) -> None:
        super().__init__(coordinator, "clock")

    @property
    def native_value(self) -> time | None:
        status = self.coordinator.data.observed_status
        return time(status.hour, status.minute) if status and status.clock is not None else None

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_command(Control.CLOCK_TIME, minute_of_day(value))


class FilterTime(BalboaFilterEntity, TimeEntity):
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator: SpaCoordinator, cycle: int, field: str) -> None:
        super().__init__(coordinator, f"filter_cycle_{cycle}_{field}")
        self.cycle, self.field = cycle, field
        self._attr_translation_key = f"filter_cycle_{field}"
        self._attr_translation_placeholders = {"index": str(cycle)}

    @property
    def native_value(self) -> time | None:
        if (schedule := self.schedule) is None:
            return None
        cycle = schedule.cycles[self.cycle - 1]
        if self.field == "start":
            return time(cycle.start_hour, cycle.start_minute)
        return time(*divmod(schedule.end(self.cycle), 60))

    async def async_set_value(self, value: time) -> None:
        minute = minute_of_day(value)
        await self.coordinator.async_filter_change(
            self.cycle,
            start=minute if self.field == "start" else None,
            end=minute if self.field == "end" else None,
        )
