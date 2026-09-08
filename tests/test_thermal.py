"""Held-out acceptance uses the physical oracle, not synthetic model labels."""

import pytest

from tools.thermal import ThermalPlant, evaluate


def test_physical_oracle_and_held_out_sixty_day_evaluation():
    plant = ThermalPlant()
    assert plant.water(27, plant.seconds_to(27, 38)) == pytest.approx(38)
    assert plant.seconds_to(38, 27) == 0
    assert ThermalPlant(power_w=1).seconds_to(27, 38) is None
    with pytest.raises(ValueError):
        ThermalPlant(mass_kg=0)
    report = evaluate()
    assert report["held_out_days"] == 15
    assert report["training_segments"] >= 200
    assert report["coefficients"][1] < 0
    assert report["median_absolute_error_minutes"] < 20
    assert report["mae_minutes"] < 20


def test_thermal_cli_reports_real_evaluation():
    import json
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "tools.thermal"], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout)["held_out_days"] == 15
