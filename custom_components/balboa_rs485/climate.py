"""Spa temperatures without pretending that REST is a physical power-off."""

from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._core.protocol.messages import HeatState, TemperatureUnit
from ._core.state.model import Control
from .coordinator import BalboaConfigEntry, SpaCoordinator
from .entity import BalboaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BalboaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([SpaClimate(entry.runtime_data)])


class SpaClimate(BalboaEntity, ClimateEntity):
    _attr_name = None
    _attr_translation_key = "spa"
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )
    _attr_preset_modes = ["low", "high"]
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator: SpaCoordinator) -> None:
        super().__init__(coordinator, "climate")

    @property
    def temperature_unit(self) -> str:
        status = self.coordinator.data.status
        return (
            UnitOfTemperature.FAHRENHEIT
            if status is not None and status.unit == TemperatureUnit.FAHRENHEIT
            else UnitOfTemperature.CELSIUS
        )

    @property
    def current_temperature(self) -> float | None:
        status = self.coordinator.data.status
        return status.current_temperature if status else None

    @property
    def target_temperature(self) -> float | None:
        status = self.coordinator.data.status
        return status.target_temperature if status else None

    @property
    def min_temp(self) -> float:
        state = self.coordinator.runtime.state
        options = state.options(Control.TARGET) if state else ()
        if options:
            assert isinstance(options[0], (int, float))
            return float(options[0])
        return 50 if self.temperature_unit == UnitOfTemperature.FAHRENHEIT else 10

    @property
    def max_temp(self) -> float:
        state = self.coordinator.runtime.state
        options = state.options(Control.TARGET) if state else ()
        if options:
            assert isinstance(options[-1], (int, float))
            return float(options[-1])
        return 104 if self.temperature_unit == UnitOfTemperature.FAHRENHEIT else 40

    @property
    def target_temperature_step(self) -> float:
        return 1 if self.temperature_unit == UnitOfTemperature.FAHRENHEIT else 0.5

    @property
    def preset_mode(self) -> str | None:
        status = self.coordinator.data.observed_status
        return ("high" if status.high_range else "low") if status else None

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in self._attr_preset_modes:
            raise HomeAssistantError("Unsupported temperature range")
        try:
            await self.coordinator.sessions.async_manual_setting(
                Control.HIGH_RANGE, preset_mode == "high"
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    @property
    def hvac_action(self) -> HVACAction | None:
        status = self.coordinator.data.status
        if status is None or status.heat_state == HeatState.UNKNOWN:
            return None
        return HVACAction.HEATING if status.heat_state == HeatState.HEATING else HVACAction.IDLE

    async def async_set_temperature(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.sessions.async_manual_temperature(kwargs[ATTR_TEMPERATURE])
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
