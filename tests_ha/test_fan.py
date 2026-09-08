"""Capability-aware native pump controls, including single-speed raw ON=2."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tools.simulator.server import Simulator

from .test_lifecycle import eventually


@pytest.mark.parametrize(
    "scenario,percentage,toggles",
    [("normal", 50, 1), ("normal", 100, 2), ("single-speed-pump", 100, 1)],
)
async def test_native_pump_percentage_is_verified_from_capabilities(
    hass, socket_enabled, scenario, percentage, toggles
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
        try:
            await eventually(lambda: hass.states.get("fan.balboa_spa_pump_1") is not None)
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            await hass.services.async_call(
                "fan",
                "set_percentage",
                {"entity_id": "fan.balboa_spa_pump_1", "percentage": percentage},
                blocking=True,
            )
            assert hass.states.get("fan.balboa_spa_pump_1").attributes["percentage"] == percentage
            assert simulator.physical_commands == toggles
            assert hass.states.get("fan.balboa_spa_pump_3") is None
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
