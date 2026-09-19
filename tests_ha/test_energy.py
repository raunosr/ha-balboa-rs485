"""Energy metadata, options and durability in actual HA, never a production endpoint."""

from dataclasses import replace
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest
import voluptuous_serialize
from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE
from homeassistant.core import CoreState
from homeassistant.helpers import config_validation as cv
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.balboa_rs485._core.energy import EnergyCounter
from custom_components.balboa_rs485._core.protocol.configuration import Configuration, Query
from custom_components.balboa_rs485._core.protocol.frames import Frame
from custom_components.balboa_rs485._core.protocol.messages import HeatState, decode_message
from custom_components.balboa_rs485._core.transport.connection import ConnectionState
from custom_components.balboa_rs485.coordinator import SpaCoordinator
from custom_components.balboa_rs485.energy import EnergyController, energy_store
from custom_components.balboa_rs485.sensor import EstimatedEnergySensor, EstimatedPowerSensor
from tools.simulator.server import Simulator, configuration_fixture, load_status_fixture

from .test_lifecycle import eventually
from .test_sessions import setup_spa


def controller(hass, **options):
    entry = MockConfigEntry(
        domain="balboa_rs485",
        title="Balboa Spa",
        data={"host": "127.0.0.1", "port": 8899, "protocol_mode": "classic-rs485"},
        options={"enable_energy_estimate": True, **options},
    )
    entry.add_to_hass(hass)
    return SpaCoordinator(hass, entry).energy


def snapshot(energy, at, sequence=1, epoch=1):
    initial = energy.coordinator.runtime.connection.snapshot
    return replace(
        initial,
        state=ConnectionState.READY,
        epoch=epoch,
        status_sequence=sequence,
        configuration=Configuration(
            decode_message(configuration_fixture(Query.INFORMATION)),
            decode_message(configuration_fixture(Query.CAPABILITIES)),
        ),
        status=replace(
            decode_message(load_status_fixture()),
            heat_state=HeatState.HEATING,
            pumps_raw=(0,) * 6,
            lights_raw=(0, 0),
            circulation_pump=False,
        ),
        health=replace(initial.health, status_stale=False, ready_missing=False, last_status=at),
    )


def ambiguous_circulation_snapshot(energy, at, sequence=1, *, circulation_running=False):
    current = snapshot(energy, at, sequence)
    return replace(
        current,
        configuration=replace(
            current.configuration,
            capabilities=decode_message(Frame(10, 191, 46, b"\x16\0\x01\x50\0\0")),
        ),
        status=replace(
            current.status, heat_state=HeatState.OFF, circulation_pump=circulation_running
        ),
    )


def update_options(energy, cached_snapshot, **changes):
    with patch.object(
        type(energy.coordinator.runtime.connection),
        "snapshot",
        new_callable=PropertyMock,
        return_value=cached_snapshot,
    ):
        hass = energy.coordinator.hass
        hass.config_entries.async_update_entry(
            energy.coordinator.entry,
            options={**energy.coordinator.entry.options, **changes},
        )
        energy.coordinator.async_options_updated()


@pytest.mark.parametrize(
    "circulation,running,expected",
    [
        ("auto", False, None),
        ("absent", False, 40),
        ("absent", True, 40),
        ("present", False, 40),
        ("present", True, 290),
    ],
)
async def test_circulation_configuration_preserves_the_configured_idle_load(
    hass, circulation, running, expected
):
    energy = controller(hass, energy_circulation=circulation, energy_powers={"electronics_w": 40})
    energy.observe(ambiguous_circulation_snapshot(energy, 100, circulation_running=running))
    observed = ambiguous_circulation_snapshot(energy, 105, 2, circulation_running=running)
    energy.observe(observed)
    energy.coordinator.async_set_updated_data(observed)
    assert energy.watts == expected
    assert energy.counter.known_seconds == (0 if expected is None else 5)
    assert energy.attributes["circulation_configuration"] == circulation
    assert energy.attributes["circulation_configuration_required"] is (circulation == "auto")
    power = EstimatedPowerSensor(energy.coordinator)
    assert power.extra_state_attributes["circulation_configuration_required"] is (
        circulation == "auto"
    )
    if expected is not None:
        assert energy.counter.kwh == pytest.approx(expected * 5 / 3_600_000)
    stale = ambiguous_circulation_snapshot(energy, 110, 3)
    energy.observe(replace(stale, health=replace(stale.health, status_stale=True)))
    assert energy.watts is None
    assert not energy.attributes["circulation_configuration_required"]


@pytest.mark.parametrize(
    "changes,expected_watts",
    [
        ({"energy_circulation": "present"}, 290),
        ({"energy_powers": {"electronics_w": 60}}, 60),
    ],
)
async def test_options_callback_excludes_cached_status_after_accounting_change(
    hass, changes, expected_watts
):
    energy = controller(hass, energy_circulation="absent", energy_powers={"electronics_w": 40})
    for at, sequence in [(100, 1), (105, 2)]:
        energy.observe(
            ambiguous_circulation_snapshot(energy, at, sequence, circulation_running=True)
        )
    await energy.async_checkpoint()
    committed = energy.committed_kwh
    assert committed == pytest.approx(40 * 5 / 3_600_000)
    update_options(
        energy,
        ambiguous_circulation_snapshot(energy, 105, 2, circulation_running=True),
        **changes,
    )
    assert energy.watts == expected_watts
    energy.observe(ambiguous_circulation_snapshot(energy, 110, 3, circulation_running=True))
    assert energy.counter.kwh == committed
    assert energy.committed_kwh == committed
    energy.observe(ambiguous_circulation_snapshot(energy, 115, 4, circulation_running=True))
    assert energy.counter.kwh == pytest.approx(committed + expected_watts * 5 / 3_600_000)
    assert energy.counter.known_seconds == 10
    await energy.async_close()


async def test_reenabling_does_not_count_a_cached_observation_from_the_disabled_period(hass):
    energy = controller(hass, energy_circulation="absent", energy_powers={"electronics_w": 40})
    energy.observe(ambiguous_circulation_snapshot(energy, 100))
    cached = ambiguous_circulation_snapshot(energy, 105, 2)
    energy.observe(cached)
    committed = energy.counter.kwh
    assert committed == pytest.approx(40 * 5 / 3_600_000)
    update_options(energy, cached, enable_energy_estimate=False)
    cached = ambiguous_circulation_snapshot(energy, 110, 3)
    energy.observe(cached)
    assert energy.watts is None
    update_options(energy, cached, enable_energy_estimate=True)
    assert energy.watts == 40
    energy.observe(ambiguous_circulation_snapshot(energy, 115, 4))
    assert energy.counter.kwh == committed
    energy.observe(ambiguous_circulation_snapshot(energy, 120, 5))
    assert energy.counter.kwh == pytest.approx(committed + 40 * 5 / 3_600_000)
    assert energy.counter.known_seconds == 10
    await energy.async_close()


@pytest.mark.parametrize("value", ["invalid", True, 1, None])
async def test_invalid_circulation_configuration_is_isolated_from_controls(hass, value):
    energy = controller(hass, energy_circulation=value, enable_controls=True)
    assert not energy.enabled
    assert energy.coordinator.controls_enabled
    energy.observe(snapshot(energy, 100))
    assert energy.watts is None


async def test_counter_is_published_only_after_checkpoint_and_restores_without_backfill(hass):
    energy = controller(hass)
    await energy.async_load()
    energy.observe(snapshot(energy, 100))
    energy.observe(snapshot(energy, 105, 2))
    assert energy.watts == 3020
    assert energy.committed_kwh is None
    assert energy.counter.kwh == pytest.approx(3020 * 5 / 3_600_000)
    await energy.async_checkpoint()
    committed = energy.committed_kwh
    assert committed == energy.counter.kwh
    assert energy.attributes["observed_seconds"] == 5
    restored = EnergyController(energy.coordinator)
    await restored.async_load()
    restored.observe(snapshot(restored, 5000))
    assert restored.counter.kwh == committed
    await restored.async_close()
    await energy.async_close()


async def test_refresh_stale_duplicates_and_epoch_do_not_invent_energy(hass):
    energy = controller(hass)
    initial = snapshot(energy, 100)
    energy.observe(replace(initial, state=ConnectionState.SYNCHRONIZING))
    assert energy.watts is None  # no ready observation in this epoch yet
    # The following synthetic timestamps start a separate deterministic interval.
    energy.counter = EnergyCounter()
    energy.observe(initial)
    energy.observe(snapshot(energy, 105, 2))
    energy.observe(snapshot(energy, 105, 2))
    assert energy.counter.known_seconds == 5
    energy.observe(replace(snapshot(energy, 110, 3), state=ConnectionState.SYNCHRONIZING))
    assert energy.counter.known_seconds == 10
    energy.observe(snapshot(energy, 115, 4, epoch=2))
    assert energy.counter.unknown_seconds == 5
    current = snapshot(energy, 120, 5, epoch=2)
    energy.observe(replace(current, health=replace(current.health, status_stale=True)))
    assert energy.watts is None
    energy.observe(replace(current, status=None))
    assert energy.watts is None


@pytest.mark.parametrize("record", [{}, {"kwh": -1, "known_seconds": 0, "unknown_seconds": 0}])
async def test_corrupt_storage_freezes_energy_not_controls(hass, record):
    energy = controller(hass)
    await energy.store.async_save(record)
    await energy.async_load()
    assert energy.storage_error
    energy.observe(snapshot(energy, 100))
    await energy.async_checkpoint()
    assert energy.committed_kwh is None
    assert await energy.store.async_load() == record


async def test_unreadable_file_and_load_timeout_do_not_reset(hass, monkeypatch):
    energy = controller(hass)
    monkeypatch.setattr("os.path.isfile", lambda path: True)
    monkeypatch.setattr(energy.store, "async_load", AsyncMock(return_value=None))
    await energy.async_load()
    assert energy.storage_error and energy.committed_kwh is None
    other = controller(hass)
    monkeypatch.setattr(other.store, "async_load", AsyncMock(side_effect=TimeoutError))
    await other.async_load()
    assert other.storage_error


async def test_write_failure_retry_and_stopping_do_not_publish_unstored_energy(hass, monkeypatch):
    energy = controller(hass)
    await energy.async_checkpoint()
    assert energy.committed_kwh == 0
    energy.counter = EnergyCounter(2, 60, 10)
    original = energy.store.async_save
    monkeypatch.setattr(energy.store, "async_save", AsyncMock(side_effect=OSError))
    await energy.async_checkpoint()
    await energy.async_checkpoint()  # repeated failure is not log spam
    assert energy.storage_error and energy.committed_kwh == 0
    monkeypatch.setattr(energy.store, "async_save", original)
    await energy.async_checkpoint()
    assert not energy.storage_error and energy.committed_kwh == 2
    energy.counter.kwh = 3
    hass.set_state(CoreState.stopping)
    await energy.async_checkpoint()
    assert energy.committed_kwh == 2
    hass.set_state(CoreState.final_write)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
    await hass.async_block_till_done()
    assert (await energy.store.async_load())["kwh"] == 3
    hass.set_state(CoreState.running)


async def test_failed_verification_does_not_publish_and_invalid_profile_is_isolated(
    hass, monkeypatch
):
    energy = controller(hass)
    monkeypatch.setattr(energy.store, "async_load", AsyncMock(return_value={}))
    await energy.async_checkpoint()
    assert energy.storage_error and energy.committed_kwh is None
    hass.config_entries.async_update_entry(
        energy.coordinator.entry,
        options={"enable_energy_estimate": True, "energy_powers": {"heater_w": -1}},
    )
    energy.configure()
    assert not energy.enabled
    energy.observe(snapshot(energy, 100))
    assert energy.watts is None
    await energy.async_checkpoint()


async def test_checkpoint_task_and_disabled_counter_preservation(hass, monkeypatch):
    monkeypatch.setattr("custom_components.balboa_rs485.energy.CHECKPOINT_SECONDS", 0.01)
    energy = controller(hass)
    energy.counter = EnergyCounter(7, 50, 20)
    energy.start()
    await eventually(lambda: energy.committed_kwh == 7)
    hass.config_entries.async_update_entry(energy.coordinator.entry, options={})
    energy.configure()
    assert energy.counter.kwh == 7 and energy.watts is None
    await energy.async_close()
    assert energy._task is None


async def test_sensor_metadata_frozen_offline_total_and_options_without_reconnect(
    hass, socket_enabled
):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator, controls=False)
        try:
            energy = entry.runtime_data.energy
            assert not energy.enabled
            assert not EstimatedEnergySensor(entry.runtime_data).available
            flow = await hass.config_entries.options.async_init(entry.entry_id)
            result = await hass.config_entries.options.async_configure(
                flow["flow_id"],
                user_input={
                    "enable_controls": False,
                    "fallback_heating_rate": 2,
                    "enable_energy_estimate": True,
                },
            )
            assert result["step_id"] == "energy"
            assert voluptuous_serialize.convert(
                result["data_schema"], custom_serializer=cv.custom_serializer
            )
            await hass.config_entries.options.async_configure(
                flow["flow_id"],
                user_input={
                    "heater_w": 3000,
                    "pump1_low_w": 350,
                    "electronics_w": 40,
                    "energy_circulation": "absent",
                },
            )
            await hass.async_block_till_done()
            await eventually(lambda: energy.watts is not None)
            assert entry.options["energy_circulation"] == "absent"
            assert energy.attributes["circulation_configuration"] == "absent"
            assert energy.profile["electronics_w"] == 40
            await energy.async_checkpoint()
            await hass.async_block_till_done()
            state = hass.states.get("sensor.balboa_spa_estimated_energy")
            assert state is not None and float(state.state) >= 0
            assert state.attributes["device_class"] == "energy"
            assert state.attributes["state_class"] == "total_increasing"
            entity = EstimatedEnergySensor(entry.runtime_data)
            assert entity.device_class == "energy" and entity.state_class == "total_increasing"
            assert entity.native_unit_of_measurement == "kWh"
            assert entity.available and entity.extra_state_attributes["estimated"]
            power = EstimatedPowerSensor(entry.runtime_data)
            assert power.available and power.native_value is not None
            assert power.state_class == "measurement" and power.native_unit_of_measurement == "W"
            counter = energy.counter.kwh
            old_epoch = entry.runtime_data.runtime.connection.snapshot.epoch
            # Accounting preferences never reconnect or rewrite previously accrued kWh.
            hass.config_entries.async_update_entry(
                entry,
                options={
                    **entry.options,
                    "energy_circulation": "present",
                    "energy_powers": {**energy.profile, "heater_w": 2500},
                },
            )
            await hass.async_block_till_done()
            assert energy.counter.kwh >= counter
            assert energy.attributes["circulation_configuration"] == "present"
            assert energy.profile["electronics_w"] == 40
            assert entry.runtime_data.runtime.connection.snapshot.epoch == old_epoch
            assert simulator.stats.connections == 1 and simulator.physical_commands == 0
            await hass.config_entries.async_unload(entry.entry_id)
            assert not power.available
            assert entity.available and entity.native_value is not None
            committed = energy.committed_kwh
            assert await hass.config_entries.async_setup(entry.entry_id)
            await eventually(lambda: entry.runtime_data.energy.watts is not None)
            assert entry.runtime_data.energy.committed_kwh == committed
            assert entry.runtime_data.energy.attributes["circulation_configuration"] == "present"
            assert simulator.physical_commands == 0
        finally:
            if hasattr(entry, "runtime_data") and entry.runtime_data._opened:
                await hass.config_entries.async_unload(entry.entry_id)


async def test_disable_before_first_checkpoint_saves_and_entry_deletion_removes_store(hass):
    from custom_components.balboa_rs485 import async_remove_entry

    energy = controller(hass)
    energy.counter = EnergyCounter(0.01, 10, 0)
    hass.config_entries.async_update_entry(energy.coordinator.entry, options={})
    energy.configure()
    await energy.async_close()
    assert energy.committed_kwh == 0.01
    assert await energy.store.async_load() == energy.counter.record()
    await async_remove_entry(hass, energy.coordinator.entry)
    # HA's storage fixture retains the old owner's loaded _data after deletion.
    assert await energy_store(hass, energy.coordinator.entry.entry_id).async_load() is None


async def test_invalid_power_form_returns_error_without_changing_options(hass):
    energy = controller(hass)
    flow = await hass.config_entries.options.async_init(energy.coordinator.entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        user_input={
            "enable_controls": False,
            "fallback_heating_rate": 2,
            "enable_energy_estimate": True,
        },
    )
    # Exercise the step's defensive boundary too; HTTP schema rejects these first.
    handler = hass.config_entries.options._progress[flow["flow_id"]]
    result = await handler.async_step_energy(
        {"heater_w": float("nan"), "energy_circulation": "absent"}
    )
    assert result["errors"] == {"base": "invalid_power"}
    assert result["data_schema"]({})["energy_circulation"] == "absent"
    assert energy.coordinator.entry.options == {"enable_energy_estimate": True}


async def test_invalid_circulation_form_does_not_change_options(hass):
    energy = controller(hass)
    flow = await hass.config_entries.options.async_init(energy.coordinator.entry.entry_id)
    await hass.config_entries.options.async_configure(
        flow["flow_id"],
        user_input={
            "enable_controls": False,
            "fallback_heating_rate": 2,
            "enable_energy_estimate": True,
        },
    )
    handler = hass.config_entries.options._progress[flow["flow_id"]]
    result = await handler.async_step_energy({"energy_circulation": "invalid"})
    assert result["errors"] == {"energy_circulation": "invalid_circulation"}
    assert energy.coordinator.entry.options == {"enable_energy_estimate": True}


async def test_circulation_choice_and_ratings_survive_disabling_and_reenabling(hass):
    energy = controller(hass, energy_circulation="absent", energy_powers={"electronics_w": 40})
    entry = energy.coordinator.entry
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        flow["flow_id"],
        user_input={
            "enable_controls": False,
            "fallback_heating_rate": 2,
            "enable_energy_estimate": False,
        },
    )
    assert entry.options["energy_circulation"] == "absent"
    assert entry.options["energy_powers"]["electronics_w"] == 40
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        user_input={
            "enable_controls": False,
            "fallback_heating_rate": 2,
            "enable_energy_estimate": True,
        },
    )
    assert result["data_schema"]({})["energy_circulation"] == "absent"
    serialized = voluptuous_serialize.convert(
        result["data_schema"], custom_serializer=cv.custom_serializer
    )
    choice = next(field for field in serialized if field["name"] == "energy_circulation")
    assert choice["selector"]["select"]["options"] == ["auto", "absent", "present"]
    assert choice["selector"]["select"]["translation_key"] == "energy_circulation"
    await hass.config_entries.options.async_configure(
        flow["flow_id"], user_input={"heater_w": 2500}
    )
    assert entry.options["energy_circulation"] == "absent"
    assert entry.options["energy_powers"]["electronics_w"] == 40
    assert entry.options["energy_powers"]["heater_w"] == 2500
