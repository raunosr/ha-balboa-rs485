"""Native HA services during write loss: real coordinator, TCP runtime and entities."""

import asyncio
from contextlib import suppress

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from tools.simulator.server import Simulator

from .test_lifecycle import eventually
from .test_sessions import setup_spa


async def set_speed(hass, value):
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.balboa_spa_pump_1_speed", "value": value},
        blocking=True,
    )


async def cleanup(hass, entry, tasks):
    for task in tasks:
        task.cancel()
        with suppress(asyncio.CancelledError, HomeAssistantError):
            await task
    await hass.config_entries.async_unload(entry.entry_id)


async def test_fast_slider_values_send_only_latest_and_report_replacement_not_success(
    hass, socket_enabled
):
    from custom_components.balboa_rs485.diagnostics import async_get_config_entry_diagnostics

    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        simulator.pump_states[0] = 2
        entry = await setup_spa(hass, simulator)
        tasks = []
        try:
            for value in (0, 1, 0):
                tasks.append(asyncio.create_task(set_speed(hass, value)))
                await asyncio.sleep(0)
            results = await asyncio.gather(*tasks, return_exceptions=True)
            assert all(isinstance(r, ServiceValidationError) for r in results[:2])
            assert all(r.translation_key == "command_replaced" for r in results[:2])
            assert results[-1] is None
            assert simulator.physical_commands == 1
            await eventually(
                lambda: hass.states.get("sensor.balboa_spa_pump_1_command").state == "verified"
            )
            state = hass.states.get("sensor.balboa_spa_pump_1_command")
            assert state.attributes["observed_speed"] == state.attributes["requested_speed"] == 0
            report = await async_get_config_entry_diagnostics(hass, entry)
            events = report["commands"]["intent_events"]
            assert sum(e["kind"] == "requested" for e in events) == 3
            assert sum(e["stage"] == "SUPERSEDED" for e in events) == 2
            assert report["commands"]["latest_intents"][0]["stage"] == "VERIFIED"
            assert entry.runtime_data._pending == {}
        finally:
            await cleanup(hass, entry, tasks)


async def test_number_accepts_replacement_during_recovery_without_showing_cached_speed(
    hass, socket_enabled
):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        simulator.pump_states[0] = 2
        simulator.drop_pump_commands = 1
        entry = await setup_spa(hass, simulator, mode="direct-rs485-tcp")
        runtime = entry.runtime_data.runtime
        runtime.engine.confirmation_timeout = 0.35
        tasks = []
        try:
            tasks.append(asyncio.create_task(set_speed(hass, 1)))
            await eventually(
                lambda: hass.states.get("sensor.balboa_spa_pump_1_command").state == "recovering"
            )
            assert not runtime.connection.snapshot.available
            number = hass.states.get("number.balboa_spa_pump_1_speed")
            assert number.state == "unknown"
            assert number.attributes["requested_speed"] == 1
            tasks.append(asyncio.create_task(set_speed(hass, 0)))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            assert isinstance(results[0], ServiceValidationError)
            assert results[0].translation_key == "command_replaced"
            assert results[1] is None
            assert simulator.physical_commands == 2
            assert simulator.pump_states[0] == 0
            await eventually(
                lambda: hass.states.get("sensor.balboa_spa_pump_1_command").state == "verified"
            )
            assert runtime.engine.history[1].action.epoch > runtime.engine.history[0].action.epoch
        finally:
            await cleanup(hass, entry, tasks)


async def test_shared_deadline_fails_cleanly_and_does_not_keep_retrying(
    hass, socket_enabled, monkeypatch
):
    from custom_components.balboa_rs485 import coordinator as module

    monkeypatch.setattr(module, "PUMP_COMMAND_TIMEOUT", 1.2)
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        simulator.drop_pump_commands = 99
        entry = await setup_spa(hass, simulator)
        coordinator = entry.runtime_data
        coordinator.runtime.engine.confirmation_timeout = 0.35
        try:
            with pytest.raises(HomeAssistantError, match="deadline"):
                await set_speed(hass, 2)
            await eventually(
                lambda: hass.states.get("sensor.balboa_spa_pump_1_command").state == "failed"
            )
            count = simulator.physical_commands
            assert 1 <= count <= coordinator.runtime.engine.max_actions
            await eventually(lambda: coordinator.runtime.connection.snapshot.available)
            await hass.services.async_call(
                "light", "turn_on", {"entity_id": "light.balboa_spa_light_1"}, blocking=True
            )
            assert simulator.physical_commands == count + 1
            assert coordinator._pending == coordinator._waiters == coordinator._deadlines == {}
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_unload_cancels_a_coalescing_window_without_transmission(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        tasks = [asyncio.create_task(set_speed(hass, 2))]
        await eventually(lambda: bool(entry.runtime_data._pending))
        await hass.config_entries.async_unload(entry.entry_id)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert isinstance(results[0], HomeAssistantError)
        assert simulator.physical_commands == 0
        assert not entry.runtime_data.runtime.connection.running
