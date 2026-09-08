"""Quantization-aware observational learning and out-of-sample model checks."""

import math
from copy import deepcopy

import pytest

from balboa_rs485.prediction import HeatingModel, HeatingSegment, SegmentCollector


def collect(collector, *, duration=3600, rate=2, outdoor=None, start=0):
    result = None
    for second in range(0, duration + 1, 30):
        sample = collector.observe(
            at=start + second,
            water=round((27 + rate * second / 3600) * 2) / 2,
            outdoor=outdoor,
            heating=True,
            healthy=True,
        )
        result = sample or result
    return result


def test_quantized_window_is_one_sample_and_matches_two_degrees_per_hour():
    segment = collect(SegmentCollector(outdoor=True), outdoor=-10)
    assert segment.start == 0 and segment.end == 3600
    assert segment.mean_outdoor == -10
    assert segment.mean_water == pytest.approx(28)
    # Half-degree quantization leaves a small phase-dependent OLS bias (<5% here).
    assert segment.rate == pytest.approx(2, abs=0.1)


def test_stopping_after_thirty_minutes_flushes_but_degradation_discards():
    collector = SegmentCollector()
    assert collect(collector, duration=1800) is None
    segment = collector.observe(at=1830, water=28, outdoor=None, heating=False, healthy=True)
    assert segment.end - segment.start == 1800
    collect(collector, duration=1800, start=2000)
    assert collector.observe(at=3830, water=28, outdoor=None, heating=False, healthy=False) is None
    assert collector.observe(at=3860, water=28, outdoor=None, heating=False, healthy=True) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"healthy": False},
        {"water": None},
        {"water": float("nan")},
        {"water": 46},
        {"outdoor": None},
        {"outdoor": float("inf")},
        {"outdoor": -61},
        {"at": 2200},
        {"at": 100},
        {"at": float("nan")},
        {"water": 20},
        {"water": 40},
    ],
)
def test_invalid_gaps_and_progression_never_train(changes):
    collector = SegmentCollector(outdoor=True)
    collect(collector, duration=1800, outdoor=0)
    data = dict(at=1830, water=28, outdoor=0, heating=True, healthy=True)
    collector.observe(**(data | changes))
    assert collector.observe(at=1860, water=28, outdoor=0, heating=False, healthy=True) is None


def test_small_rise_waits_up_to_ninety_minutes_and_duplicate_points_do_not_weight():
    collector = SegmentCollector()
    for second in range(0, 5401, 30):
        result = collector.observe(
            at=second, water=27 if second < 5400 else 27.5, outdoor=None, heating=True, healthy=True
        )
        assert result is None
    assert collector.observe(at=5430, water=27.5, outdoor=None, heating=False, healthy=True) is None
    collector = SegmentCollector()
    collect(collector, duration=3570)
    for _ in range(5):
        assert (
            collector.observe(at=3570, water=29, outdoor=None, heating=True, healthy=True) is None
        )
    assert collector.observe(
        at=3600, water=29, outdoor=None, heating=True, healthy=True
    ).rate == pytest.approx(2, abs=0.1)


def sample(index, *, water=28, outdoor=0, rate=2):
    return HeatingSegment(
        index * 5400, index * 5400 + 3600, water - rate / 2, water + rate / 2, water, outdoor, rate
    )


def trained_model():
    model = HeatingModel(outdoor=True)
    for i in range(30):
        air = (10, 0, -10, -20)[i % 4]
        rate = 3 - 0.03 * (28 - air)
        model.update(sample(i, outdoor=air, rate=rate))
    return model


def test_recency_regression_matches_physics_and_integrated_eta_not_fixed_rate():
    model = trained_model()
    assert model.quality == "learned"
    assert model.coefficients == pytest.approx((3, -0.03))
    assert model.rate(30, -20) < model.rate(30, 10)
    # Analytic integral of dT/dh = 3 - .03 * (T - outside), independent oracle.
    expected = 60 / 0.03 * math.log((3 - 0.03 * 27) / (3 - 0.03 * 38))
    assert model.eta(27, 38, 0) == pytest.approx(expected, abs=0.001)
    assert model.eta(27, 38, 0) > 60 * 11 / model.rate(27, 0)
    assert model.eta(38, 37, 0) == 0
    assert model.eta(27, 38) is None
    assert model.mae is not None and model.median_error is not None


def test_forgetting_adapts_and_constant_feature_does_not_divide_by_zero():
    model = HeatingModel()
    for i in range(100):
        model.update(sample(i, outdoor=None, rate=1 if i < 20 else 3))
    assert model.rate(28) == pytest.approx(3, abs=0.05)
    assert model.coefficients[1] == 0
    assert len(model.errors) == 64


def test_invalid_inputs_features_and_overlapping_samples_are_rejected():
    with pytest.raises(ValueError):
        HeatingModel(fallback=0)
    with pytest.raises(ValueError):
        HeatingModel(fallback=True)
    model = HeatingModel()
    assert model.quality == "learning" and model.mae is None
    assert model.eta(27, 38) == pytest.approx(330)
    with pytest.raises(ValueError):
        model.update(sample(0))
    model.update(sample(0, outdoor=None))
    with pytest.raises(ValueError):
        model.update(sample(0, outdoor=None))
    with pytest.raises(ValueError):
        model.rate(float("nan"))
    with pytest.raises(ValueError):
        model.eta(27, 46)
    with pytest.raises(ValueError):
        HeatingSegment(0, 5, 27, 28, 27.5, None, 2)
    with pytest.raises(ValueError):
        sample(0, rate=9)
    with pytest.raises(ValueError):
        sample(0, outdoor=-61)
    with pytest.raises(ValueError):
        HeatingSegment(0, 3600, 27, 28, 30, None, 2)


def test_record_roundtrip_and_corrupt_metrics_are_not_trusted():
    model = trained_model()
    restored = HeatingModel.from_record(model.to_record(), outdoor=True, fallback=2)
    assert restored.to_record() == model.to_record()
    assert restored.eta(27, 38, 0) == model.eta(27, 38, 0)
    empty = HeatingModel()
    assert HeatingModel.from_record(empty.to_record(), outdoor=False, fallback=3).samples == 0
    for changes in (
        {"version": True},
        {"version": 2},
        {"outdoor": False},
        {"samples": True},
        {"samples": -1},
        {"sums": []},
        {"sums": [0] * 5},
        {"sums": [1, 5, 0, 1, 5]},
        {"errors": [0] * 65},
        {"errors": [float("nan")]},
        {"last_update": None},
        {"coefficients": [1, 1]},
        {"mae": 999},
        {"median_error": 999},
    ):
        with pytest.raises(ValueError):
            HeatingModel.from_record(
                deepcopy(model.to_record()) | changes, outdoor=True, fallback=2
            )
    with pytest.raises(ValueError):
        HeatingModel.from_record([], outdoor=False, fallback=2)
    with pytest.raises(ValueError):
        HeatingModel.from_record(empty.to_record() | {"errors": [1]}, outdoor=False, fallback=2)


def test_unreachable_target_and_week_limit_do_not_produce_a_ready_time():
    model = HeatingModel()
    for i in range(10):
        water = 20 if i % 2 else 28
        model.update(sample(i, water=water, outdoor=None, rate=8 - 0.25 * water))
    assert model.rate(33) is None
    assert model.eta(28, 34) is None
    slow = HeatingModel()
    for i in range(5):
        slow.update(sample(i, outdoor=None, rate=0.1))
    assert slow.eta(0, 45) is None
    with pytest.raises(ValueError):
        HeatingSegment(-1, 3600, 27, 29, 28, None, 2)


def test_mixed_warmup_and_cooling_tail_is_discarded_not_an_exception():
    collector = SegmentCollector()
    for second in range(0, 3601, 30):
        water = 27 if second == 0 else 28 if second == 30 else 29
        if second >= 3540:
            water = 28.5 if second == 3540 else 28
        assert (
            collector.observe(at=second, water=water, outdoor=None, heating=True, healthy=True)
            is None
        )


def test_window_that_passes_ninety_minutes_without_exact_boundary_is_discarded():
    collector = SegmentCollector()
    for second in range(0, 5400, 60):
        assert (
            collector.observe(at=second, water=27, outdoor=None, heating=True, healthy=True) is None
        )
    assert collector.observe(at=5420, water=28, outdoor=None, heating=True, healthy=True) is None
