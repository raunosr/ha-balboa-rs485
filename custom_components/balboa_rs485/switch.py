"""Capability-discovered auxiliary outputs, verified against observed state."""

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._core.state.model import Control
from .coordinator import BalboaConfigEntry, SpaCoordinator
from .entity import BalboaControlEntity, BalboaEntity, BalboaFilterEntity, add_control_entities

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BalboaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    add_control_entities(
        entry, async_add_entities, (Control.AUX1, Control.AUX2, Control.MISTER), SpaSwitch
    )
    async_add_entities(
        [
            FilterEnabledSwitch(entry.runtime_data),
            ClockFormatSwitch(entry.runtime_data),
            HoldSwitch(entry.runtime_data),
        ]
    )


class HoldSwitch(BalboaEntity, SwitchEntity):
    _attr_translation_key = "hold"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:pause-circle"

    def __init__(self, coordinator: SpaCoordinator) -> None:
        super().__init__(coordinator, "hold")

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.data.observed_status
        return status.hold if status else None

    async def _set(self, desired: bool) -> None:
        try:
            await self.coordinator.sessions.async_manual_setting(Control.HOLD, desired)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)


class ClockFormatSwitch(BalboaEntity, SwitchEntity):
    _attr_translation_key = "clock_24h"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator: SpaCoordinator) -> None:
        super().__init__(coordinator, "clock_24h")

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.data.observed_status
        return status.clock_24h if status else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(Control.CLOCK_FORMAT, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(Control.CLOCK_FORMAT, False)


class FilterEnabledSwitch(BalboaFilterEntity, SwitchEntity):
    _attr_translation_key = "filter_cycle_2_enabled"
    _attr_icon = "mdi:filter-outline"

    def __init__(self, coordinator: SpaCoordinator) -> None:
        super().__init__(coordinator, "filter_cycle_2_enabled")

    @property
    def is_on(self) -> bool | None:
        return self.schedule.cycles[1].enabled if self.schedule else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_filter_change(2, enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_filter_change(2, enabled=False)


class SpaSwitch(BalboaControlEntity, SwitchEntity):
    def __init__(self, coordinator: SpaCoordinator, control: Control) -> None:
        super().__init__(coordinator, control)
        self._attr_translation_key = "mister" if control is Control.MISTER else "aux"
        self._attr_translation_placeholders = {"index": control.value[-1]}

    @property
    def is_on(self) -> bool | None:
        value = self.observed_value
        return value if type(value) is bool else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(self.control, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(self.control, False)
