"""Native observations require fresh status, not writable channel ownership."""

from dataclasses import replace

from pytest_homeassistant_custom_component.common import MockConfigEntry

from balboa_rs485.protocol.frames import Frame
from tools.simulator.server import Simulator, load_status_fixture

from .test_lifecycle import eventually


async def test_native_water_sensor_works_read_only_and_expires_with_status(hass, socket_enabled):
    async with Simulator(port=0, interval=0.01, transport_lab=True) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={
                "host": "127.0.0.1",
                "port": simulator.port,
                "protocol_mode": "unknown-read-only",
            },
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            entity_id = "sensor.balboa_spa_water_temperature"
            await eventually(lambda: hass.states.get(entity_id) is not None)
            assert hass.states.get(entity_id).state == "27.0"
            assert hass.states.get(entity_id).attributes["device_class"] == "temperature"
            assert hass.states.get("climate.balboa_spa").state == "unavailable"
            connection = entry.runtime_data.runtime.connection
            connection.timing = replace(
                connection.timing, degrade_after=0.1, stale_after=0.2, recover_after=0.5
            )
            simulator.scenario = "unknown-protocol"
            await eventually(lambda: hass.states.get(entity_id).state == "unavailable")
            simulator.scenario = "normal"
            await eventually(lambda: hass.states.get(entity_id).state == "27.0")
            assert simulator.stats.received_bytes == 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_safety_observations_follow_packets_without_writes(hass, socket_enabled, monkeypatch):
    payload = bytearray(load_status_fixture().payload)
    payload[0], payload[1], payload[6] = 5, 3, 4
    payload[9], payload[10], payload[21] = 0x23, 0x14, 8
    monkeypatch.setattr(
        "tools.simulator.server.load_status_fixture",
        lambda: Frame(255, 175, 19, bytes(payload)),
    )
    async with Simulator(port=0, interval=0.01, transport_lab=True) as simulator:
        entry = MockConfigEntry(
            domain="balboa_rs485",
            title="Balboa Spa",
            data={"host": "127.0.0.1", "port": simulator.port, "protocol_mode": "auto"},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        expected = {
            "binary_sensor.balboa_spa_heater_running": "on",
            "binary_sensor.balboa_spa_hold": "on",
            "binary_sensor.balboa_spa_priming": "off",
            "binary_sensor.balboa_spa_panel_locked": "on",
            "binary_sensor.balboa_spa_settings_locked": "on",
            "sensor.balboa_spa_heater_state": "heating",
            "sensor.balboa_spa_heating_mode": "ready",
            "sensor.balboa_spa_temperature_range": "high",
            "sensor.balboa_spa_reminder": "clean_filter",
            "sensor.balboa_spa_clock_format": "24h",
            "sensor.balboa_spa_spa_clock": "12:00",
        }
        try:
            await eventually(lambda: all(hass.states.get(key) is not None for key in expected))
            assert {key: hass.states.get(key).state for key in expected} == expected
            assert (
                "device_class"
                not in hass.states.get("binary_sensor.balboa_spa_panel_locked").attributes
            )
            payload[0], payload[1], payload[6] = 1, 1, 99
            payload[9], payload[10], payload[21], payload[5] = 1, 0x30, 0, 3
            expected.update(
                {
                    "binary_sensor.balboa_spa_heater_running": "unknown",
                    "binary_sensor.balboa_spa_hold": "off",
                    "binary_sensor.balboa_spa_priming": "on",
                    "binary_sensor.balboa_spa_panel_locked": "off",
                    "binary_sensor.balboa_spa_settings_locked": "off",
                    "sensor.balboa_spa_heater_state": "unknown",
                    "sensor.balboa_spa_heating_mode": "unknown",
                    "sensor.balboa_spa_temperature_range": "low",
                    "sensor.balboa_spa_reminder": "none",
                    "sensor.balboa_spa_clock_format": "12h",
                }
            )
            await eventually(
                lambda: all(hass.states.get(k).state == v for k, v in expected.items())
            )
            payload[1], payload[6], payload[3] = 3, 99, 24
            await eventually(
                lambda: hass.states.get("sensor.balboa_spa_reminder").state == "unrecognized"
            )
            assert hass.states.get("sensor.balboa_spa_reminder").attributes["reminder_code"] == 99
            assert hass.states.get("sensor.balboa_spa_spa_clock").state == "unknown"
            payload[1], payload[10] = 0, 0x20
            await eventually(
                lambda: hass.states.get("sensor.balboa_spa_heater_state").state == "waiting"
            )
            assert hass.states.get("binary_sensor.balboa_spa_heater_running").state == "off"
            connection = entry.runtime_data.runtime.connection
            connection.timing = replace(
                connection.timing, degrade_after=0.1, stale_after=0.2, recover_after=0.5
            )
            simulator.scenario = "unknown-protocol"
            await eventually(
                lambda: all(hass.states.get(k).state == "unavailable" for k in expected)
            )
            assert simulator.stats.received_bytes == 0
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
