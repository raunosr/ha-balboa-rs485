"""Fixed-address direct RS485/TCP experiment: loopback only, never a live spa."""

import asyncio
from collections import deque

import pytest

from balboa_rs485.command.engine import CommandEngine, Stage
from balboa_rs485.protocol.configuration import Query, encode_query
from balboa_rs485.protocol.frames import Frame, FrameParser, encode_frame
from balboa_rs485.runtime import SpaRuntime
from balboa_rs485.state.model import Control, PumpState
from balboa_rs485.transport.connection import SpaConnection
from balboa_rs485.transport.policy import BusPolicy, Mode
from tools.simulator.server import configuration_fixture, load_status_fixture

from .helpers import loopback_server
from .test_connection import FAST

LAB = "direct-rs485-tcp-lab"


@pytest.fixture(params=[Mode(LAB), Mode.DIRECT_RS485_TCP])
def direct_mode(request):
    return request.param


@pytest.mark.parametrize("accepted", [False, None, 1, "yes"])
def test_live_direct_requires_explicit_risk_acceptance_before_network_io(accepted):
    with pytest.raises(ValueError, match="risk acceptance"):
        SpaRuntime(
            "203.0.113.10",
            8899,
            mode=Mode.DIRECT_RS485_TCP,
            allow_unarbitrated_writes=accepted,
        )


def test_live_direct_accepts_remote_endpoint_only_with_explicit_permission():
    conn = SpaConnection(
        "203.0.113.10", 8899, mode=Mode.DIRECT_RS485_TCP, allow_unarbitrated_writes=True
    )
    assert not conn.running  # Construction must not open a connection.


class DirectPeer:
    """Synthetic direct-address peer with no free negotiated channels.

    Accepting 0x0A writes is the explicit experimental assumption, not evidence
    about any real controller. No CTS is offered for that address.
    """

    def __init__(
        self,
        *,
        drop_connections=0,
        lose_confirmation=False,
        reset_after_write=False,
        commit_delay=0,
        reply_delay=0,
    ):
        self.drop_connections = drop_connections
        self.lose_confirmation = lose_confirmation
        self.reset_after_write = reset_after_write
        self.commit_delay, self.reply_delay = commit_delay, reply_delay
        self.write_received = asyncio.Event()
        self.connections = self.active = self.max_active = 0
        self.allocations = self.physical = self.pump = 0
        self.high = True
        self.received = deque(maxlen=128)
        self.physical_epochs = []
        self.silence = False

    async def serve(self, reader, writer):
        self.connections += 1
        epoch = self.connections
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        parser = FrameParser()
        try:
            while True:
                if self.silence and epoch == 1:
                    await reader.read()  # Zombie: neither FIN nor more data.
                    return
                payload = bytearray(load_status_fixture().payload)
                payload[10] = (payload[10] & ~4) | (4 if self.high else 0)
                payload[11] = self.pump
                payload[20] = 76 if self.high else 40
                traffic = [Frame(254, 191, 0), Frame(17, 191, 6), Frame(17, 191, 7)]
                if not (self.lose_confirmation and self.physical == 1 and epoch == 1):
                    traffic.insert(0, Frame(255, 175, 19, bytes(payload)))
                writer.write(b"".join(encode_frame(f) for f in traffic))
                await writer.drain()
                try:
                    data = await asyncio.wait_for(reader.read(4096), 0.03)
                except TimeoutError:
                    continue
                if not data:
                    return
                for frame in parser.feed(data):
                    self.received.append(frame)
                    if frame == Frame(254, 191, 1, frame.payload):
                        self.allocations += 1
                        # Finite pool already exhausted: an unusable offer only.
                        writer.write(encode_frame(Frame(254, 191, 2, b"\x30" + frame.payload[1:])))
                        await writer.drain()
                        continue
                    assert (frame.address, frame.family) == (10, 191)
                    if epoch <= self.drop_connections:
                        return
                    query = next((q for q in Query if encode_query(q) == frame), None)
                    if query is not None:
                        await asyncio.sleep(self.reply_delay)
                        writer.write(encode_frame(configuration_fixture(query)))
                        await writer.drain()
                        continue
                    assert frame.message_type == 17
                    self.write_received.set()
                    if self.commit_delay:
                        # Delayed commit, with a queued pre-write status first.
                        writer.write(encode_frame(Frame(255, 175, 19, bytes(payload))))
                        await writer.drain()
                        await asyncio.sleep(self.commit_delay)
                    if frame.payload == b"\x04\0":
                        self.pump = (self.pump + 1) % 3
                    elif frame.payload == b"\x50\0":
                        self.high = not self.high
                    else:
                        pytest.fail(f"Unexpected physical action: {frame}")
                    self.physical += 1
                    self.physical_epochs.append(epoch)
                    if self.reset_after_write and self.physical == 1:
                        writer.transport.abort()
                        return
        finally:
            self.active -= 1


@pytest.mark.parametrize("host", ["203.0.113.10", "localhost", "example.invalid", "0.0.0.0"])
def test_direct_mode_rejects_non_loopback_literals_before_any_network_io(host):
    with pytest.raises(ValueError, match="loopback"):
        SpaConnection(host, 8899, mode=Mode(LAB))


def test_direct_policy_is_explicit_paced_and_preserves_unsupported_family_veto(direct_mode):
    policy = BusPolicy(direct_mode)
    status = load_status_fixture()
    assert not policy.supported
    policy.observe(status)
    policy.observe(Frame(17, 191, 6))
    assert policy.supported and policy.address == 10
    assert policy.candidate == Mode.CHANNEL_RS485  # Evidence is not silently renamed.
    policy.observe(configuration_fixture(Query.FILTERS))
    assert policy.supported  # BF23 is also a legitimate incoming query response.
    kwargs = dict(received_at=1, now=1, residual=0, cts_window=0.2)
    assert policy.allows_query([status], **kwargs)
    assert not policy.allows_query([status], **kwargs)
    assert not policy.allows_query([status], **(kwargs | {"now": 1.05}))
    assert not policy.allows_query([status], **(kwargs | {"now": 1.2, "residual": 1}))
    assert not policy.allows_query([], **(kwargs | {"now": 1.2}))
    assert policy.allows_query([status], **(kwargs | {"received_at": 1.2, "now": 1.2}))
    policy.observe(Frame(255, 175, 0xC4))
    assert not policy.supported
    assert not policy.allows_query([status], **(kwargs | {"now": 2}))


@pytest.mark.parametrize("item", [17, 32, 34])
def test_direct_policy_stops_if_other_client_or_gateway_echo_uses_fixed_address(item, direct_mode):
    policy = BusPolicy(direct_mode)
    policy.observe(load_status_fixture())
    policy.observe(Frame(10, 191, item, b"\0\0"))
    assert not policy.supported


async def test_direct_recovers_beyond_three_disconnects_without_allocating_channels(direct_mode):
    peer = DirectPeer(drop_connections=4)
    async with loopback_server(peer.serve) as port:
        async with SpaConnection(
            "127.0.0.1", port, mode=direct_mode, timing=FAST, allow_unarbitrated_writes=True
        ) as conn:
            snapshot = await conn.wait_for(lambda s: s.available, timeout=4)
            assert snapshot.epoch == 5 and snapshot.recoveries == 4
            assert snapshot.assignment_requests == peer.allocations == 0
            assert snapshot.channel is None and not snapshot.channel_assignment.requested
            assert snapshot.configuration is not None and snapshot.status is not None
            assert peer.physical == 0 and peer.max_active == 1
    assert peer.active == 0 and not conn.running


async def test_direct_zombie_socket_closes_and_resynchronizes_without_reload(direct_mode):
    peer = DirectPeer()
    async with loopback_server(peer.serve) as port:
        async with SpaConnection(
            "127.0.0.1", port, mode=direct_mode, timing=FAST, allow_unarbitrated_writes=True
        ) as conn:
            first = await conn.wait_for(lambda s: s.available, timeout=3)
            peer.silence = True
            await conn.wait_for(lambda s: not s.available, timeout=2)
            fresh = await conn.wait_for(lambda s: s.available and s.epoch == 2, timeout=3)
            assert fresh.configuration.signature == first.configuration.signature
            assert fresh.assignment_requests == peer.allocations == peer.physical == 0
            assert peer.max_active == 1


async def test_direct_delayed_commit_keeps_observed_state_until_confirmation(direct_mode):
    peer = DirectPeer(commit_delay=0.08, reply_delay=0.04)
    async with loopback_server(peer.serve) as port:
        async with SpaRuntime(
            "127.0.0.1",
            port,
            mode=direct_mode,
            allow_unarbitrated_writes=True,
            timing=FAST,
            engine=CommandEngine(confirmation_guard=0.02),
        ) as runtime:
            await runtime.connection.wait_for(lambda s: s.available, timeout=3)
            intent = runtime.request(Control.HIGH_RANGE, False)
            await asyncio.wait_for(peer.write_received.wait(), timeout=2)
            assert runtime.state.value(Control.HIGH_RANGE) is True
            assert runtime.engine.intent(intent.id).stage != Stage.VERIFIED
            assert (await runtime.wait_for_intent(intent.id, timeout=3)).stage == Stage.VERIFIED
            assert runtime.state.value(Control.HIGH_RANGE) is False
            assert peer.physical == 1 and peer.allocations == 0


async def test_direct_cancellation_stops_reconnects_and_closes_owned_socket(direct_mode):
    peer = DirectPeer(drop_connections=100)
    async with loopback_server(peer.serve) as port:
        conn = SpaConnection(
            "127.0.0.1", port, mode=direct_mode, timing=FAST, allow_unarbitrated_writes=True
        )
        async with conn:
            await conn.wait_for(lambda s: s.epoch >= 2, timeout=2)
        count = peer.connections
        await asyncio.sleep(0.12)
        assert not conn.running and not conn.snapshot.available
        assert peer.connections == count and peer.active == 0
        assert peer.allocations == peer.physical == 0


@pytest.mark.parametrize("reset", [False, True])
@pytest.mark.parametrize(
    "control,desired,expected",
    [
        (Control.HIGH_RANGE, False, 1),
        (Control.PUMP1, PumpState.LOW, 1),
        (Control.PUMP1, PumpState.HIGH, 2),
    ],
)
async def test_direct_ambiguous_toggle_resyncs_and_never_replays_raw_command(
    reset, control, desired, expected, direct_mode
):
    peer = DirectPeer(lose_confirmation=not reset, reset_after_write=reset)
    engine = CommandEngine(confirmation_guard=0.02, confirmation_timeout=0.15, resync_settle=0.06)
    async with loopback_server(peer.serve) as port:
        async with SpaRuntime(
            "127.0.0.1",
            port,
            mode=direct_mode,
            timing=FAST,
            engine=engine,
            allow_unarbitrated_writes=True,
        ) as runtime:
            await runtime.connection.wait_for(lambda s: s.available, timeout=3)
            intent = runtime.request(control, desired)
            assert (await runtime.wait_for_intent(intent.id, timeout=4)).stage == Stage.VERIFIED
            assert runtime.state.value(control) == desired
            assert peer.physical == expected
            assert peer.physical_epochs == ([1] if expected == 1 else [1, 2])
            assert runtime.connection.snapshot.epoch == 2
            assert runtime.connection.snapshot.assignment_requests == peer.allocations == 0
            assert all(record.cts_at is None for record in engine.history)
            assert engine.history[0].result == (Stage.CANCELLED if reset else Stage.FAILED)
            assert peer.max_active == 1
