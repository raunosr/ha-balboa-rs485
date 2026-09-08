"""Channel ownership is negotiated, never inferred from a quiet CTS address."""

import pytest

from balboa_rs485.protocol.frames import Frame
from balboa_rs485.transport.channel import ChannelSession


def test_only_a_correlated_assignment_then_ack_and_owned_cts_establish_ownership():
    session = ChannelSession(nonce=b"\xee\x14")
    assert session.channel is None
    assert session.reply([Frame(16, 191, 6)], at=1) is None
    request = session.reply([Frame(254, 191, 0)], at=2)
    assert request == Frame(254, 191, 1, b"\x02\xee\x14")
    session.sent(request, at=2)
    assert session.reply([Frame(254, 191, 2, b"\x12\xee\x15")], at=2.1) is None
    ack = session.reply([Frame(254, 191, 2, b"\x12\xee\x14")], at=2.2)
    assert ack == Frame(18, 191, 3)
    assert not session.ready
    session.sent(ack, at=2.2)
    session.observe(Frame(17, 191, 6))
    assert not session.ready
    session.observe(Frame(18, 191, 6))
    assert session.ready and session.channel == 18


def test_busy_channel_is_rejected_and_client_traffic_on_our_channel_revokes_ownership():
    session = ChannelSession(nonce=b"\xee\x14")
    session.observe(Frame(17, 191, 7))
    session.sent(session.reply([Frame(254, 191, 0)], at=1), at=1)
    assert session.reply([Frame(254, 191, 2, b"\x11\xee\x14")], at=1.1) is None
    ack = session.reply([Frame(254, 191, 2, b"\x12\xee\x14")], at=1.2)
    session.sent(ack, at=1.2)
    session.observe(Frame(18, 191, 6))
    session.observe(Frame(18, 191, 7))
    assert not session.ready
    assert session.failure == "Client traffic on owned channel (collision or echo)"
    session.observe(Frame(18, 191, 6))
    assert not session.ready
    assert session.reply([Frame(254, 191, 0)], at=2) is None


def test_idle_owned_cts_and_existing_client_probe_have_known_bounded_replies():
    session = ChannelSession(nonce=b"\xee\x14")
    session.sent(session.reply([Frame(254, 191, 0)], at=1), at=1)
    session.sent(session.reply([Frame(254, 191, 2, b"\x12\xee\x14")], at=1.1), at=1.1)
    assert session.reply([Frame(18, 191, 4)], at=1.2) == Frame(18, 191, 5, b"\x04\x08\0")
    assert session.idle_reply([Frame(18, 191, 6)]) == Frame(18, 191, 7)
    assert session.idle_reply([Frame(17, 191, 6)]) is None


@pytest.mark.parametrize(
    "payload,at", [(b"\x30\xee\x14", 1.1), (b"\x12\xee\x14", 4), (b"\x12\xee", 1.1)]
)
def test_expired_malformed_or_non_transmitting_assignment_is_never_acknowledged(payload, at):
    session = ChannelSession(nonce=b"\xee\x14")
    assert session.reply([Frame(254, 191, 2, payload)], at=0) is None
    session.sent(session.reply([Frame(254, 191, 0)], at=1), at=1)
    assert session.reply([Frame(254, 191, 2, payload)], at=at) is None
    assert session.reply([Frame(254, 191, 0)], at=5) is None
    assert not session.ready


def pending_assignment():
    session = ChannelSession(nonce=b"\xee\x14")
    session.sent(session.reply([Frame(254, 191, 0)], at=1), at=1)
    session.consider_assignments([Frame(254, 191, 2, b"\x12\xee\x14")], at=1.1)
    return session


def test_remembered_assignment_is_not_ownership_or_a_cached_transmission_credit():
    session = pending_assignment()
    assert session.channel is None and not session.ready
    assert session.assignment_status.pending
    assert session.reply([], at=1.2) is None
    assert session.reply([Frame(17, 191, 6)], at=1.3) is None
    assert session.reply([Frame(18, 191, 6), Frame(17, 191, 6)], at=1.4) is None
    ack = session.reply([Frame(18, 191, 6)], at=1.5)
    assert ack == Frame(18, 191, 3)
    assert not session.assignment_status.ack_on_cts
    session.sent(ack, at=1.5)
    assert session.assignment_status.ack_on_cts
    assert not session.assignment_status.pending
    assert not session.ready
    session.observe(Frame(18, 191, 6))
    assert session.ready
    assert session.reply([Frame(18, 191, 6)], at=1.6) is None


@pytest.mark.parametrize("case", ["expired", "occupied", "conflict", "invalid_conflict", "epoch"])
def test_pending_ack_cannot_cross_deadline_collision_conflict_or_epoch(case):
    session = pending_assignment()
    at = 1.5
    if case == "expired":
        at = 3
    elif case == "occupied":
        session.observe(Frame(18, 191, 7))
    elif case in ("conflict", "invalid_conflict"):
        channel = 19 if case == "conflict" else 48
        session.consider_assignments([Frame(254, 191, 2, bytes((channel, 238, 20)))], at=1.2)
        assert "Conflicting" in session.failure
    else:
        session = ChannelSession(nonce=b"\xee\x14")
    assert session.reply([Frame(18, 191, 6)], at=at) is None
    assert session.channel is None and not session.ready


def test_repeated_correlated_assignment_keeps_one_candidate_and_negative_age_is_rejected():
    session = pending_assignment()
    session.consider_assignments([Frame(254, 191, 2, b"\x12\xee\x14")], at=0.9)
    session.consider_assignments([Frame(254, 191, 2, b"\x12\xee\x14")], at=1.2)
    assert session.reply([Frame(18, 191, 6)], at=1.3) == Frame(18, 191, 3)
