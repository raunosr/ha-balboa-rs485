"""Observational thermal model; no transport, HA, or command dependency."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median
from typing import Any


def _finite(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("Expected a finite number")
    return float(value)


@dataclass(frozen=True, slots=True)
class HeatingSegment:
    start: float
    end: float
    start_water: float
    end_water: float
    mean_water: float
    mean_outdoor: float | None
    rate: float

    def __post_init__(self) -> None:
        values = (
            self.start,
            self.end,
            self.start_water,
            self.end_water,
            self.mean_water,
            self.rate,
        )
        for value in values:
            _finite(value)
        if self.start < 0 or self.end > 253402300799 or not 1800 <= self.end - self.start <= 5400:
            raise ValueError("Heating segments require 30..90 minutes")
        if not 0 <= self.start_water < self.end_water <= 45 or not 0 < self.rate <= 8:
            raise ValueError("Invalid heating progression")
        if not self.start_water <= self.mean_water <= self.end_water:
            raise ValueError("Invalid mean water temperature")
        if self.mean_outdoor is not None and not -60 <= _finite(self.mean_outdoor) <= 60:
            raise ValueError("Invalid outdoor temperature")


class SegmentCollector:
    """Bounded sufficient statistics; quantized points never become training samples."""

    def __init__(self, *, outdoor: bool = False) -> None:
        self.outdoor = outdoor
        self.reset()

    def reset(self) -> None:
        self._start: float | None = None
        self._seen = self._at = self._first = self._water = 0.0
        self._n = 0
        self._t = self._tt = self._y = self._ty = self._air = 0.0

    def _finish(self) -> HeatingSegment | None:
        if self._start is None or self._at - self._start < 1800 or self._water - self._first < 1:
            return None
        variance = self._tt - self._t * self._t / self._n
        rate = (self._ty - self._t * self._y / self._n) / variance
        if not 0 < rate <= 8 or not self._first <= self._y / self._n <= self._water:
            return None
        return HeatingSegment(
            self._start,
            self._at,
            self._first,
            self._water,
            self._y / self._n,
            self._air / self._n if self.outdoor else None,
            rate,
        )

    def observe(
        self,
        *,
        at: float,
        water: float | None,
        outdoor: float | None,
        heating: bool,
        healthy: bool,
    ) -> HeatingSegment | None:
        valid = (
            math.isfinite(at)
            and 0 <= at <= 253402300799
            and healthy
            and water is not None
            and math.isfinite(water)
            and 0 <= water <= 45
            and (
                not self.outdoor
                or outdoor is not None
                and math.isfinite(outdoor)
                and -60 <= outdoor <= 60
            )
        )
        if not valid:
            self.reset()
            return None
        assert water is not None
        if self._start is not None and (at < self._seen or at - self._seen > 90):
            self.reset()
        if not heating:
            result = self._finish()
            self.reset()
            return result
        if self._start is None:
            self._start = self._at = at
            self._first = self._water = water
        self._seen = at
        if self._n and at - self._at < 30:
            return None
        # A full degree in 30 seconds or > one quantum of cooling is not a clean window.
        if self._n and (
            water < self._water - 0.5 or water - self._water > max(1, (at - self._at) / 450)
        ):
            self.reset()
            return None
        hours = (at - self._start) / 3600
        if hours > 1.5:
            self.reset()
            return None
        self._n += 1
        self._t += hours
        self._tt += hours * hours
        self._y += water
        self._ty += hours * water
        self._air += outdoor or 0
        self._at, self._water = at, water
        if hours >= 1:
            result = self._finish()
            if result is not None or hours >= 1.5:
                self.reset()
            return result
        return None


class HeatingModel:
    """Exponentially weighted least squares, with prequential segment ETA errors."""

    def __init__(self, *, outdoor: bool = False, fallback: float = 2.0) -> None:
        if not 0.1 <= _finite(fallback) <= 8:
            raise ValueError("Fallback rate requires 0.1..8 C/hour")
        self.outdoor, self.fallback = outdoor, fallback
        self.samples = 0
        self.last_update: float | None = None
        self._sums = [0.0] * 5  # weight, x, x*x, y, x*y
        self.errors: list[float] = []

    @property
    def coefficients(self) -> tuple[float, float]:
        weight, sx, sxx, sy, sxy = self._sums
        if weight <= 0:
            return self.fallback, 0.0
        mx, my = sx / weight, sy / weight
        variance = max(0.0, sxx / weight - mx * mx)
        slope = max(-1.0, min(0.0, (sxy / weight - mx * my) / variance)) if variance >= 1 else 0.0
        return my - slope * mx, slope

    @property
    def quality(self) -> str:
        return "learning" if self.samples < 5 else "learned"

    @property
    def mae(self) -> float | None:
        return sum(abs(e) for e in self.errors) / len(self.errors) if self.errors else None

    @property
    def median_error(self) -> float | None:
        return median(abs(e) for e in self.errors) if self.errors else None

    def rate(self, water: float, outdoor: float | None = None) -> float | None:
        if not 0 <= _finite(water) <= 45:
            raise ValueError("Water temperature outside prediction range")
        if self.outdoor and (outdoor is None or not -60 <= _finite(outdoor) <= 60):
            return None
        if self.samples < 5:
            return self.fallback
        intercept, slope = self.coefficients
        value = intercept + slope * (
            water - outdoor if self.outdoor and outdoor is not None else water
        )
        return value if 0 < value <= 8 else None

    def eta(self, water: float, target: float, outdoor: float | None = None) -> float | None:
        if not 0 <= _finite(target) <= 45:
            raise ValueError("Target outside prediction range")
        first_rate = self.rate(water, outdoor)
        if first_rate is None:
            return None
        if target <= water:
            return 0.0
        steps = math.ceil((target - water) / 0.1)
        delta = (target - water) / steps
        minutes = 0.0
        for index in range(steps):
            rate = self.rate(water + (index + 0.5) * delta, outdoor)
            if rate is None:
                return None
            minutes += 60 * delta / rate
            if minutes > 10080:  # Beyond one week is not a useful readiness claim.
                return None
        return minutes

    def update(self, segment: HeatingSegment) -> None:
        if self.outdoor != (segment.mean_outdoor is not None):
            raise ValueError("Segment feature does not match model")
        if self.last_update is not None and segment.start < self.last_update:
            raise ValueError("Overlapping or out-of-order training segment")
        prediction = self.eta(segment.start_water, segment.end_water, segment.mean_outdoor)
        if prediction is not None:
            self.errors.append(prediction - (segment.end - segment.start) / 60)
            self.errors = self.errors[-64:]
        weight = (segment.end - segment.start) / 3600
        x = segment.mean_water - (segment.mean_outdoor or 0)
        values = (1.0, x, x * x, segment.rate, x * segment.rate)
        self._sums = [
            0.96 * old + weight * value for old, value in zip(self._sums, values, strict=True)
        ]
        self.samples += 1
        self.last_update = segment.end

    def to_record(self) -> dict[str, Any]:
        return {
            "version": 1,
            "outdoor": self.outdoor,
            "samples": self.samples,
            "last_update": self.last_update,
            "sums": list(self._sums),
            "coefficients": list(self.coefficients),
            "errors": list(self.errors),
            "mae": self.mae,
            "median_error": self.median_error,
        }

    @classmethod
    def from_record(cls, record: object, *, outdoor: bool, fallback: float) -> HeatingModel:
        model = cls(outdoor=outdoor, fallback=fallback)
        keys = {
            "version",
            "outdoor",
            "samples",
            "last_update",
            "sums",
            "coefficients",
            "errors",
            "mae",
            "median_error",
        }
        if (
            not isinstance(record, dict)
            or set(record) != keys
            or record["version"] != 1
            or type(record["version"]) is not int
        ):
            raise ValueError("Invalid model record version/shape")
        if (
            record["outdoor"] is not outdoor
            or type(record["samples"]) is not int
            or not 0 <= record["samples"] <= 1_000_000_000
        ):
            raise ValueError("Invalid model feature/sample count")
        sums, errors = record["sums"], record["errors"]
        if (
            not isinstance(sums, list)
            or len(sums) != 5
            or not isinstance(errors, list)
            or len(errors) > 64
        ):
            raise ValueError("Invalid model statistics")
        model._sums = [_finite(value) for value in sums]
        model.errors = [_finite(value) for value in errors]
        model.samples = record["samples"]
        last = record["last_update"]
        if model.samples:
            model.last_update = _finite(last)
            if (
                not 0 <= model.last_update <= 253402300799
                or not 0 < model._sums[0] <= 37.5001
                or model._sums[2] < 0
                or model._sums[3] <= 0
            ):
                raise ValueError("Invalid learned statistics")
            weight, sx, sxx, sy, _ = model._sums
            if sxx + 1e-7 < sx * sx / weight or not 0 < sy / weight <= 8:
                raise ValueError("Impossible regression statistics")
        elif last is not None or any(model._sums) or errors:
            raise ValueError("Empty model has learned statistics")
        # Serialized derived values are checks, never another source of coefficients.
        if (
            model.samples
            and record["coefficients"] != list(model.coefficients)
            or record["mae"] != model.mae
            or record["median_error"] != model.median_error
        ):
            raise ValueError("Inconsistent model metrics")
        return model
