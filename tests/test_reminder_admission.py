"""Routine reminders must not be confused with priming or active fault states."""

from dataclasses import replace

import pytest

from balboa_rs485.protocol.frames import Frame
from balboa_rs485.protocol.messages import decode_message
from balboa_rs485.state.model import Control

from .test_state import filter_reminder_state


@pytest.mark.parametrize(
    "code,name",
    [(3, "change_filter"), (4, "clean_filter"), (9, "check_sanitizer"), (10, "check_ph")],
)
def test_documented_maintenance_reminders_allow_normal_controls_without_clearing(code, name):
    state = filter_reminder_state()
    payload = bytearray(state.status.frame.payload)
    payload[6] = code
    state = replace(state, status=decode_message(Frame(255, 175, 19, bytes(payload))))
    assert state.status.reminder == name
    assert not state.priming
    state.validate(Control.TARGET, 36.5)
    state.validate(Control.LIGHT1, True)
    assert state.status.reminder_code == code  # Admission does not acknowledge anything.


@pytest.mark.parametrize(
    "index,value", [(0, 1), (1, 1), (1, 2), (6, 30), (6, 255), (18, 0), (18, 5), (9, 0x23), (21, 8)]
)
def test_change_filter_reminder_never_bypasses_real_faults_priming_or_locks(index, value):
    state = filter_reminder_state()
    payload = bytearray(state.status.frame.payload)
    payload[6] = 3
    payload[index] = value
    state = replace(state, status=decode_message(Frame(255, 175, 19, bytes(payload))))
    assert not state.controls_safe
    with pytest.raises(ValueError):
        state.validate(Control.LIGHT1, True)
