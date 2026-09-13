"""Priming allows explicit pump control, not heating or old-intent replay."""

from dataclasses import replace

import pytest

from balboa_rs485.command.engine import CommandEngine, Stage
from balboa_rs485.protocol.messages import decode_message
from balboa_rs485.runtime import SpaRuntime
from balboa_rs485.state.model import Control, PumpState
from balboa_rs485.transport.policy import Mode
from tools.simulator.server import Simulator

from .test_connection import FAST
from .test_state import observed


def priming_state(*, changes=(), **kwargs):
    base = observed(capabilities=b"\x0a\0\x01\0\0\0", **kwargs)
    data = bytearray(base.status.frame.payload)
    data[1], data[2], data[18] = 1, 255, 2
    for index, value in changes:
        data[index] = value
    return replace(base, status=decode_message(replace(base.status.frame, payload=bytes(data))))


@pytest.mark.parametrize(
    "control,desired", [(Control.PUMP1, PumpState.LOW), (Control.LIGHT1, True)]
)
def test_priming_allows_known_manual_control_without_normalizing_status(control, desired):
    state = priming_state()
    state.validate(control, desired)
    assert state.priming and state.current_temperature is None
    assert not state.controls_safe  # Heating/session admission is NOT relaxed.


@pytest.mark.parametrize(
    "control",
    [
        c
        for c in Control
        if not c.value.startswith("pump") and c not in (Control.LIGHT1, Control.LIGHT2)
    ],
)
def test_priming_does_not_allow_other_controls(control):
    assert not priming_state().safe_for(control)


@pytest.mark.parametrize(
    "changes", [((0, 5),), ((0, 1),), ((1, 2),), ((9, 0x23),), ((21, 8),), ((18, 5),)]
)
@pytest.mark.parametrize("control", [Control.PUMP1, Control.LIGHT1])
def test_priming_exception_keeps_other_operating_and_lock_guards(changes, control):
    assert not priming_state(changes=changes).safe_for(control)
    assert not priming_state(available=False).safe_for(control)


def test_priming_light_rejects_dedicated_circulation_configuration():
    state = priming_state()
    assert not replace(state, configuration=observed().configuration).safe_for(Control.LIGHT1)


def test_priming_control_still_requires_fresh_state_and_observed_confirmation():
    engine = CommandEngine(confirmation_guard=0.1)
    engine.observe(priming_state(), now=1)
    item = engine.request(Control.PUMP1, PumpState.LOW, now=1)
    assert engine.next_action(now=100) is None  # A known but old state cannot authorize TX.
    engine.observe(priming_state(sequence=2, at=100), now=100)
    action = engine.next_action(now=100)
    engine.sent(action, at=100, cts_at=100)
    assert engine.intent(item.id).stage == Stage.WAITING_FOR_STATE
    engine.observe(priming_state(sequence=3, at=100.2), now=100.2)
    assert engine.intent(item.id).stage == Stage.WAITING_FOR_STATE
    engine.observe(priming_state(pump=1, sequence=4, at=100.3), now=100.3)
    assert engine.intent(item.id).stage == Stage.VERIFIED


def test_priming_pump_keeps_inflight_ambiguity_but_does_not_replay_after_reconnect():
    engine = CommandEngine(confirmation_guard=0.1, resync_settle=0.1)
    engine.observe(priming_state(), now=1)
    item = engine.request(Control.PUMP1, PumpState.HIGH, now=1)
    action = engine.next_action(now=1)
    engine.sent(action, at=1, cts_at=1)
    engine.suspend(now=1.1)
    assert engine.resync_epoch == 1
    engine.observe(priming_state(pump=1, epoch=2, at=1.2), now=1.2)
    engine.observe(priming_state(pump=1, epoch=2, sequence=2, at=1.5), now=1.5)
    assert engine.intent(item.id).stage == Stage.CANCELLED
    assert engine.next_action(now=1.5) is None
    assert len(engine.history) == 1


@pytest.mark.parametrize("transition", ["enter", "exit", "reconnect"])
def test_priming_transition_cancels_queued_intents(transition):
    engine = CommandEngine()
    initial = observed() if transition == "enter" else priming_state()
    engine.observe(initial, now=1)
    item = engine.request(Control.PUMP1, PumpState.LOW, now=1, defer_for=2)
    changed = (
        observed(sequence=2, at=1.5)
        if transition == "exit"
        else priming_state(sequence=2, at=1.5, epoch=2 if transition == "reconnect" else 1)
    )
    engine.observe(changed, now=1.5)
    assert engine.intent(item.id).stage == Stage.CANCELLED
    assert engine.next_action(now=3) is None


@pytest.mark.parametrize("mode", [Mode.CLASSIC_RS485, Mode.CHANNEL_RS485, Mode.DIRECT_RS485_TCP])
async def test_priming_manual_pump_and_light_confirm_over_tcp_without_reconnect(mode, monkeypatch):
    from tools.simulator import server

    original = server.load_status_fixture()
    data = bytearray(original.payload)
    data[1], data[2], data[18] = 1, 255, 2
    data[10] &= ~0x30
    monkeypatch.setattr(
        server, "load_status_fixture", lambda: replace(original, payload=bytes(data))
    )
    async with Simulator(
        port=0, interval=0.03, control_lab=True, channel_lab=mode == Mode.CHANNEL_RS485
    ) as simulator:
        simulator.dedicated_circulation_pump = False
        async with SpaRuntime(
            "127.0.0.1",
            simulator.port,
            mode=mode,
            allow_unarbitrated_writes=mode.direct,
            timing=FAST,
            engine=CommandEngine(confirmation_guard=0.02),
        ) as runtime:
            await runtime.connection.wait_for(lambda s: s.available, timeout=3)
            for control, desired in [
                (Control.PUMP1, PumpState.LOW),
                (Control.PUMP1, PumpState.HIGH),
                (Control.PUMP1, PumpState.OFF),
                (Control.LIGHT1, True),
                (Control.LIGHT1, False),
            ]:
                item = runtime.request(control, desired)
                assert (await runtime.wait_for_intent(item.id, timeout=3)).stage == Stage.VERIFIED
            assert runtime.state.priming
            assert simulator.physical_commands == 5
            assert simulator.stats.connections == 1
            assert runtime.connection.snapshot.recoveries == 0
            for control, desired in [(Control.TARGET, 36.5), (Control.NORMAL_OPERATION, True)]:
                with pytest.raises(ValueError, match="priming"):
                    runtime.request(control, desired)
            assert simulator.physical_commands == 5
