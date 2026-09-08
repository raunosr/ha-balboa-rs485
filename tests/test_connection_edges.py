"""Lifecycle boundaries and adversarial peers, not internal implementation mocks."""

import asyncio
from dataclasses import replace

import pytest

from balboa_rs485.protocol.frames import Frame, encode_frame
from balboa_rs485.transport.connection import SpaConnection
from balboa_rs485.transport.policy import Mode
from tools.simulator.server import Simulator, load_status_fixture
from tools.smoke_client.transport import inspect_transport

from .helpers import loopback_server
from .test_connection import FAST


async def test_shutdown_revokes_availability_before_awaiting_socket_close(monkeypatch):
    opened = asyncio.open_connection
    closing = asyncio.Event()
    release = asyncio.Event()

    async def connect(*args, **kwargs):
        reader, writer = await opened(*args, **kwargs)
        wait_closed = writer.wait_closed

        async def delayed_close():
            closing.set()
            await release.wait()
            await wait_closed()

        writer.wait_closed = delayed_close
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", connect)
    async with Simulator(port=0, interval=0.03, transport_lab=True) as simulator:
        connection = SpaConnection(
            "127.0.0.1", simulator.port, mode=Mode.CLASSIC_RS485, timing=FAST
        )
        await connection.__aenter__()
        await connection.wait_for(lambda s: s.available, timeout=2)
        stopping = asyncio.create_task(connection.__aexit__(None, None, None))
        try:
            await asyncio.wait_for(closing.wait(), 1)
            assert not connection.snapshot.available
            assert connection.snapshot.configuration is None
        finally:
            release.set()
            await stopping
        assert not connection.running


@pytest.mark.parametrize("error", [TimeoutError, ConnectionError])
async def test_failed_close_is_bounded_and_aborts_transport(monkeypatch, error):
    opened = asyncio.open_connection
    aborted = []

    async def connect(*args, **kwargs):
        reader, writer = await opened(*args, **kwargs)
        abort = writer.transport.abort

        async def fail_close():
            raise error("injected close failure")

        def record_abort():
            aborted.append(True)
            abort()

        writer.wait_closed = fail_close
        writer.transport.abort = record_abort
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", connect)
    async with Simulator(port=0, interval=0.03) as simulator:
        async with SpaConnection("127.0.0.1", simulator.port, timing=FAST) as connection:
            await connection.wait_for(lambda s: s.rx_frames > 0, timeout=2)
    assert aborted


async def test_unsolicited_or_malformed_config_cannot_complete_sync():
    from .test_configuration import CAPS, INFO

    async def peer(reader, writer):
        # Valid responses before any request, then only malformed information responses.
        writer.write(encode_frame(INFO) + encode_frame(CAPS) + encode_frame(load_status_fixture()))
        await writer.drain()
        while data := await reader.read(4096):
            assert data
            writer.write(
                encode_frame(Frame(10, 191, 36, b"bad")) + encode_frame(load_status_fixture())
            )
            await writer.drain()

    async with loopback_server(peer) as port:
        async with SpaConnection("127.0.0.1", port, mode=Mode.BWA_TCP, timing=FAST) as connection:
            observed = await connection.wait_for(lambda s: s.invalid_messages >= 1, timeout=2)
            assert not observed.available and observed.configuration is None


async def test_sync_deadline_applies_when_peer_keeps_sending_valid_traffic():
    timing = replace(FAST, sync_timeout=0.12, query_timeout=0.4)
    async with Simulator(port=0, interval=0.03, scenario="missing-configuration") as simulator:
        async with SpaConnection(
            "127.0.0.1", simulator.port, mode=Mode.CLASSIC_RS485, timing=timing
        ) as connection:
            result = await connection.wait_for(lambda s: s.recoveries > 0, timeout=2)
            assert result.last_error == "configuration synchronization deadline"


async def test_double_start_rejected_and_waiter_cancellation_does_not_stop_connection():
    async with Simulator(port=0) as simulator:
        async with SpaConnection("127.0.0.1", simulator.port, timing=FAST) as connection:
            with pytest.raises(RuntimeError, match="already started"):
                await connection.__aenter__()
            with pytest.raises(TimeoutError):
                await connection.wait_for(lambda s: s.available, timeout=0.03)
            assert connection.running


@pytest.mark.parametrize("host,port", [("", 8899), ("a", 0), ("a", 65536)])
def test_invalid_connection_configuration(host, port):
    with pytest.raises(ValueError):
        SpaConnection(host, port)


@pytest.mark.parametrize("duration", [0, float("nan"), -1])
async def test_transport_smoke_rejects_invalid_duration(duration):
    with pytest.raises(ValueError):
        await inspect_transport("127.0.0.1", 1, duration=duration)


async def test_sustained_health_resets_backoff_once_and_records_ready_intervals():
    timing = replace(FAST, healthy_reset=0.1)
    async with Simulator(port=0, interval=0.03, transport_lab=True) as simulator:
        async with SpaConnection(
            "127.0.0.1", simulator.port, mode=Mode.CLASSIC_RS485, timing=timing
        ) as connection:
            snapshot = await connection.wait_for(lambda s: s.rx_frames >= 24, timeout=2)
            assert snapshot.available
            assert snapshot.health.ready_interval_mean > 0
            assert snapshot.health.ready_interval_max >= snapshot.health.ready_interval_mean
            assert not snapshot.health.ready_missing
            assert len([e for e in connection.events if e.kind == "backoff_reset"]) == 1


async def test_cts_followed_by_unframed_traffic_is_not_a_transmission_opportunity():
    async def peer(reader, writer):
        writer.write(
            encode_frame(load_status_fixture()) + encode_frame(Frame(16, 191, 6)) + b"JUNK"
        )
        await writer.drain()
        await reader.read()

    async with loopback_server(peer) as port:
        async with SpaConnection(
            "127.0.0.1", port, mode=Mode.CLASSIC_RS485, timing=FAST
        ) as connection:
            snapshot = await connection.wait_for(lambda s: s.rx_frames >= 2, timeout=2)
            assert snapshot.tx_frames == 0
