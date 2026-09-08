"""Low/High selects stored spa profiles; it never invents the other target."""

import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tools.simulator.server import Simulator

from .test_lifecycle import eventually


async def test_range_presets_preserve_targets_and_block_active_session(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "classic-rs485"},
            options={"enable_controls": True},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)

        async def preset(name):
            await hass.services.async_call(
                "climate",
                "set_preset_mode",
                {"entity_id": "climate.balboa_spa", "preset_mode": name},
                blocking=True,
            )

        try:
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            climate = hass.states.get("climate.balboa_spa")
            assert climate.attributes["preset_modes"] == ["low", "high"]
            await preset("low")
            assert hass.states.get("climate.balboa_spa").attributes["temperature"] == 27
            await hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": "climate.balboa_spa", "temperature": 26},
                blocking=True,
            )
            await preset("high")
            assert hass.states.get("climate.balboa_spa").attributes["temperature"] == 38
            assert hass.states.get("climate.balboa_spa").attributes["preset_mode"] == "high"
            assert simulator.heat_mode == 0
            assert simulator.physical_commands == 3
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
                await preset("low")
            assert simulator.high_range
            assert simulator.physical_commands == 3
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
