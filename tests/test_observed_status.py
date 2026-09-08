"""Useful read-only observations do not imply permission to control a spa."""

import asyncio

from balboa_rs485.protocol.frames import Frame, encode_frame
from balboa_rs485.transport.connection import SpaConnection
from balboa_rs485.transport.policy import Mode
from tools.simulator.server import load_status_fixture

from .helpers import loopback_server
from .test_connection import FAST


async def test_read_only_status_expires_despite_other_traffic_and_recovers_without_writes():
    resume = asyncio.Event()

    async def serve(reader, writer):
        writer.write(encode_frame(load_status_fixture()))
        await writer.drain()
        while not resume.is_set():
            writer.write(encode_frame(Frame(17, 191, 6)))
            await writer.drain()
            await asyncio.sleep(0.01)
        writer.write(encode_frame(load_status_fixture()))
        await writer.drain()
        await reader.read()

    async with loopback_server(serve) as port:
        connection = SpaConnection("127.0.0.1", port, mode=Mode.UNKNOWN_READ_ONLY, timing=FAST)
        assert connection.snapshot.observed_status is None
        async with connection:
            fresh = await connection.wait_for(lambda s: s.status is not None, timeout=2)
            assert fresh.observed_status.current_temperature == 27
            assert not fresh.available
            stale = await connection.wait_for(lambda s: s.health.status_stale, timeout=2)
            assert stale.status is not None  # Historical observation is retained internally.
            assert stale.observed_status is None
            assert stale.rx_frames > fresh.rx_frames
            resume.set()
            recovered = await connection.wait_for(
                lambda s: s.status_sequence > fresh.status_sequence, timeout=2
            )
            assert recovered.observed_status.current_temperature == 27
            assert recovered.epoch == fresh.epoch
            assert not recovered.available
            assert recovered.tx_frames == 0
        assert connection.snapshot.observed_status is None
