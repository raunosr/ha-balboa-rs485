"""Diagnostic connection state, deliberately independent of physical availability."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from ._core.protocol.messages import (
    FAULT_NAMES,
    FaultLogMessage,
    HeatMode,
    HeatState,
    StatusMessage,
)
from ._core.range_session import RangeSession
from ._core.session import SessionPhase
from ._core.transport.connection import ConnectionState, Snapshot
from .coordinator import BalboaConfigEntry, SpaCoordinator
from .entity import BalboaEntity, BalboaFilterEntity, BalboaObservationEntity


@dataclass(frozen=True, kw_only=True)
class DiagnosticDescription(SensorEntityDescription):
    value_fn: Callable[[Snapshot], int | None]
    entity_category: EntityCategory = EntityCategory.DIAGNOSTIC


DIAGNOSTIC_SENSORS = (
    DiagnosticDescription(key="channel", translation_key="channel", value_fn=lambda s: s.channel),
    DiagnosticDescription(
        key="crc_errors", translation_key="crc_errors", value_fn=lambda s: s.crc_errors
    ),
    DiagnosticDescription(
        key="recoveries", translation_key="recoveries", value_fn=lambda s: s.recoveries
    ),
    DiagnosticDescription(
        key="channel_allocations_remaining",
        translation_key="channel_allocations_remaining",
        value_fn=lambda s: max(0, 3 - s.assignment_requests),
    ),
)


@dataclass(frozen=True, kw_only=True)
class StatusDescription(SensorEntityDescription):
    value_fn: Callable[[StatusMessage], str | None]


STATUS_SENSORS = (
    StatusDescription(
        key="heater_state",
        translation_key="heater_state",
        device_class=SensorDeviceClass.ENUM,
        options=["off", "heating", "waiting"],
        value_fn=lambda s: None if s.heat_state == HeatState.UNKNOWN else s.heat_state.name.lower(),
    ),
    StatusDescription(
        key="heating_mode",
        translation_key="heating_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["ready", "rest", "ready_in_rest"],
        value_fn=lambda s: None if s.heat_mode == HeatMode.UNKNOWN else s.heat_mode.name.lower(),
    ),
    StatusDescription(
        key="temperature_range",
        translation_key="temperature_range",
        device_class=SensorDeviceClass.ENUM,
        options=["low", "high"],
        value_fn=lambda s: "high" if s.high_range else "low",
    ),
    StatusDescription(
        key="reminder",
        translation_key="reminder",
        icon="mdi:bell-alert-outline",
        device_class=SensorDeviceClass.ENUM,
        options=["none", "clean_filter", "check_ph", "check_sanitizer", "unrecognized"],
        value_fn=lambda s: "unrecognized" if s.reminder == "unknown" else s.reminder,
    ),
    StatusDescription(
        key="spa_clock",
        translation_key="spa_clock",
        icon="mdi:clock-outline",
        value_fn=lambda s: s.clock,
    ),
    StatusDescription(
        key="clock_format",
        translation_key="clock_format",
        device_class=SensorDeviceClass.ENUM,
        options=["12h", "24h"],
        value_fn=lambda s: "24h" if s.clock_24h else "12h",
    ),
)

PREDICTION_SENSORS = (
    SensorEntityDescription(
        key="heating_rate",
        translation_key="heating_rate",
        native_unit_of_measurement="°C/h",
        icon="mdi:thermometer-chevron-up",
    ),
    SensorEntityDescription(
        key="heating_eta",
        translation_key="heating_eta",
        native_unit_of_measurement="min",
        device_class=SensorDeviceClass.DURATION,
    ),
    SensorEntityDescription(
        key="ready_at", translation_key="ready_at", device_class=SensorDeviceClass.TIMESTAMP
    ),
    SensorEntityDescription(
        key="prediction_mae",
        translation_key="prediction_mae",
        native_unit_of_measurement="min",
        device_class=SensorDeviceClass.DURATION,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="prediction_samples",
        translation_key="prediction_samples",
        icon="mdi:counter",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BalboaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        [
            ConnectionSensor(entry.runtime_data),
            HeatingSessionSensor(entry.runtime_data),
            WaterTemperatureSensor(entry.runtime_data),
            FilterDurationSensor(entry.runtime_data, 1),
            FilterDurationSensor(entry.runtime_data, 2),
            FaultSensor(entry.runtime_data, count=False),
            FaultSensor(entry.runtime_data, count=True),
            *(
                DiagnosticSensor(entry.runtime_data, description)
                for description in DIAGNOSTIC_SENSORS
            ),
            *(StatusSensor(entry.runtime_data, description) for description in STATUS_SENSORS),
            *(
                PredictionSensor(entry.runtime_data, description)
                for description in PREDICTION_SENSORS
            ),
        ]
    )


class FaultSensor(BalboaEntity, SensorEntity):
    """Latest historical log entry, not an assertion that a fault is active now."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:history"

    def __init__(self, coordinator: SpaCoordinator, *, count: bool) -> None:
        key = "fault_log_entries" if count else "latest_fault"
        super().__init__(coordinator, key)
        self.count = count
        self._attr_translation_key = key
        if not count:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = ["none", "unrecognized", *sorted(set(FAULT_NAMES.values()))]

    @property
    def fault(self) -> FaultLogMessage | None:
        state = self.coordinator.runtime.state
        return state.fault if state else None

    @property
    def available(self) -> bool:
        return super().available and self.fault is not None

    @property
    def native_value(self) -> int | str | None:
        fault = self.fault
        return (fault.count if self.count else fault.name) if fault else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        fault = self.fault
        if fault is None or fault.count == 0:
            return {"historical": True}
        return {
            "historical": True,
            "code": fault.code,
            "entry": fault.entry,
            "days_ago": fault.frame.payload[3],
            "spa_hour": fault.frame.payload[4],
            "spa_minute": fault.frame.payload[5],
        }


class DiagnosticSensor(BalboaEntity, SensorEntity):
    """Event-driven counts, not noisy per-frame counters or fabricated availability."""

    entity_description: DiagnosticDescription

    def __init__(self, coordinator: SpaCoordinator, description: DiagnosticDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> int | None:
        return self.entity_description.value_fn(self.coordinator.data)


class FilterDurationSensor(BalboaFilterEntity, SensorEntity):
    _attr_translation_key = "filter_cycle_duration"
    _attr_native_unit_of_measurement = "min"
    _attr_device_class = SensorDeviceClass.DURATION

    def __init__(self, coordinator: SpaCoordinator, cycle: int) -> None:
        super().__init__(coordinator, f"filter_cycle_{cycle}_duration")
        self.cycle = cycle
        self._attr_translation_placeholders = {"index": str(cycle)}

    @property
    def native_value(self) -> int | None:
        return self.schedule.cycles[self.cycle - 1].duration_minutes if self.schedule else None


class StatusSensor(BalboaObservationEntity, SensorEntity):
    entity_description: StatusDescription

    def __init__(self, coordinator: SpaCoordinator, description: StatusDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | None:
        status = self.coordinator.data.observed_status
        return self.entity_description.value_fn(status) if status else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "reminder":
            return None
        status = self.coordinator.data.observed_status
        return {"reminder_code": status.reminder_code if status else None}


class WaterTemperatureSensor(BalboaObservationEntity, SensorEntity):
    """Measured water temperature, never replaced by the requested setpoint."""

    _attr_translation_key = "water_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SpaCoordinator) -> None:
        super().__init__(coordinator, "water_temperature")

    @property
    def native_unit_of_measurement(self) -> str | None:
        status = self.coordinator.data.observed_status
        return f"°{status.unit.value}" if status else None

    @property
    def native_value(self) -> float | None:
        status = self.coordinator.data.observed_status
        return status.current_temperature if status else None


class PredictionSensor(BalboaEntity, SensorEntity):
    """Optional forecast; unknown is distinct from a verified physical measurement."""

    def __init__(self, coordinator: SpaCoordinator, description: SensorEntityDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> float | int | datetime | None:
        return self.coordinator.prediction.values.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.coordinator.prediction.attributes


class ConnectionSensor(BalboaEntity, SensorEntity):
    _attr_translation_key = "connection"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [state.value.lower() for state in ConnectionState]

    def __init__(self, coordinator: SpaCoordinator) -> None:
        super().__init__(coordinator, "connection")

    @property
    def available(self) -> bool:
        # This reports a failed/recovering connection; it must not disappear with it.
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> str:
        return self.coordinator.data.state.value.lower()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        snapshot = self.coordinator.data
        observed = snapshot.observed_status
        return {
            "protocol_mode": snapshot.mode.value,
            "protocol_candidate": snapshot.candidate.value,
            "controls_enabled": self.coordinator.controls_enabled,
            "status_stale": snapshot.health.status_stale,
            "channel_failure": snapshot.channel_failure,
            "observations_available": observed is not None,
            "observed_current_temperature": observed.current_temperature if observed else None,
            "observed_target_temperature": observed.target_temperature if observed else None,
            "observed_temperature_unit": observed.unit.value if observed else None,
            "observed_heat_state": observed.heat_state.name.lower() if observed else None,
        }


class HeatingSessionSensor(BalboaEntity, SensorEntity):
    """Durable intent, not an optimistic physical heater state."""

    _attr_translation_key = "heating_session"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["idle", *(phase.value for phase in SessionPhase)]
    _attr_icon = "mdi:hot-tub"

    def __init__(self, coordinator: SpaCoordinator) -> None:
        super().__init__(coordinator, "heating_session")

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> str | None:
        runner = self.coordinator.sessions.runner
        if runner.session is not None:
            return runner.session.phase.value
        return None if runner.storage_failed else "idle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        runner = self.coordinator.sessions.runner
        attributes: dict[str, Any] = {"blocked_reason": runner.blocked_reason}
        if (session := runner.session) is not None:
            attributes.update(
                {
                    "start_time": datetime.fromtimestamp(session.start_time, UTC).isoformat(),
                    "end_time": datetime.fromtimestamp(session.end_time, UTC).isoformat(),
                    "target_temperature": session.target,
                    "maintenance_temperature": session.maintenance,
                    "temperature_unit": session.unit.value,
                    "remaining_minutes": max(
                        0, round((session.end_time - dt_util.utcnow().timestamp()) / 60)
                    ),
                }
            )
            if isinstance(session, RangeSession):
                attributes.update(
                    {
                        "session_type": "bathing",
                        "operation_id": session.operation_id,
                        "step": session.step.value,
                        "original_range": "high" if session.original_range else "low",
                        "original_heating_policy": session.original_mode.name.lower(),
                        "original_high_temperature": session.original_high,
                        "restore_high_temperature": session.target_owned,
                        "restore_heating_policy": session.mode_owned,
                    }
                )
            else:
                attributes["session_type"] = "legacy"
        return attributes
