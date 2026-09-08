"""Native percentage control mapped to the observed discrete pump capability."""

import math
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._core.state.model import Control
from .coordinator import BalboaConfigEntry, SpaCoordinator
from .entity import BalboaControlEntity, add_control_entities

PARALLEL_UPDATES = 0  # The independent desired-state engine arbitrates all physical commands.


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BalboaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    pumps = tuple(Control(f"pump{index}") for index in range(1, 7))
    add_control_entities(entry, async_add_entities, (*pumps, Control.BLOWER), SpaFan)


class SpaFan(BalboaControlEntity, FanEntity):
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
    )
    _attr_translation_key = "pump"

    def __init__(self, coordinator: SpaCoordinator, control: Control) -> None:
        super().__init__(coordinator, control)
        if control is Control.BLOWER:
            self._attr_translation_key = "blower"
        else:
            self._attr_translation_placeholders = {"index": control.value[-1]}

    @property
    def speed_count(self) -> int:
        return max(1, len(self.options) - 1)

    @property
    def percentage(self) -> int | None:
        value, options = self.observed_value, self.options
        if value is None or value not in options:
            return None
        return round(100 * options.index(value) / self.speed_count)

    @property
    def is_on(self) -> bool | None:
        percentage = self.percentage
        return percentage > 0 if percentage is not None else None

    async def async_set_percentage(self, percentage: int) -> None:
        options = self.options
        if not options or not 0 <= percentage <= 100:
            raise HomeAssistantError("Pump capability is unavailable or percentage is invalid")
        index = math.ceil(percentage * (len(options) - 1) / 100)
        await self.coordinator.async_command(self.control, options[index])

    async def async_turn_on(
        self, percentage: int | None = None, preset_mode: str | None = None, **kwargs: Any
    ) -> None:
        await self.async_set_percentage(100 if percentage is None else percentage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_set_percentage(0)
