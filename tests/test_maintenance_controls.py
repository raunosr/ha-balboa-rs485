"""Maintenance actions are explicit and cannot bypass priming, faults or locks."""

from dataclasses import replace

import pytest

from balboa_rs485.command.engine import Stage
from balboa_rs485.protocol.frames import Frame
from balboa_rs485.protocol.messages import decode_message
from balboa_rs485.state.model import Control, PumpState

from .test_session_runner import lab
from .test_state import observed


async def test_hold_can_be_entered_and_left_but_other_controls_are_blocked_in_hold():
    async with lab() as (simulator, runtime):
        intent = runtime.request(Control.HOLD, True)
        assert (await runtime.wait_for_intent(intent.id, timeout=2)).stage == Stage.VERIFIED
        assert runtime.state.status.hold
        with pytest.raises(ValueError):
            runtime.request(Control.PUMP1, PumpState.HIGH)
        intent = runtime.request(Control.HOLD, False)
        assert (await runtime.wait_for_intent(intent.id, timeout=2)).stage == Stage.VERIFIED
        assert not runtime.state.status.hold
        assert simulator.physical_commands == 2


async def test_normal_operation_only_exits_hold_and_soak_confirms_all_supported_pumps_off():
    async with lab() as (simulator, runtime):
        intent = runtime.request(Control.HOLD, True)
        await runtime.wait_for_intent(intent.id, timeout=2)
        intent = runtime.request(Control.NORMAL_OPERATION, True)
        assert (await runtime.wait_for_intent(intent.id, timeout=2)).stage == Stage.VERIFIED
        assert not runtime.state.status.hold
        intent = runtime.request(Control.PUMP1, PumpState.HIGH)
        await runtime.wait_for_intent(intent.id, timeout=2)
        intent = runtime.request(Control.SOAK, True)
        assert (await runtime.wait_for_intent(intent.id, timeout=2)).stage == Stage.VERIFIED
        assert not any(simulator.pump_states)
        assert simulator.physical_records[-1].frame.payload == b"\x1d\0"


@pytest.mark.parametrize("byte,value", [(0, 1), (0, 0x17), (1, 1), (1, 2), (9, 0x21), (21, 8)])
@pytest.mark.parametrize("control", [Control.HOLD, Control.NORMAL_OPERATION, Control.SOAK])
def test_maintenance_controls_never_bypass_unknown_mode_priming_faults_or_locks(
    byte, value, control
):
    state = observed()
    raw = bytearray(state.status.frame.payload)
    raw[byte] = value
    state = replace(state, status=decode_message(Frame(255, 175, 19, bytes(raw))))
    assert not state.safe_for(control)
    with pytest.raises(ValueError):
        state.validate(control, True)


async def test_lost_hold_confirmation_uses_fresh_observed_hold_without_toggling_back():
    async with lab(scenario="lost-status-after-command") as (simulator, runtime):
        intent = runtime.request(Control.HOLD, True)
        assert (await runtime.wait_for_intent(intent.id, timeout=4)).stage == Stage.VERIFIED
        assert runtime.state.hold
        assert simulator.physical_commands == 1


@pytest.mark.parametrize("code", [4, 9, 10])
async def test_only_known_reminders_can_be_acknowledged_without_clearing_fault_history(code):
    async with lab() as (simulator, runtime):
        simulator.reminder_code = code
        await runtime.connection.wait_for(
            lambda _: runtime.state.status.reminder_code == code, timeout=2
        )
        original_fault = runtime.state.fault
        intent = runtime.request(Control.ACK_REMINDER, True)
        assert (await runtime.wait_for_intent(intent.id, timeout=2)).stage == Stage.VERIFIED
        assert runtime.state.status.reminder == "none"
        assert runtime.state.fault == original_fault
        assert simulator.physical_commands == 1


@pytest.mark.parametrize("code", [30, 255])
def test_fault_or_unknown_reminder_is_never_acknowledged(code):
    state = observed()
    raw = bytearray(state.status.frame.payload)
    raw[1], raw[6], raw[18] = 3, code, 1
    state = replace(state, status=decode_message(Frame(255, 175, 19, bytes(raw))))
    with pytest.raises(ValueError):
        state.validate(Control.ACK_REMINDER, True)
