"""Read-only safety observations. Never use them to bypass command guards."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._core.protocol.messages import HeatState, StatusMessage
from .coordinator import BalboaConfigEntry, SpaCoordinator
from .entity import BalboaObservationEntity


@dataclass(frozen=True, kw_only=True)
class ObservationDescription(BinarySensorEntityDescription):
    value_fn: Callable[[StatusMessage], bool | None]


DESCRIPTIONS = (
    ObservationDescription(
        key="heater_running",
        translation_key="heater_running",
        icon="mdi:radiator",
        value_fn=lambda s: (
            None if s.heat_state == HeatState.UNKNOWN else s.heat_state == HeatState.HEATING
        ),
    ),
    ObservationDescription(
        key="hold", translation_key="hold", icon="mdi:pause-circle", value_fn=lambda s: s.hold
    ),
    ObservationDescription(
        key="priming", translation_key="priming", icon="mdi:pump", value_fn=lambda s: s.priming
    ),
    # HA's LOCK class means ON = unlocked; these names explicitly mean locked.
    ObservationDescription(
        key="panel_locked",
        translation_key="panel_locked",
        icon="mdi:lock",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.panel_locked,
    ),
    ObservationDescription(
        key="settings_locked",
        translation_key="settings_locked",
        icon="mdi:lock-cog",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.settings_locked,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BalboaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        ObservationSensor(entry.runtime_data, description) for description in DESCRIPTIONS
    )
    async_add_entities(FilterRunningSensor(entry.runtime_data, cycle) for cycle in (1, 2))
    added = False

    @callback
    def discover() -> None:
        nonlocal added
        state = entry.runtime_data.runtime.state
        if not added and state and state.has_circulation_pump:
            added = True
            async_add_entities([CirculationSensor(entry.runtime_data)])

    entry.async_on_unload(entry.runtime_data.async_add_listener(discover))
    discover()


class CirculationSensor(BalboaObservationEntity, BinarySensorEntity):
    _attr_translation_key = "circulation_pump_running"
    _attr_icon = "mdi:pump"

    def __init__(self, coordinator: SpaCoordinator) -> None:
        super().__init__(coordinator, "circulation_pump_running")

    @property
    def available(self) -> bool:
        state = self.coordinator.runtime.state
        return super().available and state is not None and state.has_circulation_pump

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.data.observed_status
        return status.circulation_pump if status else None


class FilterRunningSensor(BalboaObservationEntity, BinarySensorEntity):
    _attr_translation_key = "filter_cycle_running"
    _attr_icon = "mdi:filter-outline"

    def __init__(self, coordinator: SpaCoordinator, cycle: int) -> None:
        super().__init__(coordinator, f"filter_cycle_{cycle}_running")
        self.cycle = cycle
        self._attr_translation_placeholders = {"index": str(cycle)}

    @property
    def model(self) -> str | None:
        state = self.coordinator.runtime.state
        return state.model if state else None

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.data.observed_status
        return status.filter_running_for_model(self.model)[self.cycle - 1] if status else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self.coordinator.data.observed_status
        return {
            "interpretation": (
                "bp6013g2_cycle1_source_inferred"
                if self.cycle == 1
                else "bp6013g2_cycle2_observed_boundary"
            )
            if self.model == "BP6013G2"
            else "source_consensus_not_hardware_validated",
            "conflicting_bits": status is not None and self.is_on is None,
            "status_flags": status.frame.payload[9] if status else None,
        }


class ObservationSensor(BalboaObservationEntity, BinarySensorEntity):
    entity_description: ObservationDescription

    def __init__(self, coordinator: SpaCoordinator, description: ObservationDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.data.observed_status
        return self.entity_description.value_fn(status) if status else None
