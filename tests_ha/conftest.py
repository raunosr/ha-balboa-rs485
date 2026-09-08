"""Use the real Home Assistant test framework, only in the Linux HA job."""

from pathlib import Path

import pytest

import custom_components

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations, monkeypatch):
    """Permit discovery of the integration under test."""
    # HA's test fixture installs its own custom_components import path. Point its
    # real loader at this checkout (the equivalent of the user's config folder).
    monkeypatch.setattr(
        custom_components, "__path__", [str(Path(__file__).parents[1] / "custom_components")]
    )
