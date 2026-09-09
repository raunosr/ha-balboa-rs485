"""Acknowledge one displayed reminder, never drain a maintenance queue."""

from dataclasses import replace

import pytest

from balboa_rs485.command.engine import CommandEngine, Stage
from balboa_rs485.protocol.frames import Frame
from balboa_rs485.protocol.messages import decode_message
from balboa_rs485.state.model import Control

from .test_session_runner import lab
from .test_state import filter_reminder_state


@pytest.mark.parametrize("next_code", [4, 9, 10])
async def test_acknowledging_one_reminder_preserves_next_and_allows_other_controls(next_code):
    async with lab() as (simulator, runtime):
        simulator.reminder_code = 3
        simulator.reminder_queue = [next_code]
        await runtime.connection.wait_for(
            lambda _: runtime.state.status.reminder_code == 3, timeout=2
        )
        intent = runtime.request(Control.ACK_REMINDER, True)
        result = await runtime.wait_for_intent(intent.id, timeout=2)
        assert result.stage == Stage.VERIFIED, (result, runtime.engine.history)
        assert simulator.reminder_code == next_code
        assert simulator.physical_commands == 1
        assert runtime.connection.snapshot.epoch == 1
        light = runtime.request(Control.LIGHT1, True)
        assert (await runtime.wait_for_intent(light.id, timeout=2)).stage == Stage.VERIFIED
        assert simulator.reminder_code == next_code
        assert simulator.physical_commands == 2


def reminder_state(code=3, *, at=1.0, sequence=1, epoch=1, **overrides):
    state = filter_reminder_state()
    payload = bytearray(state.status.frame.payload)
    payload[6] = code
    for index, value in overrides.items():
        payload[int(index)] = value
    return replace(
        state,
        status=decode_message(Frame(255, 175, 19, bytes(payload))),
        observed_at=at,
        sequence=sequence,
        epoch=epoch,
    )


def ack_engine():
    engine = CommandEngine()
    engine.observe(reminder_state(), now=1)
    intent = engine.request(Control.ACK_REMINDER, True, now=1)
    action = engine.next_action(now=1)
    engine.sent(action, at=1.01, cts_at=1)
    return engine, intent


@pytest.mark.parametrize("failure", ["timeout", "disconnect"])
def test_ambiguous_ack_is_terminal_even_after_fresh_reconnect(failure):
    engine, intent = ack_engine()
    if failure == "timeout":
        engine.tick(now=5.1)
    else:
        engine.suspend(now=1.1)
    assert engine.intent(intent.id).stage == Stage.FAILED
    assert "not retried" in engine.intent(intent.id).reason
    engine.observe(reminder_state(4, at=6, sequence=1, epoch=2), now=6)
    engine.observe(reminder_state(4, at=7, sequence=2, epoch=2), now=7)
    assert engine.next_action(now=7) is None
    assert len(engine.history) == 1


def test_changed_reminder_before_transmission_is_not_acknowledged():
    engine = CommandEngine()
    engine.observe(reminder_state(), now=1)
    intent = engine.request(Control.ACK_REMINDER, True, now=1)
    engine.observe(reminder_state(4, at=2, sequence=2), now=2)
    assert engine.next_action(now=2) is None
    assert engine.intent(intent.id).stage == Stage.CANCELLED
    assert not engine.history


@pytest.mark.parametrize("overrides", [{}, {"1": 2}, {"18": 5}, {"9": 0x23}, {"21": 8}])
def test_unknown_fault_or_lock_transition_is_not_ack_success(overrides):
    engine, intent = ack_engine()
    state = reminder_state(2 if not overrides else 4, at=2, sequence=2, **overrides)
    engine.observe(state, now=2)
    assert engine.intent(intent.id).stage == Stage.WAITING_FOR_STATE
    with pytest.raises(ValueError):
        engine.request(Control.LIGHT1, True, now=2)
    engine.tick(now=5.1)
    assert engine.intent(intent.id).stage == Stage.FAILED
    assert len(engine.history) == 1


async def test_lost_ack_confirmation_does_not_clear_next_reminder_after_reconnect():
    async with lab(scenario="lost-status-after-command") as (simulator, runtime):
        simulator.reminder_code = 3
        simulator.reminder_queue = [4]
        await runtime.connection.wait_for(
            lambda _: runtime.state.status.reminder_code == 3, timeout=2
        )
        intent = runtime.request(Control.ACK_REMINDER, True)
        assert (await runtime.wait_for_intent(intent.id, timeout=2)).stage == Stage.FAILED
        await runtime.connection.wait_for(
            lambda s: s.epoch > 1 and s.available and runtime.engine.resync_epoch is None,
            timeout=3,
        )
        light = runtime.request(Control.LIGHT1, True)
        assert (await runtime.wait_for_intent(light.id, timeout=2)).stage == Stage.VERIFIED
        assert simulator.reminder_code == 4
        assert simulator.physical_commands == 2  # One ACK, then the unrelated light command.
