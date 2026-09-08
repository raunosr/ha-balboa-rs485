"""Boundary validation protects against unsupported physical writes."""

from dataclasses import replace

import pytest

from balboa_rs485.command.engine import CommandEngine, Stage
from balboa_rs485.protocol.commands import ToggleItem, pump_toggle, set_temperature, toggle
from balboa_rs485.protocol.frames import Frame
from balboa_rs485.protocol.messages import HeatMode, TemperatureUnit, decode_message
from balboa_rs485.state.model import Control, PumpState
from tools.smoke_client.controls import parse_command, run_commands, validate_endpoint
from tools.smoke_client.interactive import run_interactive

from .test_extended_messages import SETUP
from .test_state import observed


@pytest.mark.parametrize("index", range(1, 7))
def test_known_pump_item_encoding(index):
    assert pump_toggle(index) == Frame(10, 191, 17, bytes((index + 3, 0)))


@pytest.mark.parametrize("index", [0, 7, True, 1.5])
def test_arbitrary_pump_item_rejected(index):
    with pytest.raises(ValueError):
        pump_toggle(index)


@pytest.mark.parametrize(
    "value,unit",
    [
        (True, TemperatureUnit.CELSIUS),
        (float("nan"), TemperatureUnit.CELSIUS),
        (38.2, TemperatureUnit.CELSIUS),
        (41, TemperatureUnit.CELSIUS),
        (100.5, TemperatureUnit.FAHRENHEIT),
        (38, "C"),
    ],
)
def test_temperature_wire_encoding_rejects_invalid_or_ambiguous_values(value, unit):
    with pytest.raises(ValueError):
        set_temperature(value, unit)


def test_fahrenheit_encoding_and_typed_toggle_only():
    assert set_temperature(100, TemperatureUnit.FAHRENHEIT) == Frame(10, 191, 32, b"\x64")
    assert toggle(ToggleItem.HEAT_MODE).payload == b"\x51\0"
    with pytest.raises(ValueError):
        toggle(255)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"confirmation_guard": 0},
        {"confirmation_timeout": 0.1},
        {"confirmation_timeout": float("nan")},
        {"resync_settle": -1},
        {"max_actions": 0},
        {"max_actions": True},
    ],
)
def test_invalid_command_safety_timing_is_rejected(kwargs):
    with pytest.raises(ValueError):
        CommandEngine(**kwargs)


def test_ready_in_rest_uses_observed_rest_intermediate_before_ready():
    initial = observed()
    raw = bytearray(initial.status.frame.payload)
    raw[5] = 2
    state = replace(initial, status=decode_message(Frame(255, 175, 19, bytes(raw))))
    engine = CommandEngine(confirmation_guard=0.1)
    engine.observe(state, now=1)
    intent = engine.request(Control.HEAT_MODE, HeatMode.READY, now=1)
    action = engine.next_action(now=1.1)
    assert action.expected == HeatMode.REST
    engine.sent(action, at=1.1, cts_at=1.1)
    with pytest.raises(RuntimeError):
        engine.sent(action, at=1.2, cts_at=1.2)
    assert engine.history[0].latency is None
    assert engine.history[0].stages[-1][0] == Stage.WAITING_FOR_STATE
    raw[5] = 1
    engine.observe(
        replace(
            state,
            status=decode_message(Frame(255, 175, 19, bytes(raw))),
            sequence=2,
            observed_at=1.4,
        ),
        now=1.4,
    )
    assert engine.history[0].stages[-1][0] == Stage.VERIFIED
    assert engine.history[0].latency == pytest.approx(0.3)
    assert engine.next_action(now=1.5).expected == HeatMode.READY
    assert engine.intent(intent.id).stage == Stage.WAITING_FOR_BUS


def test_state_metadata_and_low_range_fahrenheit_are_observed_not_defaults():
    state = observed(setup=decode_message(SETUP))
    assert state.model == "BP SIM" and state.voltage == 240
    assert state.heater_type == "standard" and state.dip_settings == b"\0\x01"
    assert not state.priming and not state.hold and state.filter_running == (False, False)
    raw = bytearray(state.status.frame.payload)
    raw[0], raw[1], raw[9], raw[10] = 5, 1, 12, 0
    changed = replace(state, status=decode_message(Frame(255, 175, 19, bytes(raw))))
    assert changed.priming and changed.hold and changed.filter_running == (True, True)
    assert changed.options(Control.TARGET) == tuple(range(50, 100))
    with pytest.raises(ValueError):
        changed.validate(Control.PUMP1, PumpState.HIGH)
    assert observed().options(Control.TARGET) == ()
    assert observed().value(Control.PUMP3) is None
    assert observed(capabilities=bytes(6)).options(Control.BLOWER) == ()


@pytest.mark.parametrize(
    "line,control,value",
    [
        ("blower 2", Control.BLOWER, 2),
        ("heat_mode rest", Control.HEAT_MODE, HeatMode.REST),
        ("heat_mode ready", Control.HEAT_MODE, HeatMode.READY),
        ("high_range low", Control.HIGH_RANGE, False),
        ("aux1 on", Control.AUX1, True),
    ],
)
def test_command_parser_returns_typed_desired_values(line, control, value):
    assert parse_command(line) == (control, value)


@pytest.mark.parametrize("line", ["heat_mode unknown", "light1 high", "pump1 2", "toggle 4"])
def test_cli_never_accepts_raw_toggle_or_ambiguous_intent(line):
    with pytest.raises(ValueError):
        parse_command(line)


async def test_control_cli_requires_supported_mode_and_finite_deadline():
    with pytest.raises(ValueError):
        validate_endpoint("127.0.0.1", "auto")
    with pytest.raises(ValueError):
        await run_commands("127.0.0.1", 8899, "classic-rs485", [], float("nan"))
    with pytest.raises(ValueError):
        run_interactive("127.0.0.1", 8899, "classic-rs485", 0)
