"""HA-owned session preferences, explicitly not physical spa readback."""

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

from .const import CONF_BATH_DURATION, CONF_BATH_MINIMUM
from .coordinator import BalboaConfigEntry, SpaCoordinator
from .entity import BalboaEntity

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
