"""Pump 1 is also the non-circ spa's automatic circulation pump."""

from dataclasses import replace

import pytest

from balboa_rs485.command.engine import CommandEngine, Stage
from balboa_rs485.protocol.frames import Frame
from balboa_rs485.protocol.messages import decode_message
from balboa_rs485.state.model import Control, PumpState

from .test_state import observed


def non_circ(*, pump=1, **kwargs):
    state = observed(pump=pump, capabilities=b"\x06\0\x01\x02\0\0", **kwargs)
    data = bytearray(state.status.frame.payload)
    data[5], data[9], data[10], data[13] = 0, 3, 4, 0
    return replace(state, status=decode_message(Frame(255, 175, 19, bytes(data))))


@pytest.mark.parametrize(
    "offset,value,reason",
    [
        (11, 9, "other_pump"),
        (13, 4, "blower"),
        (10, 20, "heating"),
        (5, 2, "ready_in_rest"),
        (9, 15, "filtration"),
    ],
)
def test_known_circulation_rejects_off_without_blocking_jets_or_other_controls(
    offset, value, reason
):
    state = non_circ()
    data = bytearray(state.status.frame.payload)
    data[offset] = value
    state = replace(state, status=decode_message(Frame(255, 175, 19, bytes(data))))
    assert state.pump1_circulation_reason == reason
    with pytest.raises(ValueError, match="circulation"):
        state.validate(Control.PUMP1, PumpState.OFF)
    state.validate(Control.PUMP1, PumpState.LOW)
    state.validate(Control.PUMP1, PumpState.HIGH)
    state.validate(Control.LIGHT1, True)


def test_dedicated_or_unknown_circulation_capability_does_not_infer_forced_pump1():
    for caps in (b"\x06\0\x01\x82\0\0", b"\x06\0\x01\x42\0\0"):
        state = observed(pump=9, capabilities=caps)
        assert state.pump1_circulation_reason is None
        state.validate(Control.PUMP1, PumpState.OFF)
    assert non_circ().pump1_circulation_reason is None


@pytest.mark.parametrize("water", [36.5, 37.5, None])
def test_ready_in_rest_alone_does_not_inhibit_off_after_target_or_unknown_water(water):
    state = non_circ()
    data = bytearray(state.status.frame.payload)
    data[5] = 2
    data[2] = int(water * 2) if water is not None else 255
    data[20] = 73  # Celsius target 36.5, heater OFF, no other circulation reason.
    state = replace(state, status=decode_message(Frame(255, 175, 19, bytes(data))))
    assert state.pump1_circulation_reason is None
    state.validate(Control.PUMP1, PumpState.OFF)


def test_circulation_starting_after_request_is_revalidated_before_transmission():
    engine = CommandEngine()
    engine.observe(non_circ(), now=1)
    intent = engine.request(Control.PUMP1, PumpState.OFF, now=1)
    engine.observe(non_circ(pump=9, sequence=2, at=1.1), now=1.1)
    assert engine.next_action(now=1.1) is None
    assert engine.intent(intent.id).stage == Stage.FAILED
    assert engine.history == ()
    assert engine.resync_epoch is None


def test_retained_low_after_high_to_off_stops_goal_without_retry_or_reconnect():
    engine = CommandEngine(confirmation_guard=0.1)
    engine.observe(non_circ(pump=2), now=1)
    intent = engine.request(Control.PUMP1, PumpState.OFF, now=1)
    action = engine.next_action(now=1.1)
    engine.sent(action, at=1.1, cts_at=1.1)
    engine.observe(non_circ(pump=1, sequence=2, at=1.15), now=1.15)
    assert engine.busy  # No shortcut around the existing post-send guard.
    engine.observe(non_circ(pump=1, sequence=3, at=1.4), now=1.4)
    assert engine.intent(intent.id).stage == Stage.FAILED
    assert "circulation" in engine.intent(intent.id).reason
    assert not engine.busy and engine.resync_epoch is None
    assert engine.history[-1].resulting_value == PumpState.LOW
    assert engine.next_action(now=1.5) is None
    # Later observations must not resurrect a failed OFF goal.
    engine.observe(non_circ(pump=0, sequence=4, at=1.6), now=1.6)
    assert engine.intent(intent.id).stage == Stage.FAILED
    engine.request(Control.LIGHT1, True, now=1.6)
    assert engine.next_action(now=1.7).intent.control == Control.LIGHT1


def test_unchanged_high_is_still_ambiguous_and_requires_resynchronization():
    engine = CommandEngine(confirmation_guard=0.1, confirmation_timeout=0.5)
    engine.observe(non_circ(pump=2), now=1)
    engine.request(Control.PUMP1, PumpState.OFF, now=1)
    engine.sent(engine.next_action(now=1.1), at=1.1, cts_at=1.1)
    engine.observe(non_circ(pump=2, sequence=2, at=1.4), now=1.4)
    assert engine.busy
    engine.tick(now=1.7)
    assert engine.resync_epoch == 1


def test_retained_circulation_does_not_override_a_newer_low_goal():
    engine = CommandEngine(confirmation_guard=0.1)
    engine.observe(non_circ(pump=2), now=1)
    first = engine.request(Control.PUMP1, PumpState.OFF, now=1)
    engine.sent(engine.next_action(now=1.1), at=1.1, cts_at=1.1)
    newer = engine.request(Control.PUMP1, PumpState.LOW, now=1.2)
    engine.observe(non_circ(pump=1, sequence=2, at=1.4), now=1.4)
    assert engine.intent(first.id).stage == Stage.SUPERSEDED
    assert engine.intent(newer.id).stage == Stage.VERIFIED
    assert engine.resync_epoch is None
