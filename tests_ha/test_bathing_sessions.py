"""Actual HA storage/reload acceptance for range-aware bathing intent."""

import pytest
import voluptuous as vol

from tools.simulator.server import Simulator

from .test_lifecycle import eventually
from .test_sessions import action, setup_spa


async def test_bathing_action_survives_reload_and_cleans_up_original_profiles(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        simulator.target_temperature = 35
        simulator.high_range = False
        simulator.target_temperature = 26
        simulator.heat_mode = 1
        entry = await setup_spa(hass, simulator)
        try:
            await action(hass, entry, "start_bathing_session", duration="01:00:00")
            await eventually(
                lambda: getattr(entry.runtime_data.sessions.session, "step", None) == "active"
            )
            session = entry.runtime_data.sessions.session
            operation_id, end = session.operation_id, session.end_time
            assert simulator.target_temperature == 36.5
            assert simulator.high_range
            assert simulator.heat_mode == 0
            count = simulator.physical_commands
            assert await hass.config_entries.async_unload(entry.entry_id)
            assert await hass.config_entries.async_setup(entry.entry_id)
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            session = entry.runtime_data.sessions.session
            assert session.operation_id == operation_id
            assert session.end_time == end
            assert not entry.runtime_data.sessions.runner.storage_failed
            assert simulator.physical_commands == count
            await action(hass, entry, "cancel_heating_session")
            await eventually(lambda: entry.runtime_data.sessions.session is None)
            assert simulator.high_range is False
            assert simulator.target_temperature == 26
            assert simulator.heat_mode == 1
            await hass.services.async_call(
                "climate",
                "set_preset_mode",
                {"entity_id": "climate.balboa_spa", "preset_mode": "high"},
                blocking=True,
            )
            assert simulator.target_temperature == 35
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_native_session_buttons_and_preferences_do_not_need_user_helpers(
    hass, socket_enabled
):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        try:
            await eventually(lambda: hass.states.get("sensor.balboa_spa_heating_session"))
            duration = "number.balboa_spa_bathing_duration"
            minimum = "number.balboa_spa_minimum_bathing_temperature"
            assert hass.states.get(duration) is not None
            assert float(hass.states.get(duration).state) == 120
            assert float(hass.states.get(minimum).state) == 36.5
            for entity, value in ((duration, 90), (minimum, 37)):
                await hass.services.async_call(
                    "number", "set_value", {"entity_id": entity, "value": value}, blocking=True
                )
            assert simulator.physical_commands == 0  # Preferences are not spa commands.
            await hass.services.async_call(
                "button", "press", {"entity_id": "button.balboa_spa_start_bathing"}, blocking=True
            )
            await eventually(lambda: entry.runtime_data.sessions.session.step == "active")
            session = entry.runtime_data.sessions.session
            assert session.end_time - session.start_time == pytest.approx(5400, abs=1)
            assert session.minimum == 37
            assert simulator.target_temperature == 38  # Higher High remains unchanged.
            for name, seconds in (("extend_bathing", 1800), ("reduce_bathing", -1800)):
                old_end = entry.runtime_data.sessions.session.end_time
                await hass.services.async_call(
                    "button", "press", {"entity_id": f"button.balboa_spa_{name}"}, blocking=True
                )
                assert entry.runtime_data.sessions.session.end_time == old_end + seconds
            await hass.services.async_call(
                "button", "press", {"entity_id": "button.balboa_spa_end_bathing"}, blocking=True
            )
            await eventually(lambda: entry.runtime_data.sessions.session is None)
            with pytest.raises(vol.Invalid):
                await action(hass, entry, "abandon_heating_session", confirm=False)
            await action(hass, entry, "abandon_heating_session", confirm=True)
            assert await hass.config_entries.async_unload(entry.entry_id)
            assert await hass.config_entries.async_setup(entry.entry_id)
            await eventually(lambda: hass.states.get(duration).state != "unavailable")
            assert float(hass.states.get(duration).state) == 90
            assert float(hass.states.get(minimum).state) == 37
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
