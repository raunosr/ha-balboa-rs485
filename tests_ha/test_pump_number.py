"""One default Pump 1 slider; old entity IDs remain usable compatibility aliases."""

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tools.simulator.server import Simulator

from .test_lifecycle import eventually
from .test_sessions import setup_spa


@pytest.mark.parametrize(
    "scenario,maximum,values", [("normal", 2, (1, 2, 1, 0)), ("single-speed-pump", 1, (1, 0))]
)
async def test_slider_uses_observed_discrete_speeds_and_keeps_aliases(
    hass, socket_enabled, scenario, maximum, values
):
    async with Simulator(port=0, interval=0.03, control_lab=True, scenario=scenario) as sim:
        entry = await setup_spa(hass, sim)
        registry = er.async_get(hass)
        entity_id = "number.balboa_spa_pump_1_speed"
        try:
            await eventually(lambda: hass.states.get(entity_id) is not None)
            state = hass.states.get(entity_id)
            assert state.attributes["mode"] == "slider"
            assert (state.attributes["min"], state.attributes["max"], state.attributes["step"]) == (
                0,
                maximum,
                1,
            )
            assert not registry.async_get(entity_id).hidden
            for alias in ("fan.balboa_spa_pump_1", "select.balboa_spa_pump_1_mode"):
                assert registry.async_get(alias).hidden
                assert not registry.async_get(alias).disabled
            assert not registry.async_get("fan.balboa_spa_pump_2").hidden
            for value in values:
                await hass.services.async_call(
                    "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
                )
                assert float(hass.states.get(entity_id).state) == value
                assert sim.pump_states[0] == (2 if maximum == 1 and value == 1 else value)
            commands = sim.physical_commands
            with pytest.raises((HomeAssistantError, ValueError)):
                await hass.services.async_call(
                    "number", "set_value", {"entity_id": entity_id, "value": 0.5}, blocking=True
                )
            assert sim.physical_commands == commands
            assert sim.stats.connections == 1
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_existing_renamed_alias_is_hidden_once_and_user_can_unhide(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as sim:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": sim.port, "protocol_mode": "classic-rs485"},
            options={"enable_controls": True},
        )
        entry.add_to_hass(hass)
        registry = er.async_get(hass)
        alias = registry.async_get_or_create(
            "fan",
            "balboa_rs485",
            f"{entry.entry_id}_pump1",
            suggested_object_id="my_existing_pump",
            config_entry=entry,
        )
        assert not alias.hidden and not alias.disabled
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            await eventually(lambda: registry.async_get(alias.entity_id).hidden)
            registry.async_update_entity(alias.entity_id, hidden_by=None)
            assert await hass.config_entries.async_reload(entry.entry_id)
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            assert not registry.async_get(alias.entity_id).hidden
            assert not registry.async_get(alias.entity_id).disabled
            assert registry.async_get(alias.entity_id).unique_id == alias.unique_id
            assert sim.physical_commands == 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
