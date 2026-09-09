"""Routine maintenance and historical log entries are not active safety faults."""

from dataclasses import replace

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.balboa_rs485.diagnostics import async_get_config_entry_diagnostics
from tools.simulator.server import Simulator

from .test_lifecycle import eventually
from .test_sessions import setup_spa


@pytest.mark.parametrize("mode", ["classic-rs485", "direct-rs485-tcp"])
async def test_filter_replacement_reminder_allows_verified_native_setpoint(
    hass, socket_enabled, mode
):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        simulator.reminder_code = 3
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={
                "host": "127.0.0.1",
                "port": simulator.port,
                "protocol_mode": mode,
                "accept_direct_bus_risk": True,
            },
            options={"enable_controls": True},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            await hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": "climate.balboa_spa", "temperature": 37.5},
                blocking=True,
            )
            assert hass.states.get("climate.balboa_spa").attributes["temperature"] == 37.5
            assert hass.states.get("sensor.balboa_spa_reminder").state == "change_filter"
            assert hass.states.get("binary_sensor.balboa_spa_priming").state == "off"
            assert simulator.physical_commands == 1
            assert simulator.reminder_code == 3
            report = await async_get_config_entry_diagnostics(hass, entry)
            assert report["controls_safe"]
            assert report["controls_blocked_reason"] is None
            assert report["observations"]["passive_status"]["priming"] is False
            assert report["observations"]["passive_status"]["reminder"] == "change_filter"
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_historical_priming_does_not_reappear_as_new_event_on_connection_gap(
    hass, socket_enabled
):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        simulator.fault_payload = bytes((1, 0, 19, 2, 12, 0, 0, 0, 0, 0))
        entry = await setup_spa(hass, simulator)
        try:
            fault_id = "sensor.balboa_spa_latest_fault"
            await eventually(lambda: hass.states.get(fault_id).state == "priming_mode")
            historical = hass.states.get(fault_id)
            assert historical.attributes["historical"]
            assert hass.states.get("binary_sensor.balboa_spa_priming").state == "off"
            connection = entry.runtime_data.runtime.connection
            connection.timing = replace(
                connection.timing, degrade_after=0.1, stale_after=0.2, recover_after=0.5
            )
            simulator.scenario = "silent-zombie-socket"
            await eventually(lambda: hass.states.get("climate.balboa_spa").state == "unavailable")
            assert hass.states.get(fault_id).state == "priming_mode"
            assert hass.states.get(fault_id).last_changed == historical.last_changed
            simulator.scenario = "normal"
            await eventually(lambda: hass.states.get("climate.balboa_spa").state != "unavailable")
            assert hass.states.get(fault_id).last_changed == historical.last_changed
            assert hass.states.get("binary_sensor.balboa_spa_priming").state == "off"
            assert simulator.physical_commands == 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
