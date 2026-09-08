"""Advanced native unit/clock controls use the shared verified runtime."""

import pytest
from homeassistant.exceptions import HomeAssistantError

from tools.simulator.server import Simulator

from .test_lifecycle import eventually
from .test_sessions import action, setup_spa


async def test_clock_and_temperature_unit_controls_and_active_session_guard(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        try:
            entity = "select.balboa_spa_temperature_unit"
            assert hass.states.get(entity) is not None
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": entity, "option": "fahrenheit"},
                blocking=True,
            )
            assert entry.runtime_data.runtime.state.status.unit == "F"
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": entity, "option": "celsius"},
                blocking=True,
            )
            await hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": "switch.balboa_spa_clock_24h"},
                blocking=True,
            )
            assert simulator.clock_24h
            assert simulator.clock_minutes == 720
            await hass.services.async_call(
                "time",
                "set_value",
                {"entity_id": "time.balboa_spa_clock", "time": "18:45"},
                blocking=True,
            )
            assert simulator.clock_minutes == 18 * 60 + 45
            await action(hass, entry, "start_bathing_session", duration="01:00:00")
            await eventually(lambda: entry.runtime_data.sessions.session.step == "active")
            with pytest.raises(HomeAssistantError, match="session"):
                await hass.services.async_call(
                    "select",
                    "select_option",
                    {"entity_id": entity, "option": "fahrenheit"},
                    blocking=True,
                )
            assert entry.runtime_data.runtime.state.status.unit == "C"
            await action(hass, entry, "cancel_heating_session")
            await eventually(lambda: entry.runtime_data.sessions.session is None)
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
