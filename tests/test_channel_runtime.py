"""Real loopback assignment, addressed configuration and command verification."""

import asyncio
from dataclasses import replace

import pytest

from balboa_rs485.command.engine import CommandEngine, Stage
from balboa_rs485.protocol.frames import Frame, FrameParser, encode_frame
from balboa_rs485.runtime import SpaRuntime
from balboa_rs485.state.model import Control, PumpState
from balboa_rs485.transport.policy import Mode
from tools.simulator.server import Simulator, load_status_fixture

from .helpers import install_filter_reminder_variant, loopback_server
from .test_configuration import CAPS, INFO
from .test_connection import FAST


async def test_reminder_and_extended_setup_allow_only_verified_target_commands(monkeypatch):
    install_filter_reminder_variant(monkeypatch)
    async with Simulator(port=0, interval=0.03, channel_lab=True, control_lab=True) as simulator:
        async with SpaRuntime(
            "127.0.0.1",
            simulator.port,
            mode=Mode.CHANNEL_RS485,
            timing=FAST,
            engine=CommandEngine(confirmation_guard=0.02),
        ) as runtime:
            await runtime.connection.wait_for(lambda _: runtime.metadata_complete, timeout=3)
            assert runtime.state.setup is not None
            assert len(runtime.state.setup.frame.payload) == 10
            assert runtime.state.status.frame.payload[1] == 3
            assert not runtime.metadata_failures
            for desired in (36.5, 38):
                intent = runtime.request(Control.TARGET, desired)
                result = await runtime.wait_for_intent(intent.id, timeout=3)
                assert result.stage == Stage.VERIFIED
                assert runtime.state.target_temperature == desired
            assert simulator.physical_commands == 2
            assert all(record.frame.message_type == 32 for record in simulator.physical_records)
            assert runtime.state.status.frame.payload[1] == 3  # Reminder was not cleared.


@pytest.mark.parametrize("partial", [False, True])
async def test_batched_assignment_is_acknowledged_only_on_a_fresh_assigned_cts(partial):
    """Losing the immediate ACK slot must not discard a correlated assignment."""
    requests = []

    async def serve(reader, writer):
        parser = FrameParser()

        async def receive():
            while True:
                data = await reader.read(4096)
                if not data:
                    raise ConnectionError("test peer closed before expected frame")
                frames = parser.feed(data)
                if frames:
                    requests.extend(frames)
                    return frames[0]

        writer.write(encode_frame(Frame(254, 191, 0)))
        await writer.drain()
        request = await receive()
        assignment = Frame(254, 191, 2, b"\x12" + request.payload[1:])
        foreign_cts = encode_frame(Frame(17, 191, 6))
        writer.write(encode_frame(assignment) + (foreign_cts[:3] if partial else foreign_cts))
        await writer.drain()
        # Neither a partial tail nor someone else's CTS is permission to ACK.
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(reader.read(4096), timeout=0.04)
        if partial:
            writer.write(foreign_cts[3:])
            await writer.drain()
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(reader.read(4096), timeout=0.04)
        writer.write(encode_frame(Frame(18, 191, 6)))
        await writer.drain()
        assert await asyncio.wait_for(receive(), timeout=0.3) == Frame(18, 191, 3)
        # A later CTS is needed to establish READY and send a configuration query.
        for response in (INFO, CAPS):
            # Model distinct bus slots (Windows monotonic clock has coarse ticks).
            await asyncio.sleep(0.03)
            writer.write(encode_frame(load_status_fixture()) + encode_frame(Frame(18, 191, 6)))
            await writer.drain()
            assert (await receive()).message_type == 34
            writer.write(encode_frame(replace(response, address=18)))
            await writer.drain()
        await reader.read()

    async with loopback_server(serve) as port:
        async with SpaRuntime("127.0.0.1", port, mode=Mode.CHANNEL_RS485, timing=FAST) as runtime:
            try:
                snapshot = await runtime.connection.wait_for(lambda s: s.available, timeout=1)
            except TimeoutError:
                pytest.fail(str(runtime.connection.events))
            assert snapshot.channel == 18
            assert snapshot.channel_assignment.ack_on_cts
            assert len([f for f in requests if f.message_type == 1]) == 1
            assert len([f for f in requests if f.message_type == 3]) == 1
            assert all(f.message_type not in (17, 32) for f in requests)


async def test_channel_session_syncs_and_verifies_commands_only_on_its_assigned_address():
    async with Simulator(port=0, interval=0.03, channel_lab=True, control_lab=True) as simulator:
        async with SpaRuntime(
            "127.0.0.1",
            simulator.port,
            mode=Mode.CHANNEL_RS485,
            timing=FAST,
            engine=CommandEngine(confirmation_guard=0.02),
        ) as runtime:
            await runtime.connection.wait_for(lambda s: s.available, timeout=3)
            intent = runtime.request(Control.PUMP1, PumpState.HIGH)
            assert (await runtime.wait_for_intent(intent.id, timeout=3)).stage == Stage.VERIFIED
            assert runtime.connection.snapshot.channel == 18
            assert all(record.frame.address == 18 for record in simulator.query_records)
            assert all(record.frame.address == 18 for record in simulator.physical_records)
            assert simulator.physical_commands == 2
            assert simulator.stats.rejected_queries == 0
            assert all(item.action.frame.address == 18 for item in runtime.engine.history)
            await runtime.connection.wait_for(lambda _: simulator.stats.idle_replies > 0, timeout=2)


async def test_reconnects_cannot_exhaust_controller_channels_with_unbounded_assignments():
    requests = []

    async def serve(reader, writer):
        writer.write(encode_frame(Frame(254, 191, 0)))
        await writer.drain()
        parser = FrameParser()
        while data := await reader.read(4096):
            for frame in parser.feed(data):
                requests.append(frame)
                # The controller/gateway drops the socket before replying.
                return

    async with loopback_server(serve) as port:
        async with SpaRuntime("127.0.0.1", port, mode=Mode.CHANNEL_RS485, timing=FAST) as runtime:
            snapshot = await runtime.connection.wait_for(
                lambda s: s.channel_failure is not None, timeout=3
            )
            assert "budget" in snapshot.channel_failure.lower()
            assert not snapshot.available
            assert len(requests) == 3
            assert all((f.address, f.family, f.message_type) == (254, 191, 1) for f in requests)


@pytest.mark.parametrize("case", ["wrong_nonce", "no_cts_channel", "trailing_garbage"])
async def test_ambiguous_assignment_never_produces_an_ack_or_query_over_tcp(case):
    checked = asyncio.Event()

    async def serve(reader, writer):
        parser = FrameParser()
        writer.write(encode_frame(Frame(254, 191, 0)))
        await writer.drain()
        request = []
        while not request:
            request = parser.feed(await reader.read(4096))
        nonce = request[0].payload[1:]
        if case == "wrong_nonce":
            nonce = bytes((nonce[0] ^ 1, nonce[1]))
        address = 48 if case == "no_cts_channel" else 18
        wire = encode_frame(Frame(254, 191, 2, bytes((address,)) + nonce))
        writer.write(wire + (b"garbage" if case == "trailing_garbage" else b""))
        await writer.drain()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(reader.read(4096), timeout=0.1)
        checked.set()
        await reader.read()

    async with loopback_server(serve) as port:
        async with SpaRuntime("127.0.0.1", port, mode=Mode.CHANNEL_RS485, timing=FAST) as runtime:
            await asyncio.wait_for(checked.wait(), timeout=2)
            assert runtime.connection.snapshot.tx_frames == 1
            assert runtime.connection.snapshot.channel is None
            assert not runtime.connection.snapshot.available


@pytest.mark.parametrize("case", ["missing", "wrong_nonce", "batched"])
async def test_assignment_timeout_is_visible_without_reallocating_after_budget_exhaustion(case):
    requests = []

    async def serve(reader, writer):
        parser = FrameParser()
        writer.write(encode_frame(Frame(254, 191, 0)))
        await writer.drain()
        while not requests:
            requests.extend(parser.feed(await reader.read(4096)))
        nonce = requests[0].payload[1:]
        if case != "missing":
            echoed = bytes((nonce[0] ^ 1, nonce[1])) if case == "wrong_nonce" else nonce
            # A correlated assignment followed by later traffic is not a fresh
            # permission to ACK. Diagnostics must retain that it was observed.
            wire = encode_frame(Frame(254, 191, 2, b"\x12" + echoed))
            if case == "batched":
                wire += encode_frame(Frame(17, 191, 6))
            writer.write(wire)
            await writer.drain()
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
        async with SpaRuntime("127.0.0.1", port, mode=Mode.CHANNEL_RS485, timing=FAST) as runtime:
            # This socket has the final remaining allocation in its runtime.
            runtime.connection._assignment_requests = 2
            snapshot = await runtime.connection.wait_for(
                lambda s: s.channel_failure is not None, timeout=3
            )
            assert "timed out" in snapshot.channel_failure.lower()
            assert snapshot.channel_assignment.requested
            assert snapshot.channel_assignment.responses == int(case != "missing")
            assert snapshot.channel_assignment.correlated == int(case == "batched")
            assert snapshot.channel_assignment.reply_opportunities == 0
            assert snapshot.epoch == 1 and snapshot.recoveries == 0
            assert snapshot.channel is None and not snapshot.available
            assert snapshot.tx_frames == len(requests) == 1


async def test_missed_ack_slot_recovers_on_new_epoch_without_acknowledging_old_nonce(monkeypatch):
    # Even a random-generator collision must not reuse a retired request nonce.
    monkeypatch.setattr("balboa_rs485.transport.policy.secrets.token_bytes", lambda _: b"\xee\x14")
    nonces = []
    acks = []

    async def serve(reader, writer):
        parser = FrameParser()

        async def receive():
            while data := await reader.read(4096):
                frames = parser.feed(data)
                if frames:
                    return frames[0]
            raise ConnectionError("test peer closed")

        writer.write(encode_frame(Frame(254, 191, 0)))
        await writer.drain()
        request = await receive()
        nonces.append(request.payload[1:])
        assignment = Frame(254, 191, 2, b"\x12" + nonces[-1])
        if len(nonces) == 1:
            # Exact hardware pattern: correlated offer + another client's CTS/NTS.
            writer.write(
                encode_frame(assignment)
                + encode_frame(Frame(17, 191, 6))
                + encode_frame(Frame(17, 191, 7))
            )
            await writer.drain()
            while True:
                writer.write(encode_frame(Frame(17, 191, 6)))
                await writer.drain()
                try:
                    data = await asyncio.wait_for(reader.read(4096), timeout=0.03)
                except TimeoutError:
                    continue
                assert not data, "No late ACK or second request on the old socket"
                return
        writer.write(encode_frame(Frame(254, 191, 2, b"\x12" + nonces[0])))
        await writer.drain()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(reader.read(4096), timeout=0.04)
        writer.write(encode_frame(assignment))
        await writer.drain()
        ack = await receive()
        assert ack == Frame(18, 191, 3)
        acks.append(ack)
        for response in (INFO, CAPS):
            await asyncio.sleep(0.03)
            writer.write(encode_frame(load_status_fixture()) + encode_frame(Frame(18, 191, 6)))
            await writer.drain()
            assert (await receive()).message_type == 34
            writer.write(encode_frame(replace(response, address=18)))
            await writer.drain()
        await reader.read()

    async with loopback_server(serve) as port:
        async with SpaRuntime("127.0.0.1", port, mode=Mode.CHANNEL_RS485, timing=FAST) as runtime:
            snapshot = await runtime.connection.wait_for(lambda s: s.available, timeout=4)
            assert snapshot.epoch == 2 and snapshot.recoveries == 1
            assert len(nonces) == 2 and nonces[0] != nonces[1]
            assert len(acks) == 1
            assert snapshot.assignment_requests == 2
            assert any(e.kind == "backoff" for e in runtime.connection.events)
