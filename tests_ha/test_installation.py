"""Run separately: load the actual ZIP, not an already-imported checkout adapter."""

import importlib
import zipfile
from pathlib import Path

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components
from tools.package import build_zip
from tools.simulator.server import Simulator

from .test_lifecycle import eventually


# HA 2026.8.3 HTTP deliberately writes app["hass"] for backwards compatibility.
# Ignore only aiohttp's key-style advisory here, not integration warnings/errors.
@pytest.mark.filterwarnings("ignore::aiohttp.web_exceptions.NotAppKeyWarning")
async def test_extracted_package_loads_in_real_ha_and_serves_its_local_icon(
    hass, hass_client, socket_enabled, tmp_path, monkeypatch
):
    root = Path(__file__).parents[1]
    archive_path = tmp_path / "integration.zip"
    build_zip(root, archive_path)
    installed = tmp_path / "config"
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(installed)  # Locally built archive with package-root paths only.
    monkeypatch.setattr(custom_components, "__path__", [str(installed / "custom_components")])
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "classic-rs485"},
            options={"enable_controls": True},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            module = importlib.import_module("custom_components.balboa_rs485._core.runtime")
            assert Path(module.__file__).is_relative_to(installed)
            assert hass.states.get("climate.balboa_spa").attributes["temperature"] == 38
            assert hass.states.get("climate.balboa_spa").attributes["preset_mode"] == "high"
            assert hass.states.get("sensor.balboa_spa_water_temperature").state == "27.0"
            assert hass.states.get("select.balboa_spa_heating_policy").attributes["options"] == [
                "ready",
                "rest",
            ]
            assert hass.states.get("binary_sensor.balboa_spa_priming").state == "off"
            prediction_module = importlib.import_module(
                "custom_components.balboa_rs485._core.prediction"
            )
            assert Path(prediction_module.__file__).is_relative_to(installed)
            assert hass.states.get("sensor.balboa_spa_heating_rate").state == "2.0"
            session_module = importlib.import_module(
                "custom_components.balboa_rs485._core.session_runner"
            )
            assert Path(session_module.__file__).is_relative_to(installed)
            await hass.services.async_call(
                "balboa_rs485",
                "start_heating_session",
                {
                    "config_entry_id": entry.entry_id,
                    "duration": "01:00:00",
                    "target_temperature": 27,
                    "maintenance_temperature": 28,
                },
                blocking=True,
            )
            await eventually(
                lambda: hass.states.get("sensor.balboa_spa_heating_session").state == "holding"
            )
            await hass.services.async_call(
                "balboa_rs485",
                "cancel_heating_session",
                {"config_entry_id": entry.entry_id},
                blocking=True,
            )
            await eventually(
                lambda: hass.states.get("sensor.balboa_spa_heating_session").state == "idle"
            )
            assert simulator.target_temperature == 28
            assert simulator.physical_commands == 2
            assert await async_setup_component(hass, "brands", {})
            client = await hass_client()
            response = await client.get(
                "/api/brands/integration/balboa_rs485/icon.png?placeholder=no"
            )
            assert response.status == 200
            assert (
                await response.read()
                == (installed / "custom_components/balboa_rs485/brand/icon.png").read_bytes()
            )
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
