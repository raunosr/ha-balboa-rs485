"""Reconnection discovers/removes capabilities without replacing entity identity."""

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tools.simulator.server import Simulator

from .test_lifecycle import eventually


async def test_accessory_appears_then_becomes_unavailable_after_configuration_change(
    hass, socket_enabled
):
    entry = None
    try:
        async with Simulator(port=0, interval=0.03, control_lab=True) as first:
            port = first.port
            entry = MockConfigEntry(
                domain="balboa_rs485",
                title="Balboa Spa",
                data={"host": "127.0.0.1", "port": port, "protocol_mode": "classic-rs485"},
            )
            entry.add_to_hass(hass)
            assert await hass.config_entries.async_setup(entry.entry_id)
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            owner = entry.runtime_data
            registry = er.async_get(hass)
            pump_before = registry.async_get("fan.balboa_spa_pump_1")
            assert hass.states.get("light.balboa_spa_light_2") is None

        async with Simulator(port=port, interval=0.03, control_lab=True, scenario="accessories"):
            await eventually(lambda: hass.states.get("light.balboa_spa_light_2") is not None)
            await eventually(lambda: hass.states.get("light.balboa_spa_light_2").state == "off")
            light_before = registry.async_get("light.balboa_spa_light_2")
            assert entry.runtime_data is owner
            assert registry.async_get("fan.balboa_spa_pump_1").unique_id == pump_before.unique_id

        async with Simulator(port=port, interval=0.03, control_lab=True):
            await eventually(lambda: owner.runtime.connection.snapshot.epoch >= 3)
            await eventually(lambda: hass.states.get("climate.balboa_spa").state == "heat")
            assert hass.states.get("light.balboa_spa_light_2").state == "unavailable"
            assert (
                registry.async_get("light.balboa_spa_light_2").unique_id == light_before.unique_id
            )
            assert registry.async_get("light.balboa_spa_light_2").device_id == pump_before.device_id
            assert entry.runtime_data is owner
    finally:
        if entry is not None:
            await hass.config_entries.async_unload(entry.entry_id)
