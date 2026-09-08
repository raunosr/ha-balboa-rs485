"""Whole-record edits preserve the other schedule and distinguish midnight from duration."""

from dataclasses import replace

import pytest

from balboa_rs485.protocol.configuration import Query
from balboa_rs485.protocol.messages import FilterCycle, decode_message
from balboa_rs485.protocol.settings import FilterSchedule
from balboa_rs485.state.model import Control
from tools.simulator.server import configuration_fixture

from .test_state import observed


def test_filter_schedule_preserves_duration_when_start_changes_and_handles_midnight():
    original = FilterSchedule((FilterCycle(8, 30, 120, True), FilterCycle(14, 0, 90, False)))
    moved = original.update(1, start=22 * 60)
    assert moved.cycles[0] == FilterCycle(22, 0, 120, True)
    assert moved.end(1) == 0
    changed = moved.update(1, end=2 * 60)
    assert changed.cycles[0].duration_minutes == 240
    assert changed.cycles[1] == original.cycles[1]
    assert changed.frame().message_type == 0x23
    assert changed.frame().payload == bytes((22, 0, 4, 0, 14, 0, 1, 30))
    enabled = changed.update(2, enabled=True)
    assert enabled.frame().payload[4] == 0x8E
    assert enabled.cycles[0] == changed.cycles[0]
    assert enabled.cycles[1].duration_minutes == 90


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start": -1},
        {"start": 1440},
        {"start": True},
        {"end": 1440},
        {"end": 510},
        {"enabled": False},
    ],
)
def test_invalid_or_ambiguous_cycle_one_edits_are_rejected(kwargs):
    schedule = FilterSchedule((FilterCycle(8, 30, 120, True), FilterCycle(14, 0, 90, False)))
    with pytest.raises(ValueError):
        schedule.update(1, **kwargs)


def test_filter_response_can_be_newer_than_latest_status_without_being_rejected():
    state = observed(
        at=10.0, filters=decode_message(configuration_fixture(Query.FILTERS)), filters_at=10.1
    )
    desired = FilterSchedule(state.filters.cycles).update(1, start=21 * 60)
    state.validate(Control.FILTERS, desired)
    with pytest.raises(ValueError, match="freshly queried"):
        replace(state, filters_at=6).validate(Control.FILTERS, desired)
