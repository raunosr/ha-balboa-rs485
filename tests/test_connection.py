"""Exercise the runtime over real TCP, observing only its public snapshot/events."""

import asyncio
from dataclasses import replace

import pytest

from balboa_rs485.protocol.configuration import Query, encode_query
from balboa_rs485.protocol.frames import FrameParser, encode_frame
from balboa_rs485.transport.connection import ConnectionState, SpaConnection
from balboa_rs485.transport.policy import Mode
from balboa_rs485.transport.timing import Timing
from tools.simulator.server import Simulator, load_status_fixture

from .helpers import loopback_server
from .test_configuration import CAPS, INFO

FAST = Timing(
    connect=0.3,
    first_frame=0.2,
    degrade_after=0.15,
    stale_after=0.3,
    recover_after=0.5,
    sync_timeout=0.8,
    query_timeout=0.15,
    tick=0.01,
    backoff_initial=0.03,
    backoff_max=0.1,
    close=0.2,
    healthy_reset=0.25,
)


async def test_bwa_becomes_ready_only_after_correlated_configuration_and_fresh_status():
    allow_frames = asyncio.Event()
    allow_status = asyncio.Event()
    queries = []

    async def serve(reader, writer):
        await allow_frames.wait()
        writer.write(encode_frame(load_status_fixture()))
        await writer.drain()
        parser = FrameParser()
        while len(queries) < 2:
            for frame in parser.feed(await reader.read(4096)):
                queries.append(frame)
                reply = INFO if frame == encode_query(Query.INFORMATION) else CAPS
                writer.write(encode_frame(reply))
                await writer.drain()
        await allow_status.wait()
        writer.write(encode_frame(load_status_fixture()))
        await writer.drain()
        await reader.read()

    async with loopback_server(serve) as port:
        connection = SpaConnection("127.0.0.1", port, mode=Mode.BWA_TCP)
        async with connection:
            initial = await connection.wait_for(
                lambda s: s.state == ConnectionState.WAITING_FOR_FRAME, timeout=2
            )
            assert not initial.available and initial.configuration is None
            allow_frames.set()
            syncing = await connection.wait_for(lambda s: s.configuration is not None, timeout=2)
            assert not syncing.available
            allow_status.set()
            ready = await connection.wait_for(lambda s: s.available, timeout=2)
            assert ready.state == ConnectionState.READY
            assert ready.status.current_temperature == 27
            assert ready.configuration.information.model == "BP SIM"
            assert ready.configuration_revision == 1
            assert ready.tx_frames == 2 and ready.epoch == 1
            assert queries == [encode_query(Query.INFORMATION), encode_query(Query.CAPABILITIES)]
    assert connection.snapshot.state == ConnectionState.DISCONNECTED
    assert not connection.snapshot.available
    assert not connection.running


async def test_junk_cannot_extend_first_valid_frame_deadline_and_old_socket_closes():
    closed = asyncio.Event()
    connections = 0

    async def serve(reader, writer):
        nonlocal connections
        connections += 1
        try:
            while True:
                writer.write(b"junk\x7e\x7d")
                await writer.drain()
                try:
                    if not await asyncio.wait_for(reader.read(1), 0.02):
                        return
                except TimeoutError:
                    pass
        finally:
            closed.set()

    async with loopback_server(serve) as port:
        async with SpaConnection("127.0.0.1", port, timing=FAST) as connection:
            result = await connection.wait_for(lambda s: s.epoch >= 2, timeout=2)
            assert not result.available and result.tx_frames == 0
            assert closed.is_set() and connections >= 2
            assert any(
                e.kind == "recovery" and "first valid frame" in e.detail for e in connection.events
            )


async def test_classic_sync_uses_one_query_per_cts_cycle():
    async with Simulator(port=0, interval=0.03, transport_lab=True) as simulator:
        async with SpaConnection(
            "127.0.0.1", simulator.port, mode=Mode.CLASSIC_RS485, timing=FAST
        ) as connection:
            ready = await connection.wait_for(lambda s: s.available, timeout=3)
            assert ready.tx_frames == 2
            assert ready.configuration is not None
            assert simulator.stats.rejected_queries == 0
            records = tuple(simulator.query_records)
            assert len(records) == 2
            assert records[0].cycle < records[1].cycle
            assert records[0].connection == records[1].connection == ready.epoch


@pytest.mark.parametrize("scenario", ["connection-reset", "elfin-reboot"])
async def test_abrupt_disconnect_drops_socket_fragments_and_resynchronizes(scenario):
    async with Simulator(port=0, interval=0.03, transport_lab=True, scenario=scenario) as simulator:
        async with SpaConnection(
            "127.0.0.1", simulator.port, mode=Mode.CLASSIC_RS485, timing=FAST
        ) as connection:
            first = await connection.wait_for(lambda s: s.available, timeout=2)
            second = await connection.wait_for(lambda s: s.available and s.epoch == 2, timeout=3)
            assert second.tx_frames == 4
            assert second.configuration_revision == first.configuration_revision
            assert second.recoveries == 1
            assert simulator.active_connections == 1
            if scenario == "elfin-reboot":
                assert second.discarded_bytes > 0


async def test_missing_ready_never_transmits_despite_continuing_valid_status():
    async with Simulator(port=0, interval=0.03, scenario="missing-ready") as simulator:
        async with SpaConnection(
            "127.0.0.1", simulator.port, mode=Mode.CLASSIC_RS485, timing=FAST
        ) as connection:
            degraded = await connection.wait_for(
                lambda s: s.state == ConnectionState.DEGRADED, timeout=2
            )
            assert degraded.health.last_status is not None and degraded.health.last_ready is None
            recovered = await connection.wait_for(lambda s: s.epoch == 2, timeout=2)
            assert not recovered.available and recovered.tx_frames == 0
            assert simulator.stats.received_bytes == 0


async def test_silent_zombie_degrades_goes_stale_and_recovers_with_a_new_configuration():
    async with Simulator(
        port=0, interval=0.03, transport_lab=True, scenario="silent-zombie-socket"
    ) as simulator:
        async with SpaConnection(
            "127.0.0.1", simulator.port, mode=Mode.CLASSIC_RS485, timing=FAST, jitter=lambda: 0.5
        ) as connection:
            first = await connection.wait_for(lambda s: s.available, timeout=2)
            degraded = await connection.wait_for(
                lambda s: s.state == ConnectionState.DEGRADED, timeout=2
            )
            assert not degraded.available
            assert degraded.health.last_valid_frame is not None
            stale = await connection.wait_for(lambda s: s.health.status_stale, timeout=2)
            assert not stale.available
            recovered = await connection.wait_for(lambda s: s.epoch == 2 and s.available, timeout=3)
            assert recovered.configuration_revision == first.configuration_revision
            assert recovered.configuration.signature == first.configuration.signature
            assert recovered.tx_frames == 4
            assert len({r.connection for r in simulator.query_records}) == 2
            assert any(e.kind == "recovery" for e in connection.events)


async def test_configuration_query_retries_are_bounded_and_restart_from_information():
    async with Simulator(
        port=0, interval=0.03, transport_lab=True, scenario="missing-configuration"
    ) as simulator:
        async with SpaConnection(
            "127.0.0.1", simulator.port, mode=Mode.CLASSIC_RS485, timing=FAST
        ) as connection:
            await connection.wait_for(lambda s: s.epoch >= 2 and s.tx_frames >= 4, timeout=3)
            first_epoch = [r for r in simulator.query_records if r.connection == 1]
            assert len(first_epoch) == FAST.query_attempts
            assert all(r.frame == encode_query(Query.INFORMATION) for r in first_epoch)
            assert not connection.snapshot.available
            assert any(
                e.kind == "recovery" and "query attempts" in e.detail for e in connection.events
            )


async def test_periodic_refresh_detects_configuration_change_without_mutating_old_snapshot():
    timing = replace(FAST, refresh_interval=0.2)
    async with Simulator(
        port=0, interval=0.03, transport_lab=True, scenario="configuration-change"
    ) as simulator:
        async with SpaConnection(
            "127.0.0.1", simulator.port, mode=Mode.CLASSIC_RS485, timing=timing
        ) as connection:
            first = await connection.wait_for(lambda s: s.available, timeout=2)
            changed = await connection.wait_for(
                lambda s: s.available and s.configuration_revision == 2, timeout=3
            )
            assert first.configuration.information.model == "BP SIM"
            assert changed.configuration.information.model == "BP SIM2"
            assert first.configuration.signature != changed.configuration.signature
            again = await connection.wait_for(lambda s: s.available and s.tx_frames >= 6, timeout=3)
            assert again.configuration_revision == 2
            assert again.epoch == first.epoch


@pytest.mark.parametrize(
    "scenario", ["bad-crc", "partial-frame", "garbage-before-frame", "slow-network"]
)
async def test_transport_recovers_framing_and_handles_network_latency(scenario):
    timing = replace(
        FAST,
        first_frame=0.6,
        degrade_after=0.4,
        stale_after=0.7,
        recover_after=1,
        sync_timeout=2,
        query_timeout=0.5,
    )
    async with Simulator(
        port=0, interval=0.03, fragment_delay=0.001, transport_lab=True, scenario=scenario
    ) as simulator:
        async with SpaConnection(
            "127.0.0.1", simulator.port, mode=Mode.CLASSIC_RS485, timing=timing
        ) as connection:
            ready = await connection.wait_for(lambda s: s.available, timeout=3)
            assert ready.epoch == 1 and ready.tx_frames == 2
            assert ready.rx_frames >= 6
            assert ready.health.frames_per_second > 0
            if scenario == "bad-crc":
                assert ready.crc_errors >= 2
            if scenario == "garbage-before-frame":
                assert ready.discarded_bytes > 0
            assert simulator.stats.rejected_queries == 0


@pytest.mark.parametrize(
    "mode,scenario,candidate",
    [
        (Mode.AUTO, "normal", Mode.CLASSIC_RS485),
        (Mode.AUTO, "unknown-protocol", Mode.UNKNOWN_READ_ONLY),
        (Mode.CLASSIC_RS485, "channel-protocol", Mode.CHANNEL_RS485),
        (Mode.CHANNEL_RS485, "normal", Mode.CLASSIC_RS485),
    ],
)
async def test_unknown_or_channel_modes_observe_without_querying(mode, scenario, candidate):
    async with Simulator(port=0, interval=0.03, transport_lab=True, scenario=scenario) as simulator:
        async with SpaConnection("127.0.0.1", simulator.port, mode=mode, timing=FAST) as connection:
            observed = await connection.wait_for(lambda s: s.rx_frames >= 10, timeout=2)
            assert not observed.available and observed.configuration is None
            assert observed.tx_frames == 0 and simulator.stats.received_bytes == 0
            assert observed.candidate == candidate
            assert observed.state == ConnectionState.DETECTING_PROTOCOL


async def test_channel_evidence_after_sync_revokes_permission_and_configuration_for_epoch():
    async with Simulator(port=0, interval=0.03, scenario="channel-after-sync") as simulator:
        async with SpaConnection(
            "127.0.0.1", simulator.port, mode=Mode.CLASSIC_RS485, timing=FAST
        ) as connection:
            await connection.wait_for(lambda s: s.available, timeout=2)
            blocked = await connection.wait_for(
                lambda s: s.candidate == Mode.CHANNEL_RS485, timeout=2
            )
            assert not blocked.available and blocked.configuration is None
            later = await connection.wait_for(lambda s: s.rx_frames >= 20, timeout=2)
            assert later.tx_frames == 2 and later.epoch == 1
            assert any(e.kind == "mode_veto" for e in connection.events)
