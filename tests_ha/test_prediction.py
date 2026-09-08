"""Real HA state/storage/lifecycle boundaries; all physical tests use loopback only."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import voluptuous as vol
import voluptuous_serialize
from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE
from homeassistant.core import CoreState
from homeassistant.data_entry_flow import InvalidData
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.balboa_rs485._core.prediction import HeatingSegment
from custom_components.balboa_rs485._core.protocol.messages import (
    HeatState,
    TemperatureUnit,
    decode_message,
)
from custom_components.balboa_rs485._core.transport.connection import ConnectionState
from custom_components.balboa_rs485.coordinator import SpaCoordinator
from custom_components.balboa_rs485.prediction import PredictionController, model_store
from tools.simulator.server import Simulator, load_status_fixture

from .test_lifecycle import eventually
from .test_sessions import setup_spa


def controller(hass, **options):
    entry = MockConfigEntry(
        domain="balboa_rs485",
        title="Balboa Spa",
        data={"host": "127.0.0.1", "port": 8899, "protocol_mode": "classic-rs485"},
        options=options,
    )
    entry.add_to_hass(hass)
    return SpaCoordinator(hass, entry).prediction


def observation(prediction, sequence=1, *, epoch=1, **status):
    snapshot = prediction.coordinator.runtime.connection.snapshot
    return replace(
        snapshot,
        state=ConnectionState.READY,
        epoch=epoch,
        status_sequence=sequence,
        status=replace(decode_message(load_status_fixture()), **status),
        health=replace(
            snapshot.health,
            status_stale=False,
            last_status=prediction.coordinator.hass.loop.time(),
            ready_missing=False,
        ),
    )


def train(prediction, monkeypatch, *, start=1_700_000_000, epoch=1, refresh=False):
    import custom_components.balboa_rs485.prediction as module

    # One extra point tolerates sub-ms differences between loop and wall clocks.
    for seconds in range(0, 3631, 30):
        now = datetime.fromtimestamp(start + seconds, UTC)
        monkeypatch.setattr(module, "dt_util", SimpleNamespace(utcnow=lambda now=now: now))
        snapshot = observation(
            prediction,
            seconds + 1,
            epoch=epoch,
            heat_state=HeatState.HEATING,
            current_temperature=round((27 + seconds / 1800) * 2) / 2,
        )
        if refresh and seconds and seconds % 60 == 0:
            snapshot = replace(snapshot, state=ConnectionState.SYNCHRONIZING)
        prediction.observe(snapshot)


async def test_routine_metadata_refresh_keeps_clean_heating_windows(hass, monkeypatch):
    prediction = controller(hass)
    snapshot = observation(prediction, heat_state=HeatState.HEATING)
    prediction.observe(replace(snapshot, state=ConnectionState.SYNCHRONIZING))
    assert prediction.values["heating_eta"] is None
    prediction._observation = None
    train(prediction, monkeypatch, refresh=True)
    assert prediction.model.samples == 1
    snapshot = observation(prediction, 10000)
    prediction.observe(
        replace(
            snapshot,
            state=ConnectionState.SYNCHRONIZING,
            health=replace(snapshot.health, ready_missing=True),
        )
    )
    assert prediction.values["heating_eta"] is None


async def test_five_forecast_entities_and_options_do_not_open_another_socket(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator, controls=False)
        try:
            names = (
                "heating_rate",
                "heating_time_remaining",
                "ready_at",
                "heating_prediction_error",
                "heating_learning_segments",
            )
            await eventually(lambda: all(hass.states.get(f"sensor.balboa_spa_{x}") for x in names))
            assert hass.states.get("sensor.balboa_spa_heating_rate").state == "2.0"
            eta = hass.states.get("sensor.balboa_spa_heating_time_remaining")
            assert float(eta.state) == 330
            assert eta.attributes["prediction_quality"] == "learning"
            assert eta.attributes["assumption"] == "continuous_heating"
            assert hass.states.get("sensor.balboa_spa_heating_prediction_error").state == "unknown"
            flow = await hass.config_entries.options.async_init(entry.entry_id)
            # Flow-manager tests alone do not exercise the actual HTTP/UI boundary.
            serialized = voluptuous_serialize.convert(
                flow["data_schema"], custom_serializer=cv.custom_serializer
            )
            assert "fallback_heating_rate" in json.dumps(serialized)
            for bad in (float("nan"), float("inf"), 0, 9):
                with pytest.raises(vol.Invalid):
                    flow["data_schema"]({"enable_controls": False, "fallback_heating_rate": bad})
            with pytest.raises(InvalidData):
                await hass.config_entries.options.async_configure(
                    flow["flow_id"],
                    user_input={"enable_controls": False, "fallback_heating_rate": float("nan")},
                )
            assert entry.options == {"enable_controls": False}
            data = {
                "enable_controls": False,
                "fallback_heating_rate": 3,
                "outdoor_temperature_entity": "sensor.outside",
            }
            await hass.config_entries.options.async_configure(flow["flow_id"], user_input=data)
            await hass.async_block_till_done()
            await eventually(
                lambda: hass.states.get("sensor.balboa_spa_heating_rate").state == "unknown"
            )
            hass.states.async_set("sensor.outside", "32", {"unit_of_measurement": "°F"})
            await eventually(
                lambda: hass.states.get("sensor.balboa_spa_heating_rate").state == "3.0"
            )
            hass.config_entries.async_update_entry(entry, options={"enable_controls": False})
            await hass.async_block_till_done()
            assert entry.runtime_data.prediction.outdoor_entity is None
            assert simulator.stats.connections == 1
            assert simulator.physical_commands == 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "value,unit", [("unavailable", "°C"), ("nan", "°C"), ("100", "°C"), ("0", "K")]
)
async def test_invalid_outdoor_values_hide_eta_without_impacting_controls(hass, value, unit):
    prediction = controller(hass, outdoor_temperature_entity="sensor.outside")
    prediction.observe(observation(prediction))  # Missing entity.
    assert prediction.values["heating_eta"] is None
    hass.states.async_set("sensor.outside", value, {"unit_of_measurement": unit})
    prediction.observe(observation(prediction, 2))
    assert prediction.values["heating_eta"] is None
    assert prediction.coordinator.runtime.connection.snapshot.tx_frames == 0


async def test_stale_outdoor_and_fahrenheit_water_and_ready_time(hass, monkeypatch):
    import custom_components.balboa_rs485.prediction as module

    prediction = controller(hass, outdoor_temperature_entity="sensor.outside")
    hass.states.async_set("sensor.outside", "0", {"unit_of_measurement": "°C"})
    now = hass.states.get("sensor.outside").last_reported
    monkeypatch.setattr(module, "dt_util", SimpleNamespace(utcnow=lambda: now))
    snapshot = observation(
        prediction,
        unit=TemperatureUnit.FAHRENHEIT,
        current_temperature=80.6,
        target_temperature=100.4,
        heat_state=HeatState.HEATING,
    )
    prediction.observe(snapshot)
    assert prediction.values["heating_eta"] == 330
    assert prediction.values["ready_at"] == now + timedelta(minutes=330)
    before = prediction.values
    prediction.observe(snapshot)  # Duplicate observations do not relearn/recompute.
    assert prediction.values is before
    prediction.observe(replace(snapshot, status=replace(snapshot.status, heat_state=HeatState.OFF)))
    assert prediction.values["ready_at"] is None
    prediction.observe(replace(snapshot, status=replace(snapshot.status, current_temperature=None)))
    assert prediction.values["heating_eta"] is None
    now += timedelta(seconds=901)
    prediction.observe(snapshot)
    assert prediction.values["heating_eta"] is None


async def test_model_is_durable_and_not_reused_for_a_different_endpoint(hass, monkeypatch):
    prediction = controller(hass)
    train(prediction, monkeypatch)
    assert prediction.model.samples == 1
    assert prediction.attributes["model_last_update"] is not None
    await prediction.async_save()
    fresh = PredictionController(prediction.coordinator)
    await fresh.async_load()
    assert fresh.model.to_record() == prediction.model.to_record()
    assert (
        fresh.collector.observe(
            at=1_700_003_700, water=29, outdoor=None, heating=False, healthy=True
        )
        is None
    )
    prediction.coordinator.connection_data = {"host": "different", "port": 8899}
    other = PredictionController(prediction.coordinator)
    await other.async_load()
    assert other.model.samples == 0
    assert not other.storage_failed


async def test_epoch_changes_and_backwards_wall_clock_do_not_join_windows(hass, monkeypatch):
    prediction = controller(hass)
    train(prediction, monkeypatch)
    train(prediction, monkeypatch, start=1_600_000_000, epoch=2)
    assert prediction.model.samples == 1
    snapshot = observation(prediction, 5000, epoch=2)
    prediction.observe(replace(snapshot, state=ConnectionState.DEGRADED))
    assert prediction.values["heating_eta"] is None


@pytest.mark.parametrize("record", [[], {"invalid": True}, {"binding": "match", "model": {}}])
async def test_corrupt_model_storage_is_optional_and_never_overwritten(hass, record):
    prediction = controller(hass)
    if isinstance(record, dict) and record.get("binding") == "match":
        record["binding"] = prediction.binding
    await prediction._store().async_save(record)
    await prediction.async_load()
    assert prediction.storage_failed
    prediction.observe(observation(prediction))
    assert prediction.values["heating_rate"] == 2
    await prediction.async_close()
    assert await prediction._store().async_load() == record


async def test_failed_write_is_visible_but_never_blocks_physical_lifecycle(hass, monkeypatch):
    prediction = controller(hass, outdoor_temperature_entity="sensor.outside")

    async def failed_save(self, record):
        pass  # HA Store can swallow a disk error after logging it.

    with monkeypatch.context() as boundary:
        boundary.setattr(Store, "async_save", failed_save)
        await prediction.async_save()
    assert prediction.storage_failed
    assert prediction.attributes["storage_error"] is True
    await prediction.async_close()


async def test_cancelled_save_is_retried_and_shutdown_uses_ha_final_write(hass, monkeypatch):
    prediction = controller(hass)
    train(prediction, monkeypatch)

    async def cancelled_save(self, record):
        raise asyncio.CancelledError

    with monkeypatch.context() as boundary:
        boundary.setattr(Store, "async_save", cancelled_save)
        with pytest.raises(asyncio.CancelledError):
            await prediction.async_save()
    previous = hass.state
    try:
        hass.set_state(CoreState.stopping)
        await prediction.async_close()
        assert not prediction.storage_failed
        hass.set_state(CoreState.final_write)
        hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
        await hass.async_block_till_done()
    finally:
        hass.set_state(previous)
    fresh = PredictionController(prediction.coordinator)
    await fresh.async_load()
    assert fresh.model.samples == 1


async def test_learned_segment_is_saved_by_background_owner_and_removed_with_entry(
    hass, socket_enabled, monkeypatch
):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator, controls=False)
        prediction = entry.runtime_data.prediction
        try:
            train(prediction, monkeypatch)
            await eventually(lambda: not prediction._dirty)
            # Serializing on the same lock waits for readback verification to finish.
            await prediction.async_save()
            assert not prediction.storage_failed
            saved = await model_store(hass, entry.entry_id).async_load()
            assert saved["model"]["samples"] == 1
            assert simulator.physical_commands == 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
        await model_store(hass, "other").async_save({"keep": True})
        assert await hass.config_entries.async_remove(entry.entry_id)
        assert await model_store(hass, entry.entry_id).async_load() is None
        assert await model_store(hass, "other").async_load() == {"keep": True}


async def test_sensor_model_metrics_are_not_invented_confidence(hass, socket_enabled):
    from custom_components.balboa_rs485.diagnostics import async_get_config_entry_diagnostics

    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator, controls=False)
        try:
            prediction = entry.runtime_data.prediction
            for i in range(5):
                prediction.model.update(
                    HeatingSegment(i * 5400, i * 5400 + 3600, 27, 29, 28, None, 2)
                )
            prediction.observe(entry.runtime_data.runtime.connection.snapshot)
            entry.runtime_data.async_set_updated_data(
                entry.runtime_data.runtime.connection.snapshot
            )
            await hass.async_block_till_done()
            state = hass.states.get("sensor.balboa_spa_heating_learning_segments")
            assert state.state == "5"
            assert state.attributes["prediction_quality"] == "learned"
            assert state.attributes["error_scope"] == "pre_update_heating_segments"
            assert hass.states.get("sensor.balboa_spa_heating_prediction_error").state == "0.0"
            report = await async_get_config_entry_diagnostics(hass, entry)
            assert report["prediction"]["samples"] == 5
            assert report["prediction"]["coefficients"] == [2, 0]
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
