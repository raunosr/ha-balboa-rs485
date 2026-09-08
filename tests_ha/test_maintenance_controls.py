"""Native maintenance controls leave fault history and safety interlocks intact."""

from tools.simulator.server import Simulator

from .test_lifecycle import eventually
from .test_sessions import setup_spa


async def test_native_hold_normal_soak_and_reminder_acknowledgement(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        try:
            assert hass.states.get("switch.balboa_spa_hold") is not None
            await hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": "switch.balboa_spa_hold"},
                blocking=True,
            )
            assert simulator.hold
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": "button.balboa_spa_normal_operation"},
                blocking=True,
            )
            assert not simulator.hold
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": "select.balboa_spa_pump_1_mode", "option": "jets"},
                blocking=True,
            )
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": "button.balboa_spa_soak"},
                blocking=True,
            )
            assert not any(simulator.pump_states)
            simulator.reminder_code = 4
            await eventually(lambda: entry.runtime_data.runtime.state.status.reminder_code == 4)
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": "button.balboa_spa_acknowledge_reminder"},
                blocking=True,
            )
            assert entry.runtime_data.runtime.state.status.reminder == "none"
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
