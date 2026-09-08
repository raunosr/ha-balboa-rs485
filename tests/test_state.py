"""Observed values and capabilities, never optimistic command state."""

from dataclasses import replace

import pytest

from balboa_rs485.protocol.configuration import Configuration, Query
from balboa_rs485.protocol.frames import Frame
from balboa_rs485.protocol.messages import HeatMode, decode_message
from balboa_rs485.state.model import Control, PumpState, SpaState
from tools.simulator.server import configuration_fixture, load_status_fixture


def observed(
    *,
    pump=0,
    capabilities=b"\x06\0\x01\x82\0\0",
    sequence=1,
    epoch=1,
    at=1.0,
    available=True,
    **kwargs,
):
    payload = bytearray(load_status_fixture().payload)
    payload[11] = pump
    status = decode_message(Frame(255, 175, 19, bytes(payload)))
    config = Configuration(
        decode_message(configuration_fixture(Query.INFORMATION)),
        decode_message(Frame(10, 191, 46, capabilities)),
    )
    return SpaState(status, config, epoch, sequence, at, available, **kwargs)


def test_single_speed_raw_two_is_on_but_unknown_states_are_not_invented():
    state = observed(pump=0x08)
    assert state.value(Control.PUMP1) == PumpState.OFF
    assert state.value(Control.PUMP2) == PumpState.ON
    assert state.options(Control.PUMP1) == (PumpState.OFF, PumpState.LOW, PumpState.HIGH)
    assert state.options(Control.PUMP2) == (PumpState.OFF, PumpState.ON)
    assert state.options(Control.PUMP3) == ()
    assert observed(pump=3).value(Control.PUMP1) is None
    assert state.current_temperature == 27
    assert state.target_temperature == 38
    assert state.configuration.signature == replace(state, available=False).configuration.signature


def test_settings_lock_in_status_byte_21_inhibits_physical_controls():
    state = observed()
    data = bytearray(state.status.frame.payload)
    data[21] |= 8
    locked = replace(state, status=decode_message(Frame(255, 175, 19, bytes(data))))
    assert not locked.controls_safe
    with pytest.raises(ValueError, match="normal operating state"):
        locked.validate(Control.PUMP1, PumpState.LOW)


def filter_reminder_state():
    from .test_extended_messages import SETUP

    state = observed(setup=decode_message(SETUP))
    data = bytearray(state.status.frame.payload)
    data[0], data[1], data[6], data[9] = 0, 3, 4, 3
    data[18], data[19], data[21] = 1, 32, 0
    return replace(state, status=decode_message(Frame(255, 175, 19, bytes(data))))


def test_clean_filter_reminder_is_not_priming_fault_or_control_lock():
    state = filter_reminder_state()
    assert not state.priming and not state.hold
    assert state.controls_safe
    state.validate(Control.TARGET, 36.5)


@pytest.mark.parametrize(
    "index,value", [(0, 5), (1, 1), (1, 2), (1, 4), (6, 30), (18, 0), (18, 5), (9, 0x23), (21, 8)]
)
def test_filter_reminder_does_not_bypass_fault_unknown_state_or_lock(index, value):
    state = filter_reminder_state()
    data = bytearray(state.status.frame.payload)
    data[index] = value
    state = replace(state, status=decode_message(Frame(255, 175, 19, bytes(data))))
    assert not state.controls_safe
    with pytest.raises(ValueError, match="normal operating state"):
        state.validate(Control.TARGET, 36.5)


def test_filter_reminder_still_requires_available_state_and_observed_setup():
    state = filter_reminder_state()
    with pytest.raises(ValueError, match="normal operating state"):
        replace(state, available=False).validate(Control.TARGET, 36.5)
    with pytest.raises(ValueError, match="missing setup"):
        replace(state, setup=None).validate(Control.TARGET, 36.5)


def test_accessories_and_temperature_intent_require_unambiguous_observed_capabilities():
    from .test_extended_messages import SETUP

    state = observed(setup=decode_message(SETUP))
    assert state.options(Control.TARGET)[0] == 27
    assert state.options(Control.TARGET)[-1] == 40
    state.validate(Control.TARGET, 38.5)
    state.validate(Control.LIGHT1, True)
    assert state.value(Control.LIGHT1) is False
    assert state.options(Control.LIGHT2) == ()
    assert state.value(Control.BLOWER) == 0
    assert state.value(Control.HEAT_MODE) == HeatMode.READY
    for control, desired in [
        (Control.TARGET, 38.2),
        (Control.TARGET, 41),
        (Control.TARGET, True),
        (Control.PUMP1, "high"),
        (Control.LIGHT1, 1),
        (Control.BLOWER, True),
    ]:
        with pytest.raises(ValueError):
            state.validate(control, desired)
    raw = bytearray(state.status.frame.payload)
    raw[14] = 1  # Ruby/Python disagree whether this means ON.
    ambiguous = replace(state, status=decode_message(Frame(255, 175, 19, bytes(raw))))
    assert ambiguous.value(Control.LIGHT1) is None
    with pytest.raises(ValueError):
        ambiguous.validate(Control.LIGHT1, False)
