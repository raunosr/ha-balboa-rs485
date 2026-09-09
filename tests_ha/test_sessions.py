"""Public HA session actions against the real runtime and loopback spa."""

import pytest
from homeassistant.core import CoreState
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tools.simulator.server import Simulator

from .test_lifecycle import eventually


async def test_existing_but_unreadable_storage_never_becomes_an_empty_session(
    hass, socket_enabled, monkeypatch
):
    import os.path

    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        try:
            assert await hass.config_entries.async_unload(entry.entry_id)
            original_load, original_isfile = Store.async_load, os.path.isfile
            suffix = f"balboa_rs485.session.{entry.entry_id}"

            async def unreadable(self):
                # Store moves a corrupt JSON file aside and returns None. That
                # boundary result must not be mistaken for first installation.
                return None if self.path.endswith(suffix) else await original_load(self)

            with monkeypatch.context() as boundary:
                boundary.setattr(Store, "async_load", unreadable)
                boundary.setattr(
                    os.path,
                    "isfile",
                    lambda path: True if str(path).endswith(suffix) else original_isfile(path),
                )
                assert await hass.config_entries.async_setup(entry.entry_id)
                await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
                assert entry.runtime_data.sessions.runner.storage_failed
                assert simulator.physical_commands == 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "record", [[], {"session": None}, {"connection": {}, "session": {"broken": True}}]
)
async def test_invalid_or_other_endpoint_storage_blocks_sessions_not_observations(
    hass, socket_enabled, record
):
    from custom_components.balboa_rs485.sessions import session_store

    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        try:
            assert await hass.config_entries.async_unload(entry.entry_id)
            await session_store(hass, entry.entry_id).async_save(record)
            assert await hass.config_entries.async_setup(entry.entry_id)
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            assert entry.runtime_data.sessions.runner.storage_failed
            assert hass.states.get("climate.balboa_spa").state != "unavailable"
            sensor = hass.states.get("sensor.balboa_spa_heating_session")
            assert sensor.state == "unknown"
            assert sensor.attributes["blocked_reason"] == "storage_error"
            with pytest.raises(ServiceValidationError, match="storage"):
                await action(
                    hass,
                    entry,
                    "start_heating_session",
                    target_temperature=37,
                    maintenance_temperature=27,
                    duration="01:00:00",
                )
            assert simulator.physical_commands == 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_logged_but_swallowed_store_write_failure_never_sends_heating(
    hass, socket_enabled, monkeypatch
):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        try:

            async def failed_save(self, data):
                pass  # HA's Store can log a write failure without raising it.

            with monkeypatch.context() as boundary:
                boundary.setattr(Store, "async_save", failed_save)
                with pytest.raises(ServiceValidationError, match="storage"):
                    await action(
                        hass,
                        entry,
                        "start_heating_session",
                        target_temperature=37,
                        maintenance_temperature=27,
                        duration="01:00:00",
                    )
            assert entry.runtime_data.sessions.session is None
            assert simulator.physical_commands == 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_periodic_expiry_storage_failure_is_visible_and_does_not_write(
    hass, socket_enabled, monkeypatch
):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        try:
            await action(
                hass,
                entry,
                "start_heating_session",
                target_temperature=37,
                maintenance_temperature=27,
                duration="00:00:02",
            )
            await eventually(lambda: simulator.target_temperature == 37)

            async def failed_save(self, data):
                pass

            with monkeypatch.context() as boundary:
                boundary.setattr(Store, "async_save", failed_save)
                await eventually(lambda: entry.runtime_data.sessions.runner.storage_failed)
                await eventually(
                    lambda: (
                        hass.states.get("sensor.balboa_spa_heating_session").attributes[
                            "blocked_reason"
                        ]
                        == "storage_error"
                    )
                )
            assert simulator.physical_commands == 1
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_manual_climate_setpoint_durably_abandons_session(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        try:
            await action(
                hass,
                entry,
                "start_heating_session",
                target_temperature=37,
                maintenance_temperature=27,
                duration="01:00:00",
            )
            await eventually(lambda: simulator.target_temperature == 37)
            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": "climate.balboa_spa", "temperature": 37.7},
                    blocking=True,
                )
            assert entry.runtime_data.sessions.session is not None
            await hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": "climate.balboa_spa", "temperature": 36},
                blocking=True,
            )
            assert entry.runtime_data.sessions.session is None
            assert await hass.config_entries.async_unload(entry.entry_id)
            assert await hass.config_entries.async_setup(entry.entry_id)
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            assert entry.runtime_data.sessions.session is None
            assert simulator.target_temperature == 36
            assert simulator.physical_commands == 2
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_adjust_actions_and_session_sensor_follow_observed_restoration(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        try:
            await action(
                hass,
                entry,
                "start_heating_session",
                target_temperature=37,
                maintenance_temperature=27,
                duration="01:00:00",
            )
            await eventually(lambda: simulator.target_temperature == 37)
            end = entry.runtime_data.sessions.session.end_time
            await action(hass, entry, "extend_heating_session")
            assert entry.runtime_data.sessions.session.end_time == end + 1800
            await action(hass, entry, "reduce_heating_session", duration="02:00:00")
            await eventually(lambda: entry.runtime_data.sessions.session is None)
            await eventually(
                lambda: hass.states.get("sensor.balboa_spa_heating_session").state == "idle"
            )
            assert simulator.target_temperature == 27
            assert simulator.physical_commands == 2
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def setup_spa(hass, simulator, *, controls=True, mode="classic-rs485"):
    entry = MockConfigEntry(
        domain="balboa_rs485",
        title="Balboa Spa",
        data={
            "host": "127.0.0.1",
            "port": simulator.port,
            "protocol_mode": mode,
            "accept_direct_bus_risk": mode == "direct-rs485-tcp",
        },
        options={"enable_controls": controls},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
    return entry


async def action(hass, entry, name, **data):
    await hass.services.async_call(
        "balboa_rs485", name, {"config_entry_id": entry.entry_id, **data}, blocking=True
    )


async def test_disabled_controls_latch_expiry_and_restore_on_reenable(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        try:
            await action(
                hass,
                entry,
                "start_heating_session",
                target_temperature=37,
                maintenance_temperature=27,
                duration="00:00:02",
            )
            await eventually(lambda: simulator.target_temperature == 37)
            hass.config_entries.async_update_entry(entry, options={"enable_controls": False})
            await hass.async_block_till_done()
            await eventually(
                lambda: hass.states.get("sensor.balboa_spa_heating_session").state == "restoring"
            )
            assert simulator.physical_commands == 1
            assert (
                hass.states.get("sensor.balboa_spa_heating_session").attributes["blocked_reason"]
                == "controls_disabled"
            )
            hass.config_entries.async_update_entry(entry, options={"enable_controls": True})
            await eventually(lambda: entry.runtime_data.sessions.session is None)
            assert simulator.physical_commands == 2
            assert simulator.stats.connections == 1
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_shutdown_refuses_session_mutation_before_deferred_store_save(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        previous = hass.state
        try:
            await action(
                hass,
                entry,
                "start_heating_session",
                target_temperature=37,
                maintenance_temperature=27,
                duration="01:00:00",
            )
            await eventually(lambda: simulator.target_temperature == 37)
            hass.set_state(CoreState.stopping)
            with pytest.raises(ServiceValidationError, match="storage"):
                await action(hass, entry, "cancel_heating_session")
            assert simulator.physical_commands == 1
        finally:
            hass.set_state(previous)
            await hass.config_entries.async_unload(entry.entry_id)


async def test_removing_entry_clears_only_its_session_storage(hass, socket_enabled):
    from custom_components.balboa_rs485.sessions import session_store

    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        await action(
            hass,
            entry,
            "start_heating_session",
            target_temperature=37,
            maintenance_temperature=27,
            duration="01:00:00",
        )
        store = session_store(hass, entry.entry_id)
        other = session_store(hass, "unrelated-entry")
        await other.async_save({"session": None, "connection": {}})
        assert await store.async_load() is not None
        assert await hass.config_entries.async_remove(entry.entry_id)
        # The HA test fixture retains loaded _data on the old Store instance.
        # A fresh owner must see the removed durable record, not that local copy.
        assert await session_store(hass, entry.entry_id).async_load() is None
        assert await other.async_load() is not None


async def test_actions_reject_unloaded_entries_and_invalid_deadlines(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        try:
            for extra in (
                {},
                {"duration": "01:00:00", "end_time": "18:00"},
                {"end_time": "2020-01-01T18:00:00+03:00"},
            ):
                with pytest.raises(ServiceValidationError):
                    await action(
                        hass,
                        entry,
                        "start_heating_session",
                        target_temperature=37,
                        maintenance_temperature=27,
                        **extra,
                    )
            with pytest.raises(ServiceValidationError, match="positive"):
                await action(hass, entry, "extend_heating_session", duration="00:00:00")
            assert simulator.physical_commands == 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
        with pytest.raises(ServiceValidationError, match="loaded"):
            await action(hass, entry, "cancel_heating_session")


async def test_loaded_expired_session_restores_only_maintenance(hass, socket_enabled):
    from custom_components.balboa_rs485.sessions import session_store

    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        try:
            await action(
                hass,
                entry,
                "start_heating_session",
                target_temperature=37,
                maintenance_temperature=27,
                duration="01:00:00",
            )
            await eventually(lambda: simulator.target_temperature == 37)
            assert await hass.config_entries.async_unload(entry.entry_id)
            store = session_store(hass, entry.entry_id)
            saved = await store.async_load()
            saved["session"]["start_time"] = 100
            saved["session"]["end_time"] = 200
            await store.async_save(saved)
            assert await hass.config_entries.async_setup(entry.entry_id)
            await eventually(lambda: entry.runtime_data.sessions.session is None)
            assert simulator.target_temperature == 27
            assert simulator.physical_commands == 2
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_session_start_and_cancel_use_observed_setpoints(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        try:
            await action(
                hass,
                entry,
                "start_heating_session",
                target_temperature=37,
                maintenance_temperature=27,
                duration="01:00:00",
            )
            await eventually(lambda: simulator.target_temperature == 37)
            await eventually(
                lambda: hass.states.get("climate.balboa_spa").attributes["temperature"] == 37
            )
            await action(hass, entry, "cancel_heating_session")
            await eventually(lambda: simulator.target_temperature == 27)
            await eventually(
                lambda: hass.states.get("climate.balboa_spa").attributes["temperature"] == 27
            )
            assert simulator.physical_commands == 2
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_restart_preserves_session_without_replaying_a_command(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        try:
            await action(
                hass,
                entry,
                "start_heating_session",
                target_temperature=37,
                maintenance_temperature=27,
                duration="01:00:00",
            )
            await eventually(lambda: simulator.target_temperature == 37)
            assert await hass.config_entries.async_unload(entry.entry_id)
            assert await hass.config_entries.async_setup(entry.entry_id)
            await eventually(lambda: entry.runtime_data.runtime.metadata_complete)
            assert simulator.physical_commands == 1
            await action(hass, entry, "cancel_heating_session")
            await eventually(lambda: simulator.target_temperature == 27)
            assert simulator.physical_commands == 2
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
