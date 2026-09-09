"""Supplemental status and historical faults stay honest about physical meaning."""

from tools.simulator.server import Simulator

from .test_lifecycle import eventually
from .test_sessions import setup_spa


async def test_named_pump_accepts_forced_circulation_without_false_timeout(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        simulator.pump1_forced_low = True
        simulator.pump_states[0] = 2
        entry = await setup_spa(hass, simulator)
        try:
            await eventually(
                lambda: (
                    hass.states.get("select.balboa_spa_pump_1_mode") is not None
                    and hass.states.get("select.balboa_spa_pump_1_mode").state == "jets"
                )
            )
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": "select.balboa_spa_pump_1_mode", "option": "circulation"},
                blocking=True,
            )
            assert hass.states.get("select.balboa_spa_pump_1_mode").state == "circulation"
            assert simulator.physical_commands == 1
            assert simulator.stats.connections == 1
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_circulation_and_latest_fault_are_native_observations(hass, socket_enabled):
    async with Simulator(
        port=0, interval=0.03, control_lab=True, scenario="metadata-change"
    ) as simulator:
        entry = await setup_spa(hass, simulator)
        try:
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            assert hass.states.get("binary_sensor.balboa_spa_circulation_pump_running") is not None
            assert (
                hass.states.get("binary_sensor.balboa_spa_circulation_pump_running").state == "on"
            )
            await eventually(lambda: entry.runtime_data.runtime.state.fault.count == 1)
            await eventually(
                lambda: (
                    hass.states.get("sensor.balboa_spa_latest_historical_log_entry").state
                    == "flow_failed"
                )
            )
            fault = hass.states.get("sensor.balboa_spa_latest_historical_log_entry")
            assert fault.attributes["historical"] is True
            assert fault.attributes["code"] == 17
            assert hass.states.get("sensor.balboa_spa_fault_log_entries").state == "1"
            assert hass.states.get("binary_sensor.balboa_spa_filter_cycle_1_running") is not None
            assert simulator.physical_commands == 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
