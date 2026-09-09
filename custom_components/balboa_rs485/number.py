"""Observed discrete pump speed and separate HA-owned session preferences."""

import math

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._core.state.model import Control
from .const import CONF_BATH_DURATION, CONF_BATH_MINIMUM
from .coordinator import BalboaConfigEntry, SpaCoordinator
from .entity import BalboaControlEntity, BalboaEntity, add_control_entities

PARALLEL_UPDATES = 0  # All physical aliases share the coordinator's bounded goal.

DESCRIPTIONS = (
    NumberEntityDescription(
        key=CONF_BATH_DURATION,
        translation_key=CONF_BATH_DURATION,
        native_min_value=1,
        native_max_value=1440,
        native_step=1,
        native_unit_of_measurement="min",
        device_class=NumberDeviceClass.DURATION,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key=CONF_BATH_MINIMUM,
        translation_key=CONF_BATH_MINIMUM,
        native_min_value=10,
        native_max_value=40,
        native_step=0.5,
        native_unit_of_measurement="°C",
        device_class=NumberDeviceClass.TEMPERATURE,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BalboaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(SessionPreference(entry.runtime_data, item) for item in DESCRIPTIONS)
    add_control_entities(entry, async_add_entities, (Control.PUMP1,), PumpSpeedNumber)


class PumpSpeedNumber(BalboaControlEntity, NumberEntity):
    """0=off, 1=circulation, 2=jets; actual capability and readback are authoritative."""

    _attr_translation_key = "pump_speed"
    _attr_icon = "mdi:pump"
    _attr_native_min_value = 0
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: SpaCoordinator, control: Control) -> None:
        super().__init__(coordinator, control)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{control.value}_speed"
        self._attr_translation_placeholders = {"index": control.value[-1]}

    @property
    def native_max_value(self) -> float:
        return max(1, len(self.options) - 1)

    @property
    def native_value(self) -> float | None:
        value, options = self.observed_value, self.options
        return options.index(value) if value is not None and value in options else None

    @property
    def extra_state_attributes(self) -> dict[str, str | bool | None]:
        state = self.coordinator.runtime.state
        reason = state.pump1_circulation_reason if state and self.available else None
        value = self.observed_value
        return {
            "speed_label": str(value) if value is not None else None,
            "circulation_required": True if reason else None,
            "circulation_reason": reason,
        }

    async def async_set_native_value(self, value: float) -> None:
        options = self.options
        if (
            not math.isfinite(value)
            or not float(value).is_integer()
            or not 0 <= value < len(options)
        ):
            raise ServiceValidationError("Pump speed must be an available whole step (0, 1 or 2)")
        await self.coordinator.async_command(self.control, options[int(value)])


class SessionPreference(BalboaEntity, NumberEntity):
    def __init__(self, coordinator: SpaCoordinator, description: NumberEntityDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> float:
        default = 120 if self.entity_description.key == CONF_BATH_DURATION else 36.5
        return float(self.coordinator.entry.options.get(self.entity_description.key, default))

    async def async_set_native_value(self, value: float) -> None:
        item = self.entity_description
        assert item.native_min_value is not None and item.native_max_value is not None
        assert item.native_step is not None
        if (
            not math.isfinite(value)
            or not item.native_min_value <= value <= item.native_max_value
            or not math.isclose(value / item.native_step, round(value / item.native_step))
        ):
            raise ServiceValidationError("Value must match the allowed bounds and step")
        # Config-entry options persist across HA restarts. No wire command is sent.
        entry = self.coordinator.entry
        normalized = int(value) if float(value).is_integer() else value
        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, item.key: normalized}
        )
        self.async_write_ha_state()
