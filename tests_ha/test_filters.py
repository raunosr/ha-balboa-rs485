"""Four native times and Cycle 2 enable replace the old hour/minute sliders."""

from tools.simulator.server import Simulator

from .test_lifecycle import eventually
from .test_sessions import action, setup_spa


async def test_native_filter_times_and_compound_action_confirm_full_schedule(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        try:
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            assert hass.states.get("time.balboa_spa_filter_cycle_1_start") is not None
            assert hass.states.get("time.balboa_spa_filter_cycle_1_start").state == "08:00:00"
            assert hass.states.get("time.balboa_spa_filter_cycle_1_end").state == "10:00:00"
            before = simulator.filter_payload[4:]
            await action(hass, entry, "set_filter_cycle", cycle=1, start="22:00", end="02:00")
            await eventually(
                lambda: hass.states.get("time.balboa_spa_filter_cycle_1_end").state == "02:00:00"
            )
            assert simulator.filter_payload[4:] == before
            assert float(hass.states.get("sensor.balboa_spa_filter_cycle_1_duration").state) == 240
            await hass.services.async_call(
                "time",
                "set_value",
                {"entity_id": "time.balboa_spa_filter_cycle_1_start", "time": "21:00"},
                blocking=True,
            )
            assert simulator.filter_payload[:4] == bytes((21, 0, 4, 0))
            await hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": "switch.balboa_spa_filter_cycle_2_enabled"},
                blocking=True,
            )
            assert simulator.filter_payload[4] == 20
            assert simulator.physical_commands == 3
            assert simulator.stats.connections == 1
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
