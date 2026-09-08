"""HA setup retries must not reset the finite channel-allocation budget."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from tools.simulator.server import Simulator

from .test_lifecycle import eventually


async def test_channel_startup_without_status_retains_runtime_instead_of_retrying_setup(
    hass, socket_enabled
):
    # An incompatible channel gateway must keep the same runtime/budget even
    # when no standard status is ever received. It must not start a HA retry loop.
    async with Simulator(port=0, interval=0.03, scenario="unknown-protocol") as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "channel-rs485"},
        )
        entry.add_to_hass(hass)
        try:
            assert await hass.config_entries.async_setup(entry.entry_id)
            assert entry.state.value == "loaded"
            assert entry.runtime_data.runtime.connection.running
            assert hass.states.get("climate.balboa_spa").state == "unavailable"
            assert hass.states.get("sensor.balboa_spa_connection").state != "ready"
            assert simulator.physical_commands == 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
            await eventually(lambda: simulator.active_connections == 0)
