"""On/off lights with observed state and no invented brightness support."""

from typing import Any

from homeassistant.components.light import LightEntity
from homeassistant.components.light.const import ColorMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._core.state.model import Control
from .coordinator import BalboaConfigEntry, SpaCoordinator
from .entity import BalboaControlEntity, add_control_entities

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BalboaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    add_control_entities(entry, async_add_entities, (Control.LIGHT1, Control.LIGHT2), SpaLight)


class SpaLight(BalboaControlEntity, LightEntity):
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_translation_key = "light"

    def __init__(self, coordinator: SpaCoordinator, control: Control) -> None:
        super().__init__(coordinator, control)
        self._attr_translation_placeholders = {"index": control.value[-1]}

    @property
    def is_on(self) -> bool | None:
        value = self.observed_value
        return value if type(value) is bool else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(self.control, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(self.control, False)
