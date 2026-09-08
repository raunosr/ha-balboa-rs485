"""Deadlines, EOF and cancellation are exercised without hardware."""

import asyncio

import pytest

from balboa_rs485.protocol.frames import Frame, encode_frame
from tools.simulator.server import Simulator
from tools.smoke_client.client import observe

from .helpers import loopback_server


@pytest.mark.parametrize(
    "kwargs",
    [
        {"port": 0},
        {"frame_limit": -1},
        {"timeout": 0},
        {"timeout": float("nan")},
        {"timeout": float("inf")},
    ],
)
async def test_invalid_smoke_policy_is_rejected_before_connect(kwargs: dict) -> None:
    options = {"port": 8899, **kwargs}
    with pytest.raises(ValueError):
        await observe("127.0.0.1", **options)


@pytest.mark.parametrize("prefix", [b"", b"\x7e\x1d\xff\xaf", b"garbage"])
async def test_no_valid_frame_times_out_even_with_partial_or_garbage_traffic(prefix: bytes) -> None:
    async def serve(reader, writer):
        writer.write(prefix)
        await writer.drain()
        if prefix == b"garbage":
            while True:
                writer.write(b"junk")
                await writer.drain()
                await asyncio.sleep(0.005)
        await reader.read()

    output = []
    async with loopback_server(serve) as port:
        async with asyncio.timeout(2):
            with pytest.raises(TimeoutError):
                await observe("127.0.0.1", port, timeout=0.05, emit=output.append)
    assert any("TX 0" in line for line in output)
    assert not any("STATUS" in line for line in output)


async def test_eof_discards_incomplete_frame() -> None:
    async def serve(reader, writer):
        writer.write(b"\x7e\x1d\xff\xaf")
        await writer.drain()

    output = []
    async with loopback_server(serve) as port:
        report = await observe("127.0.0.1", port, timeout=2, emit=output.append)
    assert report.frames.discarded_bytes == 4
    assert report.frames.rx_frames == 0
    assert "EOF" in output


async def test_unknown_message_and_missing_temperatures_are_reported() -> None:
    async def serve(reader, writer):
        data = bytearray(24)
        data[2] = data[20] = 255
        writer.write(
            encode_frame(Frame(1, 2, 3, b"opaque"))
            + encode_frame(Frame(0xFF, 0xAF, 0x13, bytes(data)))
        )
        await writer.drain()

    output = []
    async with loopback_server(serve) as port:
        report = await observe("127.0.0.1", port, timeout=2, emit=output.append)
    assert report.unknown_message_types == 1
    assert any("Current unknown F -> Target unknown F" in line for line in output)


async def test_cancellation_closes_client_and_all_simulator_tasks() -> None:
    received = asyncio.Event()

    def emit(line):
        if line.startswith("READY"):
            received.set()

    async with Simulator(port=0) as simulator:
        task = asyncio.create_task(observe("127.0.0.1", simulator.port, emit=emit))
        await asyncio.wait_for(received.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert simulator.active_connections == 0


async def test_output_callback_failure_still_closes_connection() -> None:
    def emit(line):
        raise RuntimeError("output failed")

    async with Simulator(port=0) as simulator:
        with pytest.raises(RuntimeError, match="output failed"):
            await observe("127.0.0.1", simulator.port, emit=emit)
    assert simulator.active_connections == 0


async def test_simulator_double_start_is_rejected() -> None:
    async with Simulator(port=0) as simulator:
        with pytest.raises(RuntimeError, match="already started"):
            await simulator.__aenter__()


async def test_simulator_shutdown_closes_a_still_connected_client() -> None:
    writer = None
    try:
        async with asyncio.timeout(0.3):
            async with Simulator(port=0, interval=0.01) as simulator:
                reader, writer = await asyncio.open_connection("127.0.0.1", simulator.port)
                assert await reader.read(4096)
            # The client did not initiate shutdown; the server must close it.
            while await reader.read(4096):
                pass
            assert simulator.active_connections == 0
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()


async def test_simulator_does_not_execute_received_bytes() -> None:
    async with Simulator(port=0, interval=0.01) as simulator:
        reader, writer = await asyncio.open_connection("127.0.0.1", simulator.port)
        try:
            writer.write(b"pump1 high")
            await writer.drain()
            async with asyncio.timeout(2):
                while simulator.stats.received_bytes == 0:
                    assert await reader.read(4096)
        finally:
            writer.close()
            await writer.wait_closed()
        report = await observe("127.0.0.1", simulator.port, frame_limit=2, emit=lambda _: None)
        assert report.status_messages == 1
        assert simulator.stats.received_bytes == len(b"pump1 high")
