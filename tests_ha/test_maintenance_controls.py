"""Native maintenance controls leave fault history and safety interlocks intact."""

import pytest
from homeassistant.exceptions import HomeAssistantError

from tools.simulator.server import Simulator

from .test_lifecycle import eventually
from .test_sessions import setup_spa


async def test_fault_notification_after_ack_fails_once_then_recovers_on_normal_status(
    hass, socket_enabled
):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        try:
            simulator.reminder_code = 3
            simulator.reminder_queue = [30]
            await eventually(lambda: entry.runtime_data.runtime.state.status.reminder_code == 3)
            with pytest.raises(HomeAssistantError, match="FAILED.*not retried"):
                await hass.services.async_call(
                    "button",
                    "press",
                    {"entity_id": "button.balboa_spa_acknowledge_reminder"},
                    blocking=True,
                )
            await eventually(lambda: entry.runtime_data.runtime.connection.snapshot.available)
            # Transport readiness precedes the coordinator/entity state write.
            # HA skips unavailable targets instead of invoking their service;
            # wait at the actual call boundary before checking the fault guard.
            await eventually(lambda: hass.states.get("climate.balboa_spa").state != "unavailable")
            assert entry.runtime_data.runtime.state.status.reminder_code == 30
            assert simulator.physical_commands == 1
            with pytest.raises(HomeAssistantError, match="unsupported_notification_30"):
                await hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": "climate.balboa_spa", "temperature": 37},
                    blocking=True,
                )
            assert simulator.physical_commands == 1
            simulator.reminder_code = None
            # A fresh normal status may arrive before setup is re-queried in
            # the new epoch. Temperature writes also require those limits.
            await eventually(
                lambda: (
                    entry.runtime_data.runtime.state.controls_safe
                    and entry.runtime_data.runtime.state.setup is not None
                    and hass.states.get("climate.balboa_spa").state != "unavailable"
                )
            )
            await hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": "climate.balboa_spa", "temperature": 37},
                blocking=True,
            )
            assert simulator.physical_commands == 2
            assert hass.states.get("climate.balboa_spa").attributes["temperature"] == 37
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("mode", ["classic-rs485", "direct-rs485-tcp"])
@pytest.mark.parametrize("next_code,visible", [(2, "none"), (4, "clean_filter"), (14, "none")])
async def test_ack_next_reminder_then_climate_and_light_do_not_stall(
    hass, socket_enabled, mode, next_code, visible
):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator, mode=mode)
        try:
            simulator.reminder_code = 3
            simulator.reminder_queue = [next_code]
            await eventually(lambda: entry.runtime_data.runtime.state.status.reminder_code == 3)
            original_fault = entry.runtime_data.runtime.state.fault
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": "button.balboa_spa_acknowledge_reminder"},
                blocking=True,
            )
            assert simulator.physical_commands == 1
            assert simulator.reminder_code == next_code
            reminder = hass.states.get("sensor.balboa_spa_reminder")
            assert reminder.state == visible
            assert reminder.attributes["reminder_code"] == next_code
            await hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": "climate.balboa_spa", "temperature": 37},
                blocking=True,
            )
            await hass.services.async_call(
                "light",
                "turn_on",
                {"entity_id": "light.balboa_spa_light_1"},
                blocking=True,
            )
            assert hass.states.get("climate.balboa_spa").attributes["temperature"] == 37
            assert simulator.light_states[0]
            assert simulator.physical_commands == 3
            assert simulator.reminder_code == next_code
            assert entry.runtime_data.runtime.state.fault == original_fault
            history = entry.runtime_data.runtime.engine.history
            assert all(item.result == "VERIFIED" for item in history)
            assert history[0].action.intent.reminder_code == 3
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_native_hold_normal_soak_and_reminder_acknowledgement(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        try:
            assert hass.states.get("switch.balboa_spa_hold") is not None
            await hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": "switch.balboa_spa_hold"},
                blocking=True,
            )
            assert simulator.hold
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": "button.balboa_spa_normal_operation"},
                blocking=True,
            )
            assert not simulator.hold
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": "select.balboa_spa_pump_1_mode", "option": "jets"},
                blocking=True,
            )
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": "button.balboa_spa_soak"},
                blocking=True,
            )
            assert not any(simulator.pump_states)
            simulator.reminder_code = 4
            await eventually(lambda: entry.runtime_data.runtime.state.status.reminder_code == 4)
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": "button.balboa_spa_acknowledge_reminder"},
                blocking=True,
            )
            assert entry.runtime_data.runtime.state.status.reminder == "none"
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
