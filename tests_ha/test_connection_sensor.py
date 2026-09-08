"""Connection diagnostics stay visible when physical controls are unavailable."""

import asyncio
from dataclasses import replace

from pytest_homeassistant_custom_component.common import MockConfigEntry

from balboa_rs485.protocol.frames import Frame, FrameParser, encode_frame
from tests.helpers import loopback_server
from tools.simulator.server import Simulator, load_status_fixture

from .test_lifecycle import eventually


async def test_passive_connection_reports_why_spa_is_not_ready(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "auto"},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            await eventually(lambda: hass.states.get("sensor.balboa_spa_connection") is not None)
            state = hass.states.get("sensor.balboa_spa_connection")
            assert state.state == "detecting_protocol"
            assert state.attributes["protocol_mode"] == "unknown-read-only"
            assert state.attributes["controls_enabled"] is False
            assert state.attributes["observations_available"] is True
            assert state.attributes["observed_current_temperature"] == 27
            assert state.attributes["observed_target_temperature"] == 38
            assert state.attributes["observed_temperature_unit"] == "C"
            assert hass.states.get("climate.balboa_spa").state == "unavailable"
            assert simulator.stats.received_bytes == 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_assignment_timeout_reaches_ha_even_without_new_status(hass, socket_enabled):
    requests = []

    async def serve(reader, writer):
        writer.write(encode_frame(load_status_fixture()) + encode_frame(Frame(254, 191, 0)))
        await writer.drain()
        parser = FrameParser()
        while not requests:
            requests.extend(parser.feed(await reader.read(4096)))
        while True:
            writer.write(encode_frame(Frame(17, 191, 6)))
            await writer.drain()
            try:
                data = await asyncio.wait_for(reader.read(4096), timeout=0.03)
            except TimeoutError:
                continue
            if not data:
                return
            requests.extend(parser.feed(data))

    async with loopback_server(serve) as port:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": port, "protocol_mode": "channel-rs485"},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            await eventually(
                lambda: (
                    hass.states.get("sensor.balboa_spa_connection") is not None
                    and hass.states.get("sensor.balboa_spa_connection").attributes[
                        "channel_failure"
                    ]
                )
            )
            state = hass.states.get("sensor.balboa_spa_connection")
            assert "timed out" in state.attributes["channel_failure"]
            assert state.attributes["controls_enabled"] is False
            assert hass.states.get("climate.balboa_spa").state == "unavailable"
            assert len(requests) == 1
            from custom_components.balboa_rs485.diagnostics import (
                async_get_config_entry_diagnostics,
            )

            diagnostics = await async_get_config_entry_diagnostics(hass, entry)
            assert diagnostics["connection"]["channel_assignment"] == {
                "attempts": 1,
                "limit": 3,
                "requested": True,
                "responses": 0,
                "correlated": 0,
                "reply_opportunities": 0,
                "pending": False,
                "ack_on_cts": False,
            }
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_other_valid_traffic_cannot_keep_stale_read_only_values_visible(hass, socket_enabled):
    async with Simulator(port=0, interval=0.01, transport_lab=True) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={
                "host": "127.0.0.1",
                "port": simulator.port,
                "protocol_mode": "unknown-read-only",
            },
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            connection = entry.runtime_data.runtime.connection
            connection.timing = replace(
                connection.timing, degrade_after=0.1, stale_after=0.2, recover_after=0.5
            )
            await eventually(
                lambda: hass.states.get("sensor.balboa_spa_connection").attributes[
                    "observations_available"
                ]
            )
            epoch = connection.snapshot.epoch
            simulator.scenario = "unknown-protocol"
            await eventually(
                lambda: hass.states.get("sensor.balboa_spa_connection").attributes["status_stale"]
            )
            stale = hass.states.get("sensor.balboa_spa_connection")
            assert stale.state == "detecting_protocol"
            assert stale.attributes["observations_available"] is False
            for field in (
                "observed_current_temperature",
                "observed_target_temperature",
                "observed_temperature_unit",
                "observed_heat_state",
            ):
                assert stale.attributes[field] is None
            simulator.scenario = "normal"
            await eventually(
                lambda: hass.states.get("sensor.balboa_spa_connection").attributes[
                    "observations_available"
                ]
            )
            assert connection.snapshot.epoch == epoch
            assert connection.snapshot.tx_frames == 0
            assert hass.states.get("climate.balboa_spa").state == "unavailable"
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
