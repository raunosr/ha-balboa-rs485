"""Real HA lifecycle and native entities against a real loopback spa."""

import asyncio

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tools.simulator.server import Simulator


async def eventually(predicate):
    async with asyncio.timeout(5):
        while not predicate():  # noqa: ASYNC110 -- bounded external TCP/HA observation in tests
            await asyncio.sleep(0.01)


async def test_entry_exposes_observed_climate_and_unload_closes_owned_socket(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "classic-rs485"},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await eventually(
            lambda: (
                (state := hass.states.get("climate.balboa_spa")) and state.state != "unavailable"
            )
        )
        state = hass.states.get("climate.balboa_spa")
        assert state.attributes["current_temperature"] == 27.0
        assert state.attributes["temperature"] == 38.0
        assert state.attributes["hvac_modes"] == ["heat"]
        assert simulator.active_connections == 1
        assert simulator.physical_commands == 0
        connection = entry.runtime_data.runtime.connection
        assert await hass.config_entries.async_unload(entry.entry_id)
        await eventually(lambda: simulator.active_connections == 0)
        assert not connection.running


async def test_reconfigure_moves_endpoint_but_preserves_entity_identity_and_options(
    hass, socket_enabled
):
    async with (
        Simulator(port=0, interval=0.03, control_lab=True) as old,
        Simulator(port=0, interval=0.03, control_lab=True) as new,
    ):
        new.target_temperature = 36
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": old.port, "protocol_mode": "classic-rs485"},
            options={"enable_controls": True},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await eventually(lambda: hass.states.get("climate.balboa_spa") is not None)
        registry = er.async_get(hass)
        before = registry.async_get("climate.balboa_spa")
        try:
            flow = await hass.config_entries.flow.async_init(
                "balboa_rs485",
                context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
            )
            assert flow["type"] == FlowResultType.FORM
            result = await hass.config_entries.flow.async_configure(
                flow["flow_id"],
                user_input={
                    "host": "127.0.0.1",
                    "port": new.port,
                    "protocol_mode": "classic-rs485",
                },
            )
            assert result["type"] == FlowResultType.ABORT
            assert result["reason"] == "reconfigure_successful"
            await hass.async_block_till_done()
            await eventually(
                lambda: (
                    (state := hass.states.get("climate.balboa_spa"))
                    and state.attributes.get("temperature") == 36
                )
            )
            await eventually(lambda: old.active_connections == 0)
            assert new.active_connections == 1
            after = registry.async_get("climate.balboa_spa")
            assert (after.entity_id, after.unique_id, after.device_id) == (
                before.entity_id,
                before.unique_id,
                before.device_id,
            )
            assert entry.options["enable_controls"] is True
            assert old.physical_commands == new.physical_commands == 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_unchanged_reconfiguration_reuses_owned_socket(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "classic-rs485"},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            result = await hass.config_entries.flow.async_init(
                "balboa_rs485",
                context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
                data=dict(entry.data),
            )
            assert result["reason"] == "reconfigure_successful"
            await hass.async_block_till_done()
            assert simulator.stats.connections == 1
            assert simulator.physical_commands == 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
