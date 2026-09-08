"""Range-aware intent preserves both device profiles and the heating policy."""

import json
from dataclasses import replace

import pytest

from balboa_rs485.protocol.messages import HeatMode, TemperatureUnit
from balboa_rs485.range_session import RangeSession, RangeStep, SessionConflict
from balboa_rs485.session import SessionPhase
from balboa_rs485.state.model import Control

from .test_session import spa


def observed(*, high=False, target=26.0, mode=HeatMode.REST, current=27.0):
    state = spa(target=target, current=current)
    return replace(state, status=replace(state.status, high_range=high, heat_mode=mode))


def test_bathing_session_captures_high_before_override_and_restores_all_owned_fields():
    session = RangeSession.start(now=1000, end=4600, minimum_c=36.5, state=observed())
    assert session.goal(observed()) == (Control.HIGH_RANGE, True)
    high = observed(high=True, target=35)
    session = session.reconcile(now=1001, state=high)
    assert session.original_high == 35
    assert session.goal(high) == (Control.TARGET, 36.5)
    warm = observed(high=True, target=36.5)
    session = session.reconcile(now=1002, state=warm)
    assert session.goal(warm) == (Control.HEAT_MODE, HeatMode.READY)
    ready = observed(high=True, target=36.5, mode=HeatMode.READY)
    session = session.reconcile(now=1003, state=ready)
    assert session.goal(ready) == (Control.TARGET, 36.5)
    session = session.reconcile(now=4600, state=ready)
    assert session.phase == SessionPhase.RESTORING
    assert session.goal(ready) == (Control.TARGET, 35)
    restored_high = observed(high=True, target=35, mode=HeatMode.READY)
    session = session.reconcile(now=4601, state=restored_high)
    assert session.goal(restored_high) == (Control.HIGH_RANGE, False)
    low = observed(mode=HeatMode.READY)
    session = session.reconcile(now=4602, state=low)
    assert session.goal(low) == (Control.HEAT_MODE, HeatMode.REST)
    assert session.reconcile(now=4603, state=observed()) is None


def test_each_checkpoint_round_trips_without_reheating_an_expired_session():
    first = RangeSession.start(now=1000, end=4600, minimum_c=36.5, state=observed())
    checkpoints = [first]
    for state in (
        observed(high=True, target=35),
        observed(high=True, target=36.5),
        observed(high=True, target=36.5, mode=HeatMode.READY),
    ):
        checkpoints.append(checkpoints[-1].reconcile(now=1001, state=state))
    checkpoints.append(checkpoints[-1].cancel())
    checkpoints.append(
        checkpoints[-1].reconcile(
            now=4700, state=observed(high=True, target=35, mode=HeatMode.READY)
        )
    )
    checkpoints.append(checkpoints[-1].reconcile(now=4700, state=observed(mode=HeatMode.READY)))
    for session in checkpoints:
        loaded = RangeSession.from_record(json.loads(json.dumps(session.to_record())))
        assert loaded == session
        expired = loaded.reconcile(now=4700, state=None)
        assert expired.phase == SessionPhase.RESTORING
        assert expired.reconcile(now=1000, state=None) == expired
    uncaptured = RangeSession.from_record(first.to_record()).reconcile(
        now=4700, state=observed(high=True, target=35)
    )
    assert uncaptured.original_high is None
    assert uncaptured.goal(observed(high=True, target=35)) == (Control.HIGH_RANGE, False)


def test_manual_target_release_keeps_range_and_mode_cleanup_and_expiry_is_final():
    session = RangeSession.start(now=1000, end=4600, minimum_c=36.5, state=observed())
    for state in (
        observed(high=True, target=35),
        observed(high=True, target=36.5),
        observed(high=True, target=36.5, mode=HeatMode.READY),
    ):
        session = session.reconcile(now=1001, state=state)
    assert session.adjust(now=2000, seconds=1800).end_time == 6400
    expired = session.adjust(now=2000, seconds=-5000)
    assert expired.phase == SessionPhase.RESTORING
    with pytest.raises(ValueError, match="ended"):
        expired.adjust(now=1000, seconds=1800)
    released = session.release_target()
    assert not released.target_owned
    assert released.mode_owned
    manual = observed(high=True, target=39, mode=HeatMode.READY)
    assert released.goal(manual) == (Control.HIGH_RANGE, False)
    assert RangeSession.from_record(released.to_record()) == released


@pytest.mark.parametrize(
    "change",
    [
        {"version": 3},
        {"version": True},
        {"original_range": 1},
        {"original_mode": "UNKNOWN"},
        {"original_mode": None},
        {"step": "unknown"},
        {"phase": "unknown"},
        {"unit": "K"},
        {"original_high": float("nan")},
        {"end_time": 999},
        {"operation_id": "invalid"},
        {"operation_id": 123},
        {"unexpected": True},
        {"step": "active"},
        {"mode_owned": True, "original_mode": "READY"},
        {"phase": "restoring"},
        {"phase": "restoring", "step": "restore_mode", "mode_owned": False},
    ],
)
def test_corrupt_bathing_checkpoints_fail_closed(change):
    session = RangeSession.start(now=1000, end=4600, minimum_c=36.5, state=observed())
    with pytest.raises(ValueError):
        RangeSession.from_record(session.to_record() | change)


@pytest.mark.parametrize("record", [None, [], {}, {"version": 2}])
def test_incomplete_bathing_storage_is_not_a_session(record):
    with pytest.raises(ValueError):
        RangeSession.from_record(record)


@pytest.mark.parametrize("minimum", [float("nan"), float("inf"), 36.7, 41, True])
def test_invalid_minimum_does_not_create_intent(minimum):
    with pytest.raises(ValueError):
        RangeSession.start(now=1000, end=4600, minimum_c=minimum, state=observed())


def test_native_fahrenheit_rounds_minimum_up_and_readiness_does_not_mean_heater_on():
    state = observed(high=True, target=97, mode=HeatMode.READY)
    state = replace(state, status=replace(state.status, unit=TemperatureUnit.FAHRENHEIT))
    session = RangeSession.start(now=1000, end=4600, minimum_c=36.5, state=state)
    assert session.target == 98
    assert session.goal(state) == (Control.TARGET, 98)
    warm = replace(
        state, status=replace(state.status, target_temperature=98, current_temperature=98)
    )
    session = session.reconcile(now=1001, state=warm)
    session = session.reconcile(now=1002, state=warm)
    assert session.step == RangeStep.ACTIVE
    session = session.reconcile(now=1003, state=warm)
    assert session.phase == SessionPhase.TARGET_REACHED
    assert session.reconcile(now=1004, state=warm).phase == SessionPhase.HOLDING
    assert RangeSession.from_record(session.to_record()) == session


def test_external_target_range_or_mode_changes_are_not_silently_overwritten():
    session = RangeSession.start(
        now=1000, end=4600, minimum_c=36.5, state=observed(high=True, target=35)
    )
    for state in (
        observed(high=True, target=36.5),
        observed(high=True, target=36.5, mode=HeatMode.READY),
    ):
        session = session.reconcile(now=1001, state=state)
    assert session.step == RangeStep.ACTIVE
    for changed in (
        observed(high=True, target=39, mode=HeatMode.READY),
        observed(),
        observed(high=True, target=36.5),
    ):
        assert session.reconcile(now=1002, state=changed) == session
        with pytest.raises(SessionConflict):
            session.goal(changed)
    for state in (None, observed(target=None)):
        with pytest.raises(ValueError):
            RangeSession.start(now=1000, end=4600, minimum_c=36.5, state=state)


@pytest.mark.parametrize(
    "change", [{"target_owned": False}, {"phase": "holding"}, {"mode_owned": True}]
)
def test_storage_cannot_disarm_restoration_before_an_override(change):
    session = RangeSession.start(
        now=1000, end=4600, minimum_c=36.5, state=observed(high=True, target=35)
    )
    with pytest.raises(ValueError):
        RangeSession.from_record(session.to_record() | change)
