"""Named speed choices preserve existing fan entities and verified commands."""

import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tools.simulator.server import Simulator

from .test_lifecycle import eventually


@pytest.mark.parametrize(
    "scenario, choices, option, percentage",
    [
        ("normal", ["off", "circulation", "jets"], "circulation", 50),
        ("single-speed-pump", ["off", "on"], "on", 100),
    ],
)
async def test_named_pump_choice_and_existing_fan_share_observed_state(
    hass, socket_enabled, scenario, choices, option, percentage
):
    async with Simulator(port=0, interval=0.03, control_lab=True, scenario=scenario) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "classic-rs485"},
            options={"enable_controls": True},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        entity_id = "select.balboa_spa_pump_1_mode"
        try:
            await eventually(lambda: hass.states.get(entity_id) is not None)
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            assert hass.states.get(entity_id).attributes["options"] == choices
            await hass.services.async_call(
                "select", "select_option", {"entity_id": entity_id, "option": option}, blocking=True
            )
            assert hass.states.get(entity_id).state == option
            assert hass.states.get("fan.balboa_spa_pump_1").attributes["percentage"] == percentage
            assert simulator.physical_commands == 1
            await hass.services.async_call(
                "fan", "turn_off", {"entity_id": "fan.balboa_spa_pump_1"}, blocking=True
            )
            assert hass.states.get(entity_id).state == "off"
            assert hass.states.get("select.balboa_spa_pump_3_mode") is None
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_heat_policy_selection_keeps_range_target_and_transient_distinct(
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
        entity_id = "select.balboa_spa_heating_policy"

        async def choose(option):
            await hass.services.async_call(
                "select", "select_option", {"entity_id": entity_id, "option": option}, blocking=True
            )

        try:
            await eventually(lambda: hass.states.get(entity_id) is not None)
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            assert hass.states.get(entity_id).attributes["options"] == ["ready", "rest"]
            await choose("rest")
            assert simulator.heat_mode == 1
            assert hass.states.get(entity_id).state == "rest"
            simulator.heat_mode = 2
            await eventually(
                lambda: hass.states.get("sensor.balboa_spa_heating_mode").state == "ready_in_rest"
            )
            assert hass.states.get(entity_id).state == "unknown"
            await choose("ready")
            assert simulator.heat_mode == 0
            assert simulator.physical_commands == 3
            assert simulator.high_range
            assert simulator.target_temperature == 38
            await hass.services.async_call(
                "balboa_rs485",
                "start_heating_session",
                {
                    "config_entry_id": entry.entry_id,
                    "duration": "01:00:00",
                    "target_temperature": 38,
                    "maintenance_temperature": 38,
                },
                blocking=True,
            )
            with pytest.raises(HomeAssistantError, match="session"):
                await choose("rest")
            assert simulator.physical_commands == 3
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
