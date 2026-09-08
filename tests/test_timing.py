"""Monotonic policy, configurable deadlines, and bounded recovery pacing."""

import pytest

from balboa_rs485.transport.timing import Backoff, Timing


def test_backoff_increases_is_bounded_and_requires_explicit_healthy_reset():
    backoff = Backoff(Timing(), jitter=lambda: 0.5)
    assert [backoff.next_delay() for _ in range(9)] == [1, 2, 4, 8, 16, 32, 60, 60, 60]
    backoff.reset()
    assert backoff.next_delay() == 1
    assert Backoff(Timing(), jitter=lambda: 0).next_delay() == 0.8
    high = Backoff(Timing(), jitter=lambda: 1)
    assert high.next_delay() == pytest.approx(1.2)
    for _ in range(1000):
        assert high.next_delay() <= 60


@pytest.mark.parametrize(
    "kwargs",
    [
        {"first_frame": 0},
        {"connect": float("nan")},
        {"query_timeout": float("inf")},
        {"degrade_after": 9},
        {"stale_after": 15},
        {"backoff_initial": 100},
        {"query_attempts": 0},
        {"query_attempts": 1.5},
        {"tick": -1},
    ],
)
def test_timing_rejects_invalid_deadline_policy(kwargs):
    with pytest.raises(ValueError):
        Timing(**kwargs)
