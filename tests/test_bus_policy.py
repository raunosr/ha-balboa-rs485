"""Permission is separate from observing recognizable wire signatures."""

from balboa_rs485.protocol.frames import Frame
from balboa_rs485.transport.policy import BusPolicy, Mode
from tools.simulator.server import load_status_fixture

READY = Frame(16, 191, 6)


def test_auto_remains_passive_even_after_repeated_classic_compatible_traffic():
    policy = BusPolicy(Mode.AUTO)
    for _ in range(10):
        policy.observe(load_status_fixture())
        policy.observe(READY)
    assert policy.mode == Mode.UNKNOWN_READ_ONLY
    assert policy.candidate == Mode.CLASSIC_RS485
    assert not policy.allows_query([READY], received_at=1, now=1, residual=0, cts_window=0.2)


def test_explicit_classic_consumes_one_fresh_final_cts_without_banking():
    policy = BusPolicy(Mode.CLASSIC_RS485)
    policy.observe(load_status_fixture())
    assert policy.mode == Mode.CLASSIC_RS485
    assert policy.allows_query([READY, READY], received_at=1, now=1.1, residual=0, cts_window=0.2)
    assert not policy.allows_query([READY], received_at=1, now=1.1, residual=0, cts_window=0.2)
    for frames, stamp, now, residual in (
        ([READY, load_status_fixture()], 2, 2, 0),
        ([READY], 3, 3, 1),
        ([READY], 4, 4.3, 0),
        ([], 5, 5, 0),
    ):
        assert not policy.allows_query(
            frames, received_at=stamp, now=now, residual=residual, cts_window=0.2
        )
    assert policy.allows_query([READY], received_at=6, now=6, residual=0, cts_window=0.2)


def test_bwa_needs_explicit_mode_and_channel_evidence_vetoes_all_writes():
    for mode in Mode:
        policy = BusPolicy(mode)
        assert not policy.allows_query([], received_at=1, now=1, residual=0, cts_window=0.2)
        policy.observe(load_status_fixture())
        assert policy.allows_query([], received_at=2, now=2, residual=0, cts_window=0.2) == (
            mode == Mode.BWA_TCP
        )
        for frame in (Frame(254, 191, 0), Frame(17, 191, 6), Frame(255, 175, 0xC4)):
            policy.observe(frame)
        assert policy.candidate == Mode.CHANNEL_RS485
        assert policy.mode in (Mode.UNKNOWN_READ_ONLY, Mode.CHANNEL_RS485)
        assert not policy.allows_query([READY], received_at=3, now=3, residual=0, cts_window=0.2)
        policy.observe(READY)
        assert not policy.allows_query([READY], received_at=4, now=4, residual=0, cts_window=0.2)
