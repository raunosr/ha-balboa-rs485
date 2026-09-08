"""Independent heat-capacity/heat-loss oracle and deterministic held-out evaluation."""

import json
import math
import random
from dataclasses import dataclass
from statistics import mean, median

from balboa_rs485.prediction import HeatingModel, SegmentCollector


@dataclass(frozen=True)
class ThermalPlant:
    power_w: float = 3000
    mass_kg: float = 1300
    loss_w_per_k: float = 12
    ambient: float = 0

    def __post_init__(self) -> None:
        if any(
            not math.isfinite(x) or x <= 0 for x in (self.power_w, self.mass_kg, self.loss_w_per_k)
        ) or not math.isfinite(self.ambient):
            raise ValueError("Invalid thermal plant parameters")

    def water(self, start: float, seconds: float) -> float:
        equilibrium = self.ambient + self.power_w / self.loss_w_per_k
        return equilibrium + (start - equilibrium) * math.exp(
            -self.loss_w_per_k * seconds / (self.mass_kg * 4186)
        )

    def seconds_to(self, start: float, target: float) -> float | None:
        if target <= start:
            return 0
        equilibrium = self.ambient + self.power_w / self.loss_w_per_k
        if target >= equilibrium or start >= equilibrium:
            return None
        return (
            self.mass_kg
            * 4186
            / self.loss_w_per_k
            * math.log((equilibrium - start) / (equilibrium - target))
        )


def evaluate() -> dict[str, object]:
    """45 chronological training days; 15 untouched test days, four outdoor regimes."""
    rng = random.Random(20260907)
    model = HeatingModel(outdoor=True)
    errors = []
    for day in range(60):
        plant = ThermalPlant(
            power_w=3000 * rng.uniform(0.975, 1.025),
            loss_w_per_k=12 * rng.uniform(0.92, 1.08),
            ambient=(10, 0, -10, -20)[day % 4],
        )
        start, target = rng.uniform(23, 30), 38.5
        actual = plant.seconds_to(start, target)
        assert actual is not None
        if day >= 45:
            predicted = model.eta(start, target, plant.ambient)
            assert predicted is not None
            errors.append(predicted - actual / 60)
            continue  # Never update from held-out data.
        collector = SegmentCollector(outdoor=True)
        for seconds in range(0, int(actual), 30):
            segment = collector.observe(
                at=day * 86400 + seconds,
                water=round(plant.water(start, seconds) * 2) / 2,
                outdoor=plant.ambient,
                heating=True,
                healthy=True,
            )
            if segment is not None:
                model.update(segment)
    return {
        "seed": 20260907,
        "days": 60,
        "training_days": 45,
        "held_out_days": 15,
        "training_segments": model.samples,
        "coefficients": model.coefficients,
        "mae_minutes": mean(abs(e) for e in errors),
        "median_absolute_error_minutes": median(abs(e) for e in errors),
        "bias_minutes": mean(errors),
        "max_absolute_error_minutes": max(abs(e) for e in errors),
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
