"""Heating sessions contain intent, never serialized wire commands."""

import json
from dataclasses import replace

import pytest

from balboa_rs485.protocol.messages import TemperatureUnit, decode_message
from balboa_rs485.session import Session, SessionPhase
from tests.test_extended_messages import SETUP
from tests.test_state import observed


def spa(*, target=38.0, current=27.0, available=True):
    state = observed(setup=decode_message(SETUP), available=available)
    return replace(
        state, status=replace(state.status, target_temperature=target, current_temperature=current)
    )


def test_expiry_requests_maintenance_until_observed():
    session = Session.start(
        now=1000,
        end=4600,
        target=38,
        maintenance=27,
        unit=TemperatureUnit.CELSIUS,
        state=spa(target=27),
    )
    assert session.phase == SessionPhase.PREHEATING
    assert session.desired(spa(target=27)) == 38
    assert session.desired(spa()) is None
    expired = session.reconcile(now=4600, state=spa())
    assert expired.phase == SessionPhase.RESTORING
    assert expired.desired(spa()) == 27
    assert expired.reconcile(now=4700, state=spa(target=27)) is None


@pytest.mark.parametrize(
    "state",
    [
        None,
        spa(available=False),
        replace(spa(), status=replace(spa().status, unit=TemperatureUnit.FAHRENHEIT)),
    ],
)
def test_expiry_is_latched_without_safe_matching_observations(state):
    session = Session.start(
        now=1000, end=4600, target=38, maintenance=27, unit=TemperatureUnit.CELSIUS, state=spa()
    )
    expired = session.reconcile(now=4600, state=state)
    assert expired.phase == SessionPhase.RESTORING
    assert expired.reconcile(now=1500, state=state) == expired
    with pytest.raises(ValueError):
        expired.desired(state)


def test_adjust_cancel_and_clock_rollback_do_not_resurrect_expired_sessions():
    session = Session.start(
        now=1000, end=4600, target=38, maintenance=27, unit=TemperatureUnit.CELSIUS, state=spa()
    )
    extended = session.adjust(now=2000, seconds=1800)
    assert extended.end_time == 6400
    assert extended.adjust(now=2000, seconds=-1800) == session
    reduced = session.adjust(now=3000, seconds=-1800)
    assert reduced.phase == SessionPhase.RESTORING
    assert reduced.end_time == 2800
    assert session.cancel().phase == SessionPhase.RESTORING
    for finished, now in [(session, 4600), (reduced, 1000), (session.cancel(), 1000)]:
        with pytest.raises(ValueError, match="ended"):
            finished.adjust(now=now, seconds=1800)


@pytest.mark.parametrize(
    "override",
    [
        dict(end=1000),
        dict(end=float("inf")),
        dict(now=float("nan")),
        dict(target=True),
        dict(maintenance=26),
        dict(target=37.7),
        dict(unit=TemperatureUnit.FAHRENHEIT),
        dict(state=None),
    ],
)
def test_start_rejects_invalid_or_unobserved_intent(override):
    arguments = dict(
        now=1000, end=4600, target=38, maintenance=27, unit=TemperatureUnit.CELSIUS, state=spa()
    )
    with pytest.raises(ValueError):
        Session.start(**(arguments | override))


def test_observed_progress_and_restart_preserve_only_intent():
    session = Session.start(
        now=1000, end=4600, target=38, maintenance=27, unit=TemperatureUnit.CELSIUS, state=spa()
    )
    assert session.reconcile(now=1100, state=spa(current=None)) == session
    assert session.reconcile(now=1100, state=spa(current=38, target=27)) == session
    reached = session.reconcile(now=1100, state=spa(current=38))
    assert reached.phase == SessionPhase.TARGET_REACHED
    holding = reached.reconcile(now=1200, state=spa(current=38))
    assert holding.phase == SessionPhase.HOLDING
    assert holding.reconcile(now=1300, state=spa(current=37)) == holding
    for original in (session, reached, holding, holding.cancel()):
        record = json.loads(json.dumps(original.to_record()))
        assert Session.from_record(record) == original
    restored = Session.from_record(session.to_record())
    assert restored.reconcile(now=4700, state=None).phase == SessionPhase.RESTORING


@pytest.mark.parametrize(
    "override",
    [
        dict(version=2),
        dict(phase="unknown"),
        dict(unit="K"),
        dict(target=float("nan")),
        dict(maintenance=True),
        dict(target=100),
        dict(target=37.7),
        dict(start_time=-1),
        dict(end_time=1e300),
        dict(end_time=999),
        dict(extra="wire"),
        dict(target="38"),
    ],
)
def test_corrupt_or_future_storage_is_not_loaded(override):
    session = Session.start(
        now=1000, end=4600, target=38, maintenance=27, unit=TemperatureUnit.CELSIUS, state=spa()
    )
    with pytest.raises(ValueError):
        Session.from_record(session.to_record() | override)


@pytest.mark.parametrize("record", [None, [], {}, {"version": 1}])
def test_missing_record_fields_fail_closed(record):
    with pytest.raises(ValueError):
        Session.from_record(record)


def test_fahrenheit_session_preserves_native_unit_and_rejects_unit_change():
    state = spa(target=90, current=82)
    state = replace(state, status=replace(state.status, unit=TemperatureUnit.FAHRENHEIT))
    session = Session.start(
        now=1000, end=4600, target=100, maintenance=80, unit=TemperatureUnit.FAHRENHEIT, state=state
    )
    assert Session.from_record(session.to_record()).desired(state) == 100
    with pytest.raises(ValueError, match="matching"):
        session.desired(spa())
    with pytest.raises(ValueError, match="Unknown"):
        replace(session, unit="F")
