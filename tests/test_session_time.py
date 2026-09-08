"""Wall-clock deadlines are explicit; DST must not silently choose an hour."""

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from balboa_rs485.session_time import deadline


@pytest.mark.parametrize(
    "duration,end,expected",
    [
        (3600, None, "2026-09-06T13:00:00+00:00"),
        (None, "18:00", "2026-09-06T15:00:00+00:00"),
        (None, "12:00", "2026-09-07T09:00:00+00:00"),
        (None, "2026-09-06T18:00:00+03:00", "2026-09-06T15:00:00+00:00"),
    ],
)
def test_duration_or_next_local_end_time(duration, end, expected):
    now = datetime(2026, 9, 6, 12, tzinfo=UTC)
    assert (
        deadline(now=now, duration=duration, end_time=end, zone=timezone(timedelta(hours=3)))
        == datetime.fromisoformat(expected).timestamp()
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"duration": 60, "end_time": "18:00"},
        {"duration": 0},
        {"duration": -1},
        {"duration": True},
        {"duration": float("inf")},
        {"duration": 1e100},
        {"end_time": "2026-09-06T18:00:00"},
        {"end_time": "2026-09-05T18:00:00Z"},
        {"end_time": "25:00"},
        {"end_time": "bad"},
    ],
)
def test_deadline_rejects_ambiguous_input(arguments):
    with pytest.raises(ValueError):
        deadline(now=datetime(2026, 9, 6, 12, tzinfo=UTC), zone=UTC, **arguments)


@pytest.mark.parametrize("now", ["2026-03-28T23:00:00Z", "2026-10-24T23:00:00Z"])
def test_dst_gap_and_fold_require_explicit_offset(now):
    with pytest.raises(ValueError, match="ambiguous|nonexistent"):
        deadline(
            now=datetime.fromisoformat(now), zone=ZoneInfo("Europe/Helsinki"), end_time="03:30"
        )


def test_duration_counts_elapsed_time_even_when_callers_clock_is_local():
    zone = ZoneInfo("Europe/Helsinki")
    now = datetime(2026, 3, 29, 2, 30, tzinfo=zone)
    assert deadline(now=now, zone=zone, duration=10800) == now.timestamp() + 10800
    with pytest.raises(ValueError, match="aware"):
        deadline(now=now.replace(tzinfo=None), zone=zone, duration=60)
