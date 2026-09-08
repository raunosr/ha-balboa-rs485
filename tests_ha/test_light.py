"""Native on/off light actions are observation-verified, never optimistic."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from tools.simulator.server import Simulator

from .test_lifecycle import eventually


async def test_native_light_on_and_off_are_verified(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "classic-rs485"},
            options={"enable_controls": True},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            await eventually(lambda: hass.states.get("light.balboa_spa_light_1") is not None)
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            for service, expected in [("turn_on", "on"), ("turn_off", "off")]:
                await hass.services.async_call(
                    "light", service, {"entity_id": "light.balboa_spa_light_1"}, blocking=True
                )
                assert hass.states.get("light.balboa_spa_light_1").state == expected
            assert simulator.physical_commands == 2
            assert simulator.light_states == [False, False]
            assert hass.states.get("light.balboa_spa_light_2") is None
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
