"""Named native choices using the same capability-checked command engine."""

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._core.protocol.messages import HeatMode, TemperatureUnit
from ._core.state.model import Control, PumpState
from .coordinator import BalboaConfigEntry, SpaCoordinator
from .entity import BalboaEntity, add_control_entities

_SPEEDS = {
    "off": PumpState.OFF,
    "circulation": PumpState.LOW,
    "jets": PumpState.HIGH,
    "on": PumpState.ON,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BalboaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    add_control_entities(entry, async_add_entities, (Control.PUMP1,), PumpModeSelect)
    async_add_entities(
        [HeatingPolicySelect(entry.runtime_data), TemperatureUnitSelect(entry.runtime_data)]
    )


class TemperatureUnitSelect(BalboaEntity, SelectEntity):
    _attr_translation_key = "temperature_unit"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = ["celsius", "fahrenheit"]
    _attr_icon = "mdi:temperature-celsius"

    def __init__(self, coordinator: SpaCoordinator) -> None:
        super().__init__(coordinator, "temperature_unit")

    @property
    def current_option(self) -> str | None:
        status = self.coordinator.data.observed_status
        return status.unit.name.lower() if status else None

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            raise HomeAssistantError("Unsupported temperature unit")
        try:
            await self.coordinator.sessions.async_manual_setting(
                Control.TEMPERATURE_UNIT, TemperatureUnit[option.upper()]
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err


class HeatingPolicySelect(BalboaEntity, SelectEntity):
    """Ready-in-Rest is an observation, never a directly selectable policy."""

    _attr_translation_key = "heating_policy"
    _attr_options = ["ready", "rest"]
    _attr_icon = "mdi:radiator"

    def __init__(self, coordinator: SpaCoordinator) -> None:
        super().__init__(coordinator, "heating_policy")

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.controls_enabled

    @property
    def current_option(self) -> str | None:
        status = self.coordinator.data.observed_status
        if status is None or status.heat_mode == HeatMode.UNKNOWN:
            return None
        if status.heat_mode == HeatMode.READY_IN_REST:
            return "rest"  # Temporary Jets-triggered heating does not change the REST policy.
        return status.heat_mode.name.lower()

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            raise HomeAssistantError("Unsupported heating policy")
        try:
            await self.coordinator.sessions.async_manual_setting(
                Control.HEAT_MODE, HeatMode.READY if option == "ready" else HeatMode.REST
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err


class PumpModeSelect(BalboaEntity, SelectEntity):
    """Hidden compatibility alias of the Pump 1 slider; stable service target."""

    _attr_translation_key = "pump_mode"
    _attr_icon = "mdi:pump"
    _attr_entity_registry_visible_default = False
    _pump_slider_alias = True

    def __init__(self, coordinator: SpaCoordinator, control: Control) -> None:
        super().__init__(coordinator, f"{control.value}_mode")
        self.control = control
        self._attr_translation_placeholders = {"index": control.value[-1]}

    @property
    def options(self) -> list[str]:
        state = self.coordinator.runtime.state
        supported = state.options(self.control) if state else ()
        return [label for label, value in _SPEEDS.items() if value in supported]

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.controls_enabled and bool(self.options)

    @property
    def current_option(self) -> str | None:
        state = self.coordinator.runtime.state
        observed = state.value(self.control) if state else None
        return next((label for label in self.options if _SPEEDS[label] == observed), None)

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise HomeAssistantError("Unsupported pump speed")
        await self.coordinator.async_command(self.control, _SPEEDS[option])
