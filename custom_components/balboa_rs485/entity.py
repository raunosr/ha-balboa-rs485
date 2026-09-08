"""Stable entry-scoped identity and observed availability for native entities."""

from collections.abc import Callable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._core.protocol.settings import FilterSchedule
from ._core.state.model import Control, Value
from .const import DOMAIN
from .coordinator import BalboaConfigEntry, SpaCoordinator


class BalboaEntity(CoordinatorEntity[SpaCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: SpaCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.entry.title,
            manufacturer="Balboa",
        )
        configuration = coordinator.data.configuration
        if configuration is not None:
            self._attr_device_info["model"] = configuration.information.model
            self._attr_device_info["sw_version"] = ".".join(
                str(part) for part in configuration.information.software_version
            )

    @property
    def available(self) -> bool:
        state = self.coordinator.runtime.state
        return (
            super().available
            and self.coordinator.data.available
            and state is not None
            and state.available
            and state.epoch == self.coordinator.data.epoch
        )


class BalboaObservationEntity(BalboaEntity):
    """Fresh passive status remains useful without a writable bus channel."""

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.coordinator.data.observed_status is not None
        )


class BalboaControlEntity(BalboaEntity):
    """A capability can disappear without destroying the stable entity identity."""

    def __init__(self, coordinator: SpaCoordinator, control: Control) -> None:
        super().__init__(coordinator, control.value)
        self.control = control

    @property
    def options(self) -> tuple[Value, ...]:
        state = self.coordinator.runtime.state
        return state.options(self.control) if state else ()

    @property
    def observed_value(self) -> Value | None:
        state = self.coordinator.runtime.state
        return state.value(self.control) if state else None

    @property
    def available(self) -> bool:
        return super().available and bool(self.options)


class BalboaFilterEntity(BalboaEntity):
    """Last received schedule in this connection epoch; changes always re-query."""

    @property
    def schedule(self) -> FilterSchedule | None:
        state = self.coordinator.runtime.state
        return FilterSchedule(state.filters.cycles) if state and state.filters else None

    @property
    def available(self) -> bool:
        return super().available and self.schedule is not None


def add_control_entities(
    entry: BalboaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    controls: tuple[Control, ...],
    factory: Callable[[SpaCoordinator, Control], BalboaEntity],
) -> None:
    """Discover newly synchronized capabilities once, including after reconnect."""
    added: set[Control] = set()

    @callback
    def discover() -> None:
        state = entry.runtime_data.runtime.state
        if state is None:
            return
        new = [control for control in controls if control not in added and state.options(control)]
        if new:
            added.update(new)
            async_add_entities([factory(entry.runtime_data, control) for control in new])

    entry.async_on_unload(entry.runtime_data.async_add_listener(discover))
    discover()
