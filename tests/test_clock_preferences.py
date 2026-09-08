"""Clock/unit writes are known absolute commands with status-confirmed outcomes."""

import pytest

from balboa_rs485.command.engine import Stage
from balboa_rs485.protocol.commands import set_clock, set_clock_format, set_temperature_unit
from balboa_rs485.protocol.messages import TemperatureUnit
from balboa_rs485.session_runner import SessionRunner
from balboa_rs485.state.model import Control

from .test_session_runner import lab, save_noop, settle


async def test_clock_format_preserves_observed_time_and_clock_edit_preserves_format():
    async with lab() as (simulator, runtime):
        original = runtime.state.status.clock
        intent = runtime.request(Control.CLOCK_FORMAT, True)
        assert (await runtime.wait_for_intent(intent.id, timeout=2)).stage == Stage.VERIFIED
        assert runtime.state.status.clock == original
        assert runtime.state.status.clock_24h
        intent = runtime.request(Control.CLOCK_TIME, 23 * 60 + 59)
        assert (await runtime.wait_for_intent(intent.id, timeout=2)).stage == Stage.VERIFIED
        assert runtime.state.status.clock == "23:59"
        assert runtime.state.status.clock_24h
        assert [r.frame.payload for r in simulator.physical_records] == [b"\x02\x01", b"\x97\x3b"]
        assert [r.frame.message_type for r in simulator.physical_records] == [0x27, 0x21]


async def test_unit_selection_observes_converted_targets_without_temperature_write():
    async with lab() as (simulator, runtime):
        for unit in (TemperatureUnit.FAHRENHEIT, TemperatureUnit.CELSIUS):
            intent = runtime.request(Control.TEMPERATURE_UNIT, unit)
            assert (await runtime.wait_for_intent(intent.id, timeout=2)).stage == Stage.VERIFIED
            assert runtime.state.status.unit == unit
        assert runtime.state.target_temperature == 38
        assert [r.frame.message_type for r in simulator.physical_records] == [0x27, 0x27]


@pytest.mark.parametrize("value", [-1, 1440, True, 5.5])
def test_clock_invalid_minutes_are_rejected(value):
    with pytest.raises(ValueError):
        set_clock(value, True)


def test_clock_and_unit_encoding_require_explicit_types():
    with pytest.raises(ValueError):
        set_clock(720, 1)
    with pytest.raises(ValueError):
        set_clock_format(1)
    with pytest.raises(ValueError):
        set_temperature_unit("C")


async def test_manual_unit_changes_are_serialized_and_rejected_during_bathing():
    async with lab() as (simulator, runtime):
        runner = SessionRunner(runtime, save=save_noop, enabled=lambda: True, now=lambda: 1000)

        async def apply(control, desired):
            intent = runtime.request(control, desired)
            assert (await runtime.wait_for_intent(intent.id, timeout=2)).stage == Stage.VERIFIED

        await runner.async_manual_change(
            Control.TEMPERATURE_UNIT, TemperatureUnit.FAHRENHEIT, apply=apply
        )
        await runner.async_manual_change(
            Control.TEMPERATURE_UNIT, TemperatureUnit.CELSIUS, apply=apply
        )
        await runner.async_start_bathing(end=4600)
        await settle(runner, lambda: runner.session.step == "active")
        with pytest.raises(ValueError, match="End the heating session"):
            await runner.async_manual_change(
                Control.TEMPERATURE_UNIT, TemperatureUnit.FAHRENHEIT, apply=apply
            )
        assert runtime.state.status.unit == TemperatureUnit.CELSIUS
        runner.close()
