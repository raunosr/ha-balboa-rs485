"""Analytical energy accounting with deterministic gaps and no hardware."""

from dataclasses import replace

import pytest

from balboa_rs485.energy import DEFAULT_POWERS, EnergyCounter, estimate, powers
from balboa_rs485.protocol.frames import Frame
from balboa_rs485.protocol.messages import HeatState, decode_message

from .test_state import observed


def spa(*, heat=HeatState.OFF, pump=0, caps=b"\x16\0\x01\0\0\0", **status):
    state = observed(pump=pump, capabilities=caps)
    return replace(
        state, status=replace(state.status, heat_state=heat, lights_raw=(0, 0), **status)
    )


def test_power_defaults_and_analytical_hour():
    profile = powers({})
    state = spa(heat=HeatState.HEATING, pump=1)
    assert estimate(state, profile) == 3370
    counter = EnergyCounter()
    for second in range(3601):
        counter.sample(second, estimate(state, profile), 1)
    assert counter.kwh == pytest.approx(3.37)
    assert counter.known_seconds == 3600
    assert counter.unknown_seconds == 0
    assert estimate(spa(heat=HeatState.HEATING, pump=0x2A), profile) == 6920
    assert estimate(spa(heat=HeatState.WAITING), profile) == 20
    assert estimate(spa(heat=HeatState.UNKNOWN), profile) is None


@pytest.mark.parametrize("value", [-1, 25001, float("nan"), float("inf"), True, "3000", None])
def test_invalid_profile(value):
    with pytest.raises(ValueError):
        powers({"heater_w": value})


def test_profile_keys_and_no_mutation():
    with pytest.raises(ValueError):
        powers({"unknown": 1})
    profile = powers({"heater_w": 2000})
    assert profile["heater_w"] == 2000
    assert DEFAULT_POWERS["heater_w"] == 3000
    assert estimate(spa(heat=HeatState.HEATING), powers({"heater_w": 0})) is None
    assert estimate(spa(), powers({"electronics_w": 0})) == 0


def test_dedicated_circulation_is_not_pump1_low_twice():
    state = spa(pump=1, circulation_pump=True)
    assert estimate(state, powers({})) == 370
    dedicated = spa(pump=1, circulation_pump=True, caps=b"\x16\0\x01\x80\0\0")
    assert estimate(dedicated, powers({})) == 620
    assert estimate(spa(caps=b"\x16\0\x01\x40\0\0"), powers({})) is None


@pytest.mark.parametrize("descriptor", [0x40, 0x50, 0xC0])
def test_explicit_circulation_configuration_resolves_only_the_ambiguous_load(descriptor):
    profile = powers({"electronics_w": 40})
    state = spa(caps=bytes([0x16, 0, 1, descriptor, 0, 0]), circulation_pump=False)
    assert estimate(state, profile) is None
    assert estimate(state, profile, circulation="auto") is None
    assert estimate(state, profile, circulation="absent") == 40
    assert estimate(state, profile, circulation="present") == 40
    active = replace(state, status=replace(state.status, circulation_pump=True))
    assert estimate(active, profile, circulation="absent") == 40
    assert estimate(active, profile, circulation="present") == 290
    assert estimate(active, powers({"circulation_w": 0}), circulation="present") is None


@pytest.mark.parametrize(
    "pump,heat,expected",
    [
        (0, HeatState.OFF, 40),
        (1, HeatState.OFF, 390),
        (1, HeatState.HEATING, 3390),
        (0x2A, HeatState.HEATING, 6940),
    ],
)
def test_shared_pump_circulation_uses_observed_loads_once(pump, heat, expected):
    state = spa(
        caps=b"\x16\0\x01\x50\0\0",
        pump=pump,
        heat=heat,
        circulation_pump=True,
        current_temperature=None,
    )
    assert estimate(state, powers({"electronics_w": 40}), circulation="absent") == expected
    assert not state.has_circulation_pump
    assert not state.pump1_is_circulation  # An accounting option does not change control policy.


def test_explicit_circulation_keeps_unknown_actuator_and_zero_power_guards():
    profile = powers({"electronics_w": 40})
    assert estimate(spa(heat=HeatState.UNKNOWN), profile, circulation="absent") is None
    assert estimate(spa(pump=3), profile, circulation="absent") is None
    state = spa(heat=HeatState.HEATING)
    assert estimate(state, powers({"heater_w": 0}), circulation="absent") is None


def test_configured_idle_load_accrues_energy_without_a_temperature_reading():
    state = spa(caps=b"\x16\0\x01\x50\0\0", current_temperature=None)
    profile = powers({"electronics_w": 40})
    counter = EnergyCounter()
    for second in range(3601):
        counter.sample(second, estimate(state, profile, circulation="absent"), 1)
    assert counter.kwh == pytest.approx(0.04)
    assert counter.known_seconds == 3600
    assert counter.unknown_seconds == 0


@pytest.mark.parametrize("value", ["invalid", True, 1, None])
def test_invalid_circulation_configuration_is_rejected(value):
    with pytest.raises(ValueError):
        estimate(spa(), powers({}), circulation=value)


def test_all_six_pump_ratings_and_unknown_states():
    state = spa(caps=b"\xaa\x82\x01\0\0\0", pumps_raw=(1, 2, 1, 2, 1, 2))
    assert estimate(state, powers({})) == 20 + 3 * 350 + 3 * 1300
    assert estimate(spa(pump=3), powers({})) is None
    assert estimate(spa(caps=b"\x03\0\x01\0\0\0"), powers({})) is None
    # Single-speed raw 1 and 2 are both normalized to ON, rated at high power.
    assert estimate(spa(pump=4), powers({})) == estimate(spa(pump=8), powers({})) == 1320


def test_lights_and_unconfigured_accessories_are_not_free():
    state = spa()
    absent = spa(caps=b"\x16\0\0\0\0\0")
    assert (
        estimate(replace(absent, status=replace(absent.status, lights_raw=(2, 0))), powers({}))
        is None
    )
    assert (
        estimate(replace(state, status=replace(state.status, lights_raw=(2, 0))), powers({})) == 30
    )
    assert (
        estimate(replace(state, status=replace(state.status, lights_raw=(1, 0))), powers({}))
        is None
    )
    state = spa(caps=b"\x16\0\x01\x01\x13\0")
    payload = bytearray(state.status.frame.payload)
    payload[13] = 4  # blower speed 1
    payload[15] = 25  # mister, auxiliary 1, auxiliary 2
    status = decode_message(Frame(255, 175, 19, bytes(payload)))
    state = replace(state, status=replace(status, heat_state=HeatState.OFF, lights_raw=(0, 0)))
    assert estimate(state, powers({})) is None
    assert (
        estimate(state, powers({"blower_w": 100, "mister_w": 10, "aux1_w": 5, "aux2_w": 5})) == 140
    )
    payload[13] = 12  # unsupported blower speed
    state = replace(state, status=decode_message(Frame(255, 175, 19, bytes(payload))))
    assert estimate(state, powers({})) is None


def test_gaps_epochs_duplicate_observations_and_profile_change():
    counter = EnergyCounter()
    counter.sample(0, 3600, 1)
    counter.sample(5, 0, 1)
    assert counter.kwh == 0.005
    counter.sample(5, 3600, 1)  # repeated sample cannot change baseline
    counter.sample(4, 3600, 1)  # out-of-order sample cannot change baseline
    counter.sample(10, 3600, 1)
    assert counter.kwh == 0.005
    counter.sample(30, 3600, 1)  # entire unobserved interval excluded
    counter.sample(35, 3600, 2)  # epoch boundary excluded
    counter.sample(40, None, 2)
    counter.sample(45, 3600, 2)
    assert counter.unknown_seconds == 35
    counter.sample(50, 3600, 2)
    assert counter.kwh == 0.01
    counter.break_interval()
    counter.sample(100, 7200, 2)
    counter.sample(105, 7200, 2)
    assert counter.kwh == 0.02
    assert counter.known_seconds == 20


def test_restore_never_backfills_restart_or_resets_total():
    counter = EnergyCounter(123, 100, 20)
    restored = EnergyCounter.restore(counter.record())
    restored.sample(5000, 3000, 1)
    assert restored.record() == counter.record()
    restored.sample(5006, 3000, 1)
    assert restored.kwh == pytest.approx(123.005)


@pytest.mark.parametrize(
    "record",
    [
        None,
        [],
        {},
        {"kwh": 1},
        {"kwh": -1, "known_seconds": 0, "unknown_seconds": 0},
        {"kwh": float("nan"), "known_seconds": 0, "unknown_seconds": 0},
        {"kwh": True, "known_seconds": 0, "unknown_seconds": 0},
        {"kwh": "1", "known_seconds": 0, "unknown_seconds": 0},
    ],
)
def test_corrupt_record_is_not_zero(record):
    with pytest.raises(ValueError):
        EnergyCounter.restore(record)


@pytest.mark.parametrize("now,watts", [(float("inf"), 1), (0, -1), (0, float("nan"))])
def test_invalid_sample(now, watts):
    with pytest.raises(ValueError):
        EnergyCounter().sample(now, watts, 1)
