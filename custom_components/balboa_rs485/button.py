"""Native session buttons wrap the same durable, validated actions as automations."""

from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._core.state.model import Control
from .const import CONF_BATH_DURATION, CONF_BATH_MINIMUM, DOMAIN
from .coordinator import BalboaConfigEntry, SpaCoordinator
from .entity import BalboaEntity

ACTIONS = {
    "start_bathing": "start_bathing_session",
    "end_bathing": "cancel_heating_session",
    "extend_bathing": "extend_heating_session",
    "reduce_bathing": "reduce_heating_session",
}
MAINTENANCE = {
    "normal_operation": Control.NORMAL_OPERATION,
    "soak": Control.SOAK,
    "acknowledge_reminder": Control.ACK_REMINDER,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BalboaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(SessionButton(entry.runtime_data, key) for key in ACTIONS)
    async_add_entities(MaintenanceButton(entry.runtime_data, key) for key in MAINTENANCE)


class MaintenanceButton(BalboaEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SpaCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self.entity_description = ButtonEntityDescription(
            key=key, translation_key=key, icon="mdi:hot-tub", entity_category=EntityCategory.CONFIG
        )

    async def async_press(self) -> None:
        control = MAINTENANCE[self.entity_description.key]
        if control == Control.ACK_REMINDER:
            await self.coordinator.async_command(control, True)
            return
        try:
            await self.coordinator.sessions.async_manual_setting(control, True)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err


class SessionButton(BalboaEntity, ButtonEntity):
    def __init__(self, coordinator: SpaCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self.entity_description = ButtonEntityDescription(
            key=key, translation_key=key, icon="mdi:hot-tub"
        )

    @property
    def available(self) -> bool:
        # End/adjust can persist while offline; start is validated against fresh state.
        return self.coordinator.last_update_success

    async def async_press(self) -> None:
        entry = self.coordinator.entry
        data: dict[str, Any] = {"config_entry_id": entry.entry_id}
        if self.entity_description.key == "start_bathing":
            data.update(
                {
                    "duration": {"minutes": entry.options.get(CONF_BATH_DURATION, 120)},
                    "minimum_temperature_c": entry.options.get(CONF_BATH_MINIMUM, 36.5),
                }
            )
        await self.hass.services.async_call(
            DOMAIN, ACTIONS[self.entity_description.key], data, blocking=True
        )
