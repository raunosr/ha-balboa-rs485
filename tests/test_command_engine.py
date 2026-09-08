"""Desired-state behavior, independent of sockets or Home Assistant."""

import pytest

from balboa_rs485.command.engine import CommandEngine, Stage
from balboa_rs485.protocol.frames import Frame
from balboa_rs485.state.model import Control, PumpState

from .test_state import observed


@pytest.mark.parametrize("timeout", [0, -1, 0.2, float("nan"), float("inf")])
def test_invalid_filter_confirmation_deadline_is_rejected(timeout):
    with pytest.raises(ValueError, match="Filter confirmation timeout"):
        CommandEngine(filter_confirmation_timeout=timeout)


def test_filter_read_deadline_does_not_extend_ambiguous_pump_toggle():
    engine = CommandEngine(confirmation_timeout=0.5, filter_confirmation_timeout=9)
    engine.observe(observed(), now=1)
    engine.request(Control.PUMP1, PumpState.HIGH, now=1)
    action = engine.next_action(now=1.1)
    engine.sent(action, at=1.1, cts_at=1.1)
    assert engine.pending_transaction.action == action
    engine.tick(now=1.7)
    assert engine.pending_transaction is None
    assert engine.history[-1].result == Stage.FAILED
    assert engine.resync_epoch == 1
    assert engine.next_action(now=1.7) is None


def test_two_speed_pump_advances_only_after_each_observed_step():
    engine = CommandEngine(confirmation_guard=0.1)
    initial = observed()
    engine.observe(initial, now=1)
    intent = engine.request(Control.PUMP1, PumpState.HIGH, now=1)
    action = engine.next_action(now=1.1)
    assert action.frame == Frame(10, 191, 17, b"\x04\0")
    engine.sent(action, at=1.1, cts_at=1.1)
    assert engine.state is initial
    assert engine.next_action(now=1.2) is None
    engine.observe(observed(pump=1, sequence=2, at=1.4), now=1.4)
    action2 = engine.next_action(now=1.5)
    assert action2.expected == PumpState.HIGH
    engine.sent(action2, at=1.5, cts_at=1.5)
    engine.observe(observed(pump=2, sequence=3, at=1.8), now=1.8)
    assert engine.intent(intent.id).stage == Stage.VERIFIED
    assert engine.next_action(now=1.9) is None
    assert len(engine.history) == 2
    assert all(row.result == Stage.VERIFIED for row in engine.history)
    assert engine.history[0].starting_value == PumpState.OFF
    assert engine.history[0].resulting_value == PumpState.LOW
    assert engine.history[1].cts_at == 1.5


def test_forced_circulation_final_goal_confirms_without_observing_intermediate_off():
    engine = CommandEngine(confirmation_guard=0.1)
    engine.observe(observed(pump=2), now=1)
    intent = engine.request(Control.PUMP1, PumpState.LOW, now=1)
    action = engine.next_action(now=1.1)
    assert action.expected == PumpState.OFF
    engine.sent(action, at=1.1, cts_at=1.1)
    # A filter/heating cycle keeps low running, so OFF may never be broadcast.
    engine.observe(observed(pump=1, sequence=2, at=1.15), now=1.15)
    assert engine.busy  # The existing post-send guard is still mandatory.
    engine.observe(observed(pump=1, sequence=3, at=1.4), now=1.4)
    assert engine.intent(intent.id).stage == Stage.VERIFIED
    assert engine.history[-1].resulting_value == PumpState.LOW
    assert engine.next_action(now=1.5) is None
    assert engine.resync_epoch is None
    assert len(engine.history) == 1


@pytest.mark.parametrize("desired", [PumpState.LOW, PumpState.HIGH])
def test_lost_toggle_confirmation_never_blindly_retries_and_rebases_after_resync(desired):
    engine = CommandEngine(confirmation_guard=0.1, confirmation_timeout=0.5, resync_settle=0.2)
    engine.observe(observed(), now=1)
    intent = engine.request(Control.PUMP1, desired, now=1)
    first = engine.next_action(now=1.1)
    engine.sent(first, at=1.1, cts_at=1.1)
    # Pump physically becomes LOW, but that status is dropped. Buffered OFF isn't proof of failure.
    for sequence in range(2, 8):
        engine.observe(observed(sequence=sequence, at=1.2), now=1.2)
    engine.tick(now=1.7)
    assert engine.resync_epoch == 1
    assert engine.history[-1].result == Stage.FAILED
    assert engine.next_action(now=2) is None
    engine.observe(observed(pump=1, sequence=8, at=2), now=2)
    assert engine.next_action(now=2) is None  # No same-epoch retry after ambiguity.
    engine.observe(observed(pump=1, epoch=2, sequence=1, at=3), now=3)
    assert engine.next_action(now=3) is None
    engine.observe(observed(pump=1, epoch=2, sequence=2, at=3.3), now=3.3)
    next_action = engine.next_action(now=3.3)
    assert engine.resync_epoch is None
    if desired == PumpState.LOW:
        assert next_action is None
        assert engine.intent(intent.id).stage == Stage.VERIFIED
    else:
        assert next_action.starting_value == PumpState.LOW
        assert next_action.expected == PumpState.HIGH
        assert next_action.epoch == 2


def test_coalescing_supersedes_intent_but_keeps_sent_physical_transaction():
    engine = CommandEngine(confirmation_guard=0.1)
    engine.observe(observed(), now=1)
    first = engine.request(Control.PUMP1, PumpState.HIGH, now=1)
    second = engine.request(Control.PUMP1, PumpState.OFF, now=1)
    assert engine.intent(first.id).stage == Stage.SUPERSEDED
    assert engine.next_action(now=1) is None
    assert engine.intent(second.id).stage == Stage.VERIFIED
    third = engine.request(Control.PUMP1, PumpState.HIGH, now=1.1)
    action = engine.next_action(now=1.1)
    engine.sent(action, at=1.1, cts_at=1.1)
    final = engine.request(Control.PUMP1, PumpState.LOW, now=1.2)
    assert engine.intent(third.id).stage == Stage.SUPERSEDED
    assert engine.next_action(now=1.2) is None
    engine.observe(observed(pump=1, sequence=2, at=1.4), now=1.4)
    assert engine.intent(final.id).stage == Stage.VERIFIED
    assert engine.next_action(now=1.4) is None
    assert len(engine.history) == 1


def test_absolute_target_coalesces_and_does_not_change_observed_temperature_on_tx():
    from balboa_rs485.protocol.messages import decode_message

    from .test_extended_messages import SETUP

    engine = CommandEngine(confirmation_guard=0.1)
    engine.observe(observed(setup=decode_message(SETUP)), now=1)
    intents = [engine.request(Control.TARGET, target, now=1) for target in (35, 36, 37, 39)]
    action = engine.next_action(now=1.1)
    assert action.frame == Frame(10, 191, 32, b"\x4e")
    engine.sent(action, at=1.1, cts_at=1.1)
    assert engine.state.target_temperature == 38
    assert all(engine.intent(item.id).stage == Stage.SUPERSEDED for item in intents[:-1])


def test_removed_capability_fails_intent_without_sending_or_crashing():
    engine = CommandEngine()
    engine.observe(observed(), now=1)
    request = engine.request(Control.PUMP1, PumpState.HIGH, now=1)
    engine.observe(observed(capabilities=bytes(6), sequence=2, at=2), now=2)
    assert engine.next_action(now=2) is None
    assert engine.intent(request.id).stage == Stage.FAILED


def test_history_eviction_does_not_drop_another_controls_active_intent():
    engine = CommandEngine()
    engine.observe(observed(), now=1)
    first = engine.request(Control.PUMP2, PumpState.ON, now=1)
    for i in range(150):
        engine.request(Control.PUMP1, PumpState.HIGH if i % 2 else PumpState.LOW, now=1)
    action = engine.next_action(now=1.1)
    assert action.intent.id == first.id


def test_cancellation_does_not_erase_sent_action_or_allow_another_toggle():
    engine = CommandEngine(confirmation_guard=0.1)
    engine.observe(observed(), now=1)
    request = engine.request(Control.PUMP1, PumpState.HIGH, now=1)
    action = engine.next_action(now=1.1)
    engine.sent(action, at=1.1, cts_at=1.1)
    engine.cancel(Control.PUMP1)
    assert engine.intent(request.id).stage == Stage.CANCELLED
    assert engine.busy and engine.next_action(now=1.2) is None
    engine.observe(observed(pump=1, sequence=2, at=1.4), now=1.4)
    assert engine.next_action(now=1.4) is None
    assert engine.intent(request.id).stage == Stage.CANCELLED


def test_action_cannot_be_used_after_a_new_observation_or_superseding_intent():
    engine = CommandEngine()
    engine.observe(observed(), now=1)
    engine.request(Control.PUMP1, PumpState.HIGH, now=1)
    action = engine.next_action(now=1.1)
    engine.observe(observed(pump=1, sequence=2, at=1.2), now=1.2)
    with pytest.raises(ValueError, match="Stale"):
        engine.sent(action, at=1.3, cts_at=1.3)
    assert not engine.history


def test_stale_state_cannot_accept_or_send_intent_and_old_observations_are_ignored():
    engine = CommandEngine()
    engine.observe(observed(sequence=5, at=1), now=1)
    engine.request(Control.PUMP1, PumpState.HIGH, now=1)
    assert engine.next_action(now=10) is None
    with pytest.raises(ValueError):
        engine.request(Control.PUMP1, PumpState.LOW, now=10)
    engine.observe(observed(pump=2, sequence=2, at=0.5), now=10)
    assert engine.state.sequence == 5


def test_disconnect_does_not_resurrect_cancelled_intent():
    engine = CommandEngine()
    engine.observe(observed(), now=1)
    intent = engine.request(Control.PUMP1, PumpState.HIGH, now=1)
    action = engine.next_action(now=1.1)
    engine.sent(action, at=1.1, cts_at=1.1)
    engine.cancel(Control.PUMP1)
    engine.suspend(now=1.2)
    assert engine.intent(intent.id).stage == Stage.CANCELLED
    assert engine.history[-1].result == Stage.CANCELLED


def test_physical_action_budget_prevents_unbounded_attempts():
    engine = CommandEngine(confirmation_guard=0.1, max_actions=1)
    engine.observe(observed(), now=1)
    intent = engine.request(Control.PUMP1, PumpState.HIGH, now=1)
    action = engine.next_action(now=1.1)
    engine.sent(action, at=1.1, cts_at=1.1)
    engine.observe(observed(pump=1, sequence=2, at=1.4), now=1.4)
    assert engine.next_action(now=1.5) is None
    assert engine.intent(intent.id).stage == Stage.FAILED
