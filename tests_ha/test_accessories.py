"""Supported accessory controls use native entities and the same verified intent path."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tools.simulator.server import Simulator

from .test_lifecycle import eventually


@pytest.mark.parametrize(
    "platform,key,service,data,attribute,expected",
    [
        ("fan", "blower", "set_percentage", {"percentage": 100}, "blower", 2),
        ("switch", "aux_1", "turn_on", {}, "aux_states", [True, False]),
        ("switch", "aux_2", "turn_on", {}, "aux_states", [False, True]),
        ("switch", "mister", "turn_on", {}, "mister", True),
    ],
)
async def test_supported_accessory_native_action_is_verified(
    hass, socket_enabled, platform, key, service, data, attribute, expected
):
    async with Simulator(
        port=0, interval=0.03, control_lab=True, scenario="accessories"
    ) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "classic-rs485"},
            options={"enable_controls": True},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        entity_id = f"{platform}.balboa_spa_{key}"
        try:
            await eventually(lambda: hass.states.get(entity_id) is not None)
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            await hass.services.async_call(
                platform, service, {"entity_id": entity_id, **data}, blocking=True
            )
            assert hass.states.get(entity_id).state == "on"
            assert getattr(simulator, attribute) == expected
            await hass.services.async_call(
                platform, "turn_off", {"entity_id": entity_id}, blocking=True
            )
            assert hass.states.get(entity_id).state == "off"
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
