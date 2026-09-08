"""HA service calls express intent and finish only after physical observations."""

import asyncio

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tools.simulator.server import Simulator

from .test_lifecycle import eventually


@pytest.mark.parametrize("reminder_variant", [False, True])
async def test_temperature_service_waits_for_observed_target(
    hass, socket_enabled, monkeypatch, reminder_variant
):
    if reminder_variant:
        from tests.helpers import install_filter_reminder_variant

        install_filter_reminder_variant(monkeypatch)
    async with Simulator(
        port=0, interval=0.03, control_lab=True, channel_lab=reminder_variant
    ) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={
                "host": "127.0.0.1",
                "port": simulator.port,
                "protocol_mode": "channel-rs485" if reminder_variant else "classic-rs485",
            },
            options={"enable_controls": True},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
        try:
            await hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": "climate.balboa_spa", "temperature": 35.5},
                blocking=True,
            )
            assert hass.states.get("climate.balboa_spa").attributes["temperature"] == 35.5
            assert simulator.target_temperature == 35.5
            assert simulator.physical_commands == 1
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_controls_require_explicit_option_without_reconnecting(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "classic-rs485"},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
        try:
            with pytest.raises(HomeAssistantError, match="disabled"):
                await hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": "climate.balboa_spa", "temperature": 35},
                    blocking=True,
                )
            assert simulator.physical_commands == 0
            flow = await hass.config_entries.options.async_init(entry.entry_id)
            assert flow["type"] == FlowResultType.FORM
            assert flow["data_schema"]({})["enable_controls"] is False
            result = await hass.config_entries.options.async_configure(
                flow["flow_id"], user_input={"enable_controls": True}
            )
            assert result["type"] == FlowResultType.CREATE_ENTRY
            await hass.async_block_till_done()
            await hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": "climate.balboa_spa", "temperature": 35},
                blocking=True,
            )
            assert simulator.physical_commands == 1
            assert simulator.stats.connections == 1
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_disabling_controls_cancels_remaining_pump_intent_without_another_toggle(
    hass, socket_enabled
):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "classic-rs485"},
            options={"enable_controls": True},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
        command = asyncio.create_task(
            hass.services.async_call(
                "fan",
                "set_percentage",
                {"entity_id": "fan.balboa_spa_pump_1", "percentage": 100},
                blocking=True,
            )
        )
        try:
            await eventually(lambda: simulator.physical_commands == 1)
            hass.config_entries.async_update_entry(entry, options={"enable_controls": False})
            with pytest.raises(HomeAssistantError, match="CANCELLED"):
                await command
            await eventually(lambda: not entry.runtime_data.runtime.engine.busy)
            assert simulator.physical_commands == 1
            assert simulator.pump_states[0] == 1
            assert simulator.stats.connections == 1
        finally:
            if not command.done():
                command.cancel()
            await asyncio.gather(command, return_exceptions=True)
            await hass.config_entries.async_unload(entry.entry_id)
