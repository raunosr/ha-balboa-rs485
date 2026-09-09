"""Configuration through Home Assistant's real public flow manager."""

import asyncio

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tools.simulator.server import Simulator

from .test_lifecycle import eventually


def test_experimental_direct_transport_is_not_a_home_assistant_mode():
    from custom_components.balboa_rs485.config_flow import CONNECTION_SCHEMA

    with pytest.raises(vol.Invalid):
        CONNECTION_SCHEMA(
            {"host": "127.0.0.1", "port": 8899, "protocol_mode": "direct-rs485-tcp-lab"}
        )


async def test_user_can_open_configuration_form(hass):
    result = await hass.config_entries.flow.async_init(
        "balboa_rs485", context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert "host" in result["data_schema"].schema


@pytest.mark.parametrize("source", ["user", "reconfigure"])
async def test_direct_risk_gate_precedes_validation_and_preserves_existing_entry(hass, source):
    from unittest.mock import AsyncMock, patch

    entry = MockConfigEntry(
        domain="balboa_rs485",
        data={"host": "example.invalid", "port": 8899, "protocol_mode": "auto"},
    )
    context = {"source": source}
    if source == "reconfigure":
        entry.add_to_hass(hass)
        context["entry_id"] = entry.entry_id
    with patch(
        "custom_components.balboa_rs485.config_flow.BalboaConfigFlow._validate_connection",
        new_callable=AsyncMock,
    ) as validate:
        result = await hass.config_entries.flow.async_init(
            "balboa_rs485",
            context=context,
            data={**entry.data, "protocol_mode": "direct-rs485-tcp"},
        )
        assert result["type"] == FlowResultType.FORM
        assert result["errors"] == {"accept_direct_bus_risk": "direct_risk_required"}
        validate.assert_not_called()
        assert entry.data["protocol_mode"] == "auto"


async def test_direct_reconfigure_preserves_owner_and_can_return_to_passive(hass, socket_enabled):
    from tests.helpers import loopback_server
    from tests.test_direct_tcp_lab import DirectPeer

    peer = DirectPeer()
    async with loopback_server(peer.serve) as port:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": port, "protocol_mode": "auto"},
            options={"enable_controls": False, "fallback_heating_rate": 2},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            result = await hass.config_entries.flow.async_init(
                "balboa_rs485",
                context={"source": "reconfigure", "entry_id": entry.entry_id},
                data={
                    **entry.data,
                    "protocol_mode": "direct-rs485-tcp",
                    "accept_direct_bus_risk": True,
                },
            )
            assert result["reason"] == "reconfigure_successful"
            await hass.async_block_till_done()
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            assert entry.runtime_data.runtime.connection.snapshot.available
            assert peer.max_active == 1 and peer.connections == 2
            assert peer.physical == peer.allocations == 0
            assert entry.options == {"enable_controls": False, "fallback_heating_rate": 2}
            result = await hass.config_entries.flow.async_init(
                "balboa_rs485",
                context={"source": "reconfigure", "entry_id": entry.entry_id},
                data={**entry.data, "protocol_mode": "auto"},
            )
            assert result["reason"] == "reconfigure_successful"
            await hass.async_block_till_done()
            assert entry.data["accept_direct_bus_risk"] is False
            assert peer.physical == peer.allocations == 0
            assert peer.max_active == 1
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_configuration_requires_observed_status_and_is_passive(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03) as simulator:
        result = await hass.config_entries.flow.async_init(
            "balboa_rs485",
            context={"source": config_entries.SOURCE_USER},
            data={"host": " 127.0.0.1 ", "port": simulator.port, "protocol_mode": "auto"},
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"]["host"] == "127.0.0.1"
        assert result["data"]["port"] == simulator.port
        assert simulator.stats.received_bytes == 0
        await hass.async_block_till_done()


async def test_duplicate_endpoint_is_rejected_before_opening_any_socket(hass):
    entry = MockConfigEntry(
        domain="balboa_rs485", data={"host": "127.0.0.1", "port": 8899, "protocol_mode": "auto"}
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        "balboa_rs485",
        context={"source": config_entries.SOURCE_USER},
        data={"host": " 127.0.0.1 ", "port": 8899, "protocol_mode": "channel-rs485"},
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_parallel_setup_flows_share_no_duplicate_validation_or_runtime(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03) as simulator:
        try:
            results = await asyncio.gather(
                *(
                    hass.config_entries.flow.async_init(
                        "balboa_rs485",
                        context={"source": config_entries.SOURCE_USER},
                        data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "auto"},
                    )
                    for _ in range(2)
                )
            )
            assert sorted(result["type"] for result in results) == [
                FlowResultType.ABORT,
                FlowResultType.CREATE_ENTRY,
            ]
            await hass.async_block_till_done()
            assert len(hass.config_entries.async_entries("balboa_rs485")) == 1
            assert simulator.stats.connections <= 2  # One passive check and one owned runtime.
            assert simulator.stats.received_bytes == 0
        finally:
            await hass.async_block_till_done()
            for entry in hass.config_entries.async_entries("balboa_rs485"):
                await hass.config_entries.async_unload(entry.entry_id)


async def test_reconfigure_unloaded_entry_schedules_setup_and_preserves_options(
    hass, socket_enabled
):
    async with Simulator(port=0, interval=0.03) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": 8899, "protocol_mode": "auto"},
            options={"enable_controls": False},
        )
        entry.add_to_hass(hass)
        try:
            result = await hass.config_entries.flow.async_init(
                "balboa_rs485",
                context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
                data={**entry.data, "port": simulator.port},
            )
            assert result["reason"] == "reconfigure_successful"
            await hass.async_block_till_done()
            assert entry.state.value == "loaded"
            assert entry.options == {"enable_controls": False}
            assert simulator.stats.connections == 2  # Passive check, then the owned runtime.
            assert simulator.active_connections == 1
            assert simulator.stats.received_bytes == 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_reconfigure_stale_owned_endpoint_returns_error_without_a_second_socket(
    hass, socket_enabled
):
    async with Simulator(port=0, interval=0.1, control_lab=True) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "classic-rs485"},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            simulator.scenario = "silent-zombie-socket"
            await entry.runtime_data.runtime.connection.wait_for(
                lambda snapshot: snapshot.health.status_stale
            )
            result = await hass.config_entries.flow.async_init(
                "balboa_rs485",
                context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
                data={**entry.data, "protocol_mode": "auto"},
            )
            assert result["type"] == FlowResultType.FORM
            assert result["errors"] == {"base": "cannot_connect"}
            assert simulator.stats.connections == 1
            assert entry.data["protocol_mode"] == "classic-rs485"
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
