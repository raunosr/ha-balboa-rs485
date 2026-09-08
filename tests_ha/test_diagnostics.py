"""Diagnostics expose troubleshooting evidence without endpoint or secret leakage."""

import json

import pytest
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tools.simulator.server import Simulator

from .test_lifecycle import eventually


async def test_diagnostics_are_json_safe_redacted_and_include_verified_history(
    hass, socket_enabled
):
    from custom_components.balboa_rs485.diagnostics import async_get_config_entry_diagnostics

    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={
                "host": "127.0.0.1",
                "port": simulator.port,
                "protocol_mode": "classic-rs485",
                "token": "secret-for-redaction-test",
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
                {"entity_id": "climate.balboa_spa", "temperature": 35},
                blocking=True,
            )
            report = await async_get_config_entry_diagnostics(hass, entry)
            serialized = json.dumps(report)
            assert "127.0.0.1" not in serialized
            assert "secret-for-redaction-test" not in serialized
            assert report["connection"]["host"] == "**REDACTED**"
            assert report["connection"]["port"] == "**REDACTED**"
            assert report["connection"]["state"] == "READY"
            assert report["connection"]["rx_frames"] > 0
            assert report["device"]["model"] == "BP SIM"
            assert report["commands"]["window_count"] == 1
            assert report["commands"]["verified"] == 1
            assert report["commands"]["history"][0]["result"] == "VERIFIED"
            assert report["commands"]["mean_verification_latency"] > 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("channel_mode", [False, True])
async def test_device_info_and_stable_diagnostic_entities_use_observed_controller(
    hass, socket_enabled, channel_mode
):
    async with Simulator(
        port=0, interval=0.03, control_lab=True, channel_lab=channel_mode
    ) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={
                "host": "127.0.0.1",
                "port": simulator.port,
                "protocol_mode": "channel-rs485" if channel_mode else "classic-rs485",
            },
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        registry = dr.async_get(hass)

        def device():
            return registry.async_get_device(identifiers={("balboa_rs485", entry.entry_id)})

        try:
            await eventually(lambda: device() is not None and device().model == "BP SIM")
            assert device().sw_version == "1.2"
            expected = {
                "channel": "18" if channel_mode else "unknown",
                "crc_errors": "0",
                "recoveries": "0",
                "channel_allocations_remaining": "2" if channel_mode else "3",
            }
            await eventually(
                lambda: all(
                    hass.states.get(f"sensor.balboa_spa_{key}") is not None for key in expected
                )
            )
            assert {
                key: hass.states.get(f"sensor.balboa_spa_{key}").state for key in expected
            } == expected
            assert simulator.physical_commands == 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
