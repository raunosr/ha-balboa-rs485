"""A filter edit uses fresh whole-record reads and verified one-socket writes."""

import asyncio
from dataclasses import replace

import pytest

from balboa_rs485.command.engine import CommandEngine, Stage
from balboa_rs485.protocol.messages import FilterCyclesMessage
from balboa_rs485.protocol.settings import FilterSchedule
from balboa_rs485.state.model import Control

from .test_session_runner import lab


async def test_filter_edit_reads_back_preserves_other_cycle_and_serializes_edits():
    async with lab() as (simulator, runtime):
        original = FilterSchedule(runtime.state.filters.cycles)
        await runtime.async_update_filter(1, start=22 * 60, end=2 * 60)
        actual = FilterSchedule(runtime.state.filters.cycles)
        assert actual.cycles[0].start_hour == 22
        assert actual.cycles[0].duration_minutes == 240
        assert actual.cycles[1] == original.cycles[1]
        await asyncio.gather(
            runtime.async_update_filter(1, start=21 * 60),
            runtime.async_update_filter(2, enabled=False),
        )
        actual = FilterSchedule(runtime.state.filters.cycles)
        assert actual.cycles[0].start_hour == 21
        assert actual.cycles[0].duration_minutes == 240
        assert not actual.cycles[1].enabled
        assert simulator.stats.connections == 1
        assert simulator.physical_commands == 3
        assert simulator.stats.rejected_queries == 0


async def test_disabled_filter_controls_send_no_physical_command():
    async with lab() as (simulator, runtime):
        with pytest.raises(ValueError, match="unavailable"):
            await runtime.async_update_filter(2, enabled=False, valid=lambda: False)
        assert simulator.physical_commands == 0


async def test_missing_fresh_filter_read_never_uses_cached_whole_record():
    async with lab() as (simulator, runtime):
        assert runtime.state.filters is not None
        simulator.scenario = "missing-metadata"
        with pytest.raises(ValueError, match="fresh filter"):
            await runtime.async_update_filter(2, enabled=False)
        assert simulator.physical_commands == 0


async def test_filter_read_refreshes_an_external_change_before_preserving_other_cycle():
    async with lab() as (simulator, runtime):
        data = bytearray(simulator.filter_payload)
        data[4:8] = bytes((128 | 18, 15, 3, 0))
        simulator.filter_payload = bytes(data)  # Panel changed after initial metadata query.
        await runtime.async_update_filter(1, start=21 * 60)
        assert simulator.filter_payload[4:] == data[4:]
        assert simulator.physical_commands == 1


async def test_filter_write_lost_with_connection_is_not_replayed_after_reconnect():
    async with lab(scenario="reset-after-command") as (simulator, runtime):
        with pytest.raises(ValueError, match="not verified"):
            await runtime.async_update_filter(1, start=21 * 60)
        await runtime.connection.wait_for(lambda s: s.available and s.epoch >= 2, timeout=4)
        assert simulator.physical_commands == 1
        assert simulator.filter_payload[0] == 21


async def test_write_echo_or_cached_metadata_is_not_filter_confirmation():
    async with lab() as (_, runtime):
        state = runtime.state
        engine = CommandEngine(confirmation_guard=0.01, confirmation_timeout=0.2)
        now = state.observed_at
        state = replace(state, filters_at=now)
        engine.observe(state, now=now)
        desired = FilterSchedule(state.filters.cycles).update(1, start=1260)
        intent = engine.request(Control.FILTERS, desired, now=now)
        step = engine.next_action(now=now)
        engine.sent(step, at=now, cts_at=now)
        echoed = replace(
            state,
            filters=FilterCyclesMessage(desired.frame(), desired.cycles),
            filters_at=None,
            sequence=state.sequence + 1,
            observed_at=now + 0.05,
        )
        engine.observe(echoed, now=now + 0.05)
        assert engine.intent(intent.id).stage != Stage.VERIFIED
        queried = replace(
            echoed, filters_at=now + 0.08, sequence=state.sequence + 2, observed_at=now + 0.1
        )
        engine.observe(queried, now=now + 0.1)
        assert engine.intent(intent.id).stage == Stage.VERIFIED
