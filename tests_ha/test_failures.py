"""Failure boundaries are exercised through real HA services and TCP streams."""

import asyncio
from contextlib import suppress

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tools.simulator.server import Simulator

from .test_lifecycle import eventually


async def test_lost_confirmation_does_not_optimistically_update_or_repeat_toggle(
    hass, socket_enabled
):
    async with Simulator(
        port=0, interval=0.03, control_lab=True, scenario="lost-status-after-command"
    ) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "classic-rs485"},
            options={"enable_controls": True},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        action = None
        try:
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            assert hass.states.get("fan.balboa_spa_pump_1").state == "off"
            action = asyncio.create_task(
                hass.services.async_call(
                    "fan",
                    "set_percentage",
                    {"entity_id": "fan.balboa_spa_pump_1", "percentage": 50},
                    blocking=True,
                )
            )
            await eventually(lambda: simulator.physical_commands == 1)
            assert simulator.pump_states[0] == 1
            assert hass.states.get("fan.balboa_spa_pump_1").state == "off"
            assert not action.done()
            await asyncio.wait_for(action, 15)
            await eventually(lambda: hass.states.get("fan.balboa_spa_pump_1").state == "on")
            assert hass.states.get("fan.balboa_spa_pump_1").attributes["percentage"] == 50
            assert simulator.physical_commands == 1
            assert simulator.stats.connections == 2
        finally:
            if action is not None:
                action.cancel()
                with suppress(asyncio.CancelledError):
                    await action
            await hass.config_entries.async_unload(entry.entry_id)


async def test_home_assistant_stop_closes_connection_and_unload_remains_idempotent(
    hass, socket_enabled
):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "classic-rs485"},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        connection = entry.runtime_data.runtime.connection
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
        await eventually(lambda: not connection.running)
        await eventually(lambda: simulator.active_connections == 0)
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_silent_open_socket_is_unavailable_before_reconnect(hass, socket_enabled):
    async with Simulator(port=0, interval=0.1, control_lab=True) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "classic-rs485"},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            simulator.scenario = "silent-zombie-socket"
            await eventually(lambda: hass.states.get("climate.balboa_spa").state == "unavailable")
            assert simulator.active_connections == 1
            assert simulator.stats.connections == 1
            assert simulator.physical_commands == 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("source", ["user", "reconfigure"])
async def test_invalid_endpoint_returns_a_recoverable_form_without_sockets(hass, source):
    context = {"source": source}
    if source == "reconfigure":
        entry = MockConfigEntry(
            domain="balboa_rs485",
            data={"host": "127.0.0.1", "port": 8899, "protocol_mode": "auto"},
        )
        entry.add_to_hass(hass)
        context["entry_id"] = entry.entry_id
    result = await hass.config_entries.flow.async_init(
        "balboa_rs485",
        context=context,
        data={"host": "   ", "port": 8899, "protocol_mode": "auto"},
    )
    assert result["type"] == "form"
    assert result["step_id"] == source
    assert result["errors"] == {"base": "cannot_connect"}


async def test_setup_without_valid_status_cleans_up_and_can_be_retried(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, scenario="unknown-protocol") as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "auto"},
        )
        entry.add_to_hass(hass)
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await eventually(lambda: simulator.active_connections == 0)
        assert simulator.stats.received_bytes == 0
        simulator.scenario = "normal"
        assert await hass.config_entries.async_reload(entry.entry_id)
        assert simulator.active_connections == 1
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_cancelled_command_waiter_cancels_goal_but_keeps_observed_physical_step(
    hass, socket_enabled
):
    from custom_components.balboa_rs485._core.state.model import Control, PumpState

    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "classic-rs485"},
            options={"enable_controls": True},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        action = None
        try:
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            action = asyncio.create_task(
                entry.runtime_data.async_command(Control.PUMP1, PumpState.HIGH)
            )
            await eventually(lambda: simulator.physical_commands == 1)
            action.cancel()
            with pytest.raises(asyncio.CancelledError):
                await action
            await eventually(lambda: not entry.runtime_data.runtime.engine.busy)
            assert simulator.pump_states[0] == 1
            assert simulator.physical_commands == 1
            assert hass.states.get("fan.balboa_spa_pump_1").attributes["percentage"] == 50
        finally:
            if action is not None:
                action.cancel()
                await asyncio.gather(action, return_exceptions=True)
            await hass.config_entries.async_unload(entry.entry_id)


async def test_nonrepresentable_temperature_is_rejected_without_transmission(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "classic-rs485"},
            options={"enable_controls": True},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            with pytest.raises(HomeAssistantError, match="Unsupported desired"):
                await hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": "climate.balboa_spa", "temperature": 35.2},
                    blocking=True,
                )
            assert simulator.physical_commands == 0
            assert hass.states.get("climate.balboa_spa").attributes["temperature"] == 38
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_unload_cancels_pending_service_with_a_clear_ha_error(hass, socket_enabled):
    async with Simulator(
        port=0, interval=0.03, control_lab=True, scenario="lost-status-after-command"
    ) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "classic-rs485"},
            options={"enable_controls": True},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
        action = asyncio.create_task(
            hass.services.async_call(
                "fan",
                "set_percentage",
                {"entity_id": "fan.balboa_spa_pump_1", "percentage": 100},
                blocking=True,
            )
        )
        try:
            await eventually(lambda: simulator.physical_commands == 1)
            assert await hass.config_entries.async_unload(entry.entry_id)
            with pytest.raises(HomeAssistantError, match="CANCELLED"):
                await action
            await eventually(lambda: simulator.active_connections == 0)
            assert simulator.physical_commands == 1
        finally:
            action.cancel()
            await asyncio.gather(action, return_exceptions=True)
            await hass.config_entries.async_unload(entry.entry_id)
