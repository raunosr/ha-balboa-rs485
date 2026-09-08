"""Exercise the real parser over actual loopback TCP sockets."""

import asyncio

import pytest

from balboa_rs485.protocol.frames import FrameParser
from balboa_rs485.protocol.messages import ReadyMessage, StatusMessage, decode_message
from tools.simulator.server import Simulator
from tools.smoke_client.client import observe


async def test_simulator_streams_ready_and_status() -> None:
    async with Simulator(port=0, interval=0.01) as simulator:
        reader, writer = await asyncio.open_connection("127.0.0.1", simulator.port)
        parser = FrameParser()
        frames = []
        try:
            async with asyncio.timeout(2):
                while len(frames) < 2:
                    frames.extend(parser.feed(await reader.read(4096)))
        finally:
            writer.close()
            await writer.wait_closed()
    ready, status = map(decode_message, frames[:2])
    assert isinstance(ready, ReadyMessage)
    assert isinstance(status, StatusMessage)
    assert status.current_temperature == 27.0
    assert status.target_temperature == 38.0
    assert simulator.active_connections == 0


@pytest.mark.parametrize("scenario", ["normal", "bad-crc", "partial-frame", "garbage-before-frame"])
async def test_smoke_observes_each_scenario_without_transmitting(scenario: str) -> None:
    output = []
    async with Simulator(
        port=0, interval=0.01, scenario=scenario, fragment_delay=0.001
    ) as simulator:
        report = await observe(
            "127.0.0.1", simulator.port, frame_limit=4, timeout=2, emit=output.append
        )
        assert simulator.stats.received_bytes == 0
    assert report.ready_messages == 2
    assert report.status_messages == 2
    assert report.tx_frames == 0
    assert any("27.0 C" in line and "38.0 C" in line for line in output)
    assert any("CONFIG pending" in line for line in output)
    if scenario == "bad-crc":
        assert report.frames.crc_errors == 2
    if scenario == "garbage-before-frame":
        assert report.frames.discarded_bytes > 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"scenario": "typo"},
        {"interval": 0},
        {"interval": float("nan")},
        {"fragment_delay": -1},
        {"fragment_delay": float("inf")},
        {"port": 65536},
    ],
)
def test_simulator_rejects_invalid_policy(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        Simulator(**kwargs)


async def test_malformed_message_obeys_frame_limit() -> None:
    from balboa_rs485.protocol.frames import Frame, encode_frame

    async def serve(reader, writer):
        writer.write(
            encode_frame(Frame(0x10, 0xBF, 0x06, b"invalid"))
            + encode_frame(Frame(0x10, 0xBF, 0x06))
        )
        await writer.drain()
        await reader.read()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    output = []
    try:
        report = await observe(
            "127.0.0.1",
            server.sockets[0].getsockname()[1],
            frame_limit=1,
            timeout=0.2,
            emit=output.append,
        )
    finally:
        server.close()
        await server.wait_closed()
    assert report.invalid_messages == 1
    assert report.ready_messages == 0


async def test_passive_observer_displays_known_configuration_without_querying():
    from balboa_rs485.protocol.frames import encode_frame

    from .helpers import loopback_server
    from .test_configuration import CAPS, INFO

    received = []

    async def peer(reader, writer):
        writer.write(encode_frame(INFO) + encode_frame(CAPS))
        await writer.drain()
        received.append(await reader.read())

    output = []
    async with loopback_server(peer) as port:
        report = await observe("127.0.0.1", port, frame_limit=2, emit=output.append)
    assert report.configuration_messages == 2 and report.unknown_message_types == 0
    assert report.tx_frames == 0
    assert any("OBSERVED CONFIG" in line for line in output)
