"""Native pump intent budgets and replacement at the real recovery boundary."""

import asyncio
from dataclasses import replace

import pytest

from balboa_rs485.command.engine import CommandEngine, Stage
from balboa_rs485.runtime import SpaRuntime
from balboa_rs485.state.model import Control, PumpState
from balboa_rs485.transport.policy import Mode
from tools.simulator.server import Simulator

from .test_connection import FAST
from .test_state import observed


@pytest.mark.parametrize("mode", [Mode.CLASSIC_RS485, Mode.CHANNEL_RS485, Mode.DIRECT_RS485_TCP])
async def test_changed_pump_target_during_ambiguous_recovery_is_retained_not_rejected(mode):
    engine = CommandEngine(confirmation_guard=0.02, confirmation_timeout=0.15, resync_settle=0.06)
    async with Simulator(
        port=0, interval=0.03, control_lab=True, channel_lab=mode == Mode.CHANNEL_RS485
    ) as simulator:
        simulator.pump_states[0] = 2
        simulator.drop_pump_commands = 1
        async with SpaRuntime(
            "127.0.0.1",
            simulator.port,
            mode=mode,
            allow_unarbitrated_writes=mode == Mode.DIRECT_RS485_TCP,
            timing=FAST,
            engine=engine,
        ) as runtime:
            await runtime.connection.wait_for(lambda s: s.available, timeout=3)
            first = runtime.request(Control.PUMP1, PumpState.LOW)
            await runtime.connection.wait_for(
                lambda s: not s.available and bool(engine.history), timeout=3
            )
            assert engine.history[0].result == Stage.FAILED
            # This is the production failure boundary: fresh traffic alone did
            # not confirm the command; the old goal is still queued for recovery.
            final = runtime.request(Control.PUMP1, PumpState.OFF, replace_pending=True)
            assert engine.intent(first.id).stage == Stage.SUPERSEDED
            assert (await runtime.wait_for_intent(final.id, timeout=4)).stage == Stage.VERIFIED
            assert simulator.pump_states[0] == 0
            assert simulator.physical_commands == 2
            assert engine.history[1].action.epoch > engine.history[0].action.epoch


@pytest.mark.parametrize("delay", [0.08, 0.4])
async def test_delayed_application_does_not_replay_a_toggle_and_latest_goal_wins(delay):
    engine = CommandEngine(confirmation_guard=0.02, confirmation_timeout=0.15, resync_settle=0.2)
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        simulator.pump_states[0] = 2
        simulator.pump_command_delay = delay
        async with SpaRuntime(
            "127.0.0.1",
            simulator.port,
            mode=Mode.DIRECT_RS485_TCP,
            allow_unarbitrated_writes=True,
            timing=FAST,
            engine=engine,
        ) as runtime:
            await runtime.connection.wait_for(lambda s: s.available, timeout=3)
            first = runtime.request(Control.PUMP1, PumpState.LOW)
            await runtime.connection.wait_for(lambda _: engine.busy, timeout=3)
            simulator.pump_command_delay = 0
            # HIGH -> OFF already accepted by the peer; OFF is now the latest
            # desired state, so it must not be toggled back on after reconnect.
            final = runtime.request(Control.PUMP1, PumpState.OFF, replace_pending=True)
            assert (await runtime.wait_for_intent(final.id, timeout=4)).stage == Stage.VERIFIED
            assert engine.intent(first.id).stage == Stage.SUPERSEDED
            assert simulator.physical_commands == 1
            assert simulator.pump_states[0] == 0


async def test_persistent_write_loss_with_healthy_reads_stops_at_the_deadline():
    engine = CommandEngine(confirmation_guard=0.02, confirmation_timeout=0.15, resync_settle=0.06)
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        simulator.drop_pump_commands = 99
        async with SpaRuntime(
            "127.0.0.1",
            simulator.port,
            mode=Mode.DIRECT_RS485_TCP,
            allow_unarbitrated_writes=True,
            timing=FAST,
            engine=engine,
        ) as runtime:
            await runtime.connection.wait_for(lambda s: s.available, timeout=3)
            intent = runtime.request(
                Control.PUMP1, PumpState.HIGH, deadline=asyncio.get_running_loop().time() + 1.3
            )
            result = await runtime.wait_for_intent(intent.id)
            assert result.stage == Stage.FAILED
            assert "deadline" in result.reason.lower()
            assert simulator.physical_commands <= engine.max_actions
            count = simulator.physical_commands
            await runtime.connection.wait_for(
                lambda s: s.available and engine.resync_epoch is None, timeout=3
            )
            light = runtime.request(Control.LIGHT1, True)
            assert (await runtime.wait_for_intent(light.id, timeout=3)).stage == Stage.VERIFIED
            assert simulator.physical_commands == count + 1
            assert simulator.pump_states[0] == 0


def test_deadline_and_invalid_parameters_cannot_weaken_admission():
    engine = CommandEngine()
    engine.observe(observed(), now=1)
    for kwargs in ({"deadline": 1}, {"deadline": float("inf")}, {"defer_for": -1}):
        with pytest.raises(ValueError):
            engine.request(Control.PUMP1, PumpState.HIGH, now=1, **kwargs)
    intent = engine.request(Control.PUMP1, PumpState.HIGH, now=1, deadline=2)
    assert engine.next_action(now=1.1) is None
    assert engine.intent(intent.id).stage == Stage.FAILED


def test_deadline_during_inflight_keeps_the_safety_receipt_and_terminal_failure():
    engine = CommandEngine(confirmation_timeout=1)
    engine.observe(observed(), now=1)
    item = engine.request(Control.PUMP1, PumpState.HIGH, now=1, deadline=2.2)
    action = engine.next_action(now=1.1)
    engine.sent(action, at=1.1, cts_at=1.1)
    # Cancellation of the caller must not remove the in-flight wire receipt.
    engine.cancel(Control.PUMP1, now=1.2)
    assert engine.busy
    engine.tick(now=2.3)
    assert engine.intent(item.id).stage == Stage.CANCELLED
    assert engine.resync_epoch == 1


def test_late_tx_receipt_is_kept_even_after_goal_deadline():
    engine = CommandEngine(confirmation_timeout=1)
    engine.observe(observed(), now=1)
    item = engine.request(Control.PUMP1, PumpState.HIGH, now=1, deadline=3)
    action = engine.next_action(now=1.2)
    engine.sent(action, at=3.1, cts_at=1.2)
    assert engine.intent(item.id).stage == Stage.FAILED
    assert engine.pending_transaction.action == action
    engine.tick(now=4.2)
    assert engine.resync_epoch == 1


def test_intent_timeline_is_bounded_and_includes_duplicates_without_transmission():
    engine = CommandEngine()
    engine.observe(observed(), now=1)
    item = engine.request(Control.PUMP1, PumpState.HIGH, now=1, deadline=20)
    for _ in range(240):
        engine.joined(item.id, now=1.1)
    assert len(engine.events) == 200
    assert all(e.kind == "joined" and e.observed == PumpState.OFF for e in engine.events)
    assert not engine.history
    assert engine.latest(Control.PUMP1).deadline == 20
    engine.cancel(Control.PUMP1)
    revision = engine.revision
    engine.joined(item.id, now=1.2)
    engine.joined(-1, now=1.2)
    engine.cancel(Control.PUMP1)
    assert engine.revision == revision


def test_deadline_expires_without_discarding_an_ambiguous_sent_toggle():
    engine = CommandEngine(confirmation_timeout=1)
    engine.observe(observed(), now=1)
    intent = engine.request(Control.PUMP1, PumpState.HIGH, now=1, deadline=2.5)
    action = engine.next_action(now=1.1)
    engine.sent(action, at=1.1, cts_at=1.1)
    engine.tick(now=2.6)
    assert engine.intent(intent.id).stage == Stage.FAILED
    assert "deadline" in engine.intent(intent.id).reason.lower()
    assert engine.resync_epoch == 1
    engine.observe(observed(pump=1, epoch=2, sequence=1, at=3), now=3)
    engine.observe(observed(pump=1, epoch=2, sequence=2, at=4), now=4)
    assert engine.next_action(now=4) is None
    assert engine.intent(intent.id).stage == Stage.FAILED


def test_replacement_preserves_deadline_and_spent_action_budget():
    engine = CommandEngine(confirmation_timeout=1, max_actions=1)
    engine.observe(observed(), now=1)
    first = engine.request(Control.PUMP1, PumpState.HIGH, now=1, deadline=10)
    action = engine.next_action(now=1.1)
    engine.sent(action, at=1.1, cts_at=1.1)
    final = engine.request(Control.PUMP1, PumpState.OFF, now=1.2, deadline=20, replace_pending=True)
    assert final.deadline == first.deadline
    assert engine.busy
    engine.observe(observed(pump=1, sequence=2, at=1.5), now=1.5)
    assert engine.next_action(now=1.6) is None
    assert engine.intent(final.id).stage == Stage.FAILED
    assert "budget" in engine.intent(final.id).reason


def test_unsent_slider_steps_coalesce_but_last_target_and_history_survive():
    engine = CommandEngine()
    engine.observe(observed(), now=1)
    first = engine.request(Control.PUMP1, PumpState.HIGH, now=1, deadline=20, defer_for=0.15)
    assert engine.next_action(now=1.05) is None
    final = engine.request(
        Control.PUMP1, PumpState.LOW, now=1.06, deadline=20, defer_for=0.15, replace_pending=True
    )
    assert engine.next_action(now=1.2) is None
    assert engine.next_action(now=1.22).intent.id == final.id
    assert engine.intent(first.id).stage == Stage.SUPERSEDED
    assert any(e.intent_id == first.id and e.stage == Stage.SUPERSEDED for e in engine.events)
    assert engine.state.value(Control.PUMP1) == PumpState.OFF


def test_recovery_does_not_admit_a_new_unrelated_or_invalid_goal():
    engine = CommandEngine()
    engine.observe(observed(), now=1)
    engine.request(Control.PUMP1, PumpState.HIGH, now=1, deadline=20)
    engine.suspend(now=2)
    with pytest.raises(ValueError):
        engine.request(Control.PUMP2, PumpState.HIGH, now=2, replace_pending=True)
    with pytest.raises(ValueError):
        engine.request(Control.PUMP1, True, now=2, replace_pending=True)
    engine.observe(replace(observed(at=2), available=False), now=2)
    assert engine.next_action(now=2) is None
