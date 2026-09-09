"""Overlapping native aliases must share one bounded physical pump goal."""

import asyncio
from contextlib import suppress

import pytest
from homeassistant.exceptions import HomeAssistantError

from tools.simulator.server import Simulator

from .test_lifecycle import eventually
from .test_sessions import setup_spa


async def pump_service(hass, domain, service, **data):
    await hass.services.async_call(domain, service, data, blocking=True)


async def test_identical_fan_and_select_requests_do_not_supersede_or_restart_steps(
    hass, socket_enabled
):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        tasks = []
        try:
            tasks.append(
                asyncio.create_task(
                    pump_service(
                        hass,
                        "fan",
                        "set_percentage",
                        entity_id="fan.balboa_spa_pump_1",
                        percentage=100,
                    )
                )
            )
            await eventually(lambda: simulator.physical_commands == 1)
            identifier = entry.runtime_data.runtime.engine.pending_transaction.action.intent.id
            tasks.append(
                asyncio.create_task(
                    pump_service(
                        hass,
                        "select",
                        "select_option",
                        entity_id="select.balboa_spa_pump_1_mode",
                        option="jets",
                    )
                )
            )
            await asyncio.gather(*tasks)
            assert simulator.physical_commands == 2
            assert simulator.stats.connections == 1
            assert {row.action.intent.id for row in entry.runtime_data.runtime.engine.history} == {
                identifier
            }
        finally:
            for task in tasks:
                task.cancel()
                with suppress(asyncio.CancelledError, HomeAssistantError):
                    await task
            await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("cancel_both", [False, True])
async def test_one_cancelled_duplicate_does_not_cancel_the_remaining_waiter(
    hass, socket_enabled, cancel_both
):
    from custom_components.balboa_rs485._core.command.engine import Stage
    from custom_components.balboa_rs485._core.state.model import Control, PumpState

    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        coordinator = entry.runtime_data
        tasks = []
        try:
            tasks = [asyncio.create_task(coordinator.async_command(Control.PUMP1, PumpState.HIGH))]
            await eventually(lambda: simulator.physical_commands == 1)
            identifier = coordinator.runtime.engine.pending_transaction.action.intent.id
            tasks.append(
                asyncio.create_task(coordinator.async_command(Control.PUMP1, PumpState.HIGH))
            )
            await asyncio.sleep(0)  # Join the already sent intent, before any new status.
            tasks[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await tasks[0]
            if cancel_both:
                tasks[1].cancel()
                with pytest.raises(asyncio.CancelledError):
                    await tasks[1]
                assert coordinator.runtime.engine.intent(identifier).stage == Stage.CANCELLED
                await eventually(lambda: not coordinator.runtime.engine.busy)
                assert simulator.physical_commands == 1
            else:
                await tasks[1]
                assert coordinator.runtime.engine.intent(identifier).stage == Stage.VERIFIED
                assert simulator.physical_commands == 2
            assert coordinator._pending == {}
            assert coordinator._waiters == {}
            assert coordinator._deadlines == {}
        finally:
            for task in tasks:
                task.cancel()
                with suppress(asyncio.CancelledError, HomeAssistantError):
                    await task
            await hass.config_entries.async_unload(entry.entry_id)


async def test_duplicate_keeps_original_deadline_and_different_target_still_supersedes(
    hass, socket_enabled, monkeypatch
):
    from custom_components.balboa_rs485._core.command.engine import Stage
    from custom_components.balboa_rs485._core.state.model import Control, PumpState

    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        coordinator = entry.runtime_data
        runtime = coordinator.runtime
        seen = []
        release = asyncio.Event()

        async def wait(identifier, *, timeout=20):  # noqa: ASYNC109 - runtime API boundary
            seen.append((identifier, timeout))
            await release.wait()
            return runtime.engine.intent(identifier)

        monkeypatch.setattr(runtime, "wait_for_intent", wait)
        tasks = []
        try:
            tasks.append(
                asyncio.create_task(coordinator.async_command(Control.PUMP1, PumpState.HIGH))
            )
            await eventually(lambda: len(seen) == 1)
            tasks.append(
                asyncio.create_task(coordinator.async_command(Control.PUMP1, PumpState.HIGH))
            )
            await eventually(lambda: len(seen) == 2)
            assert seen[0][0] == seen[1][0]
            assert 0 < seen[1][1] < seen[0][1] <= 20
            tasks.append(
                asyncio.create_task(coordinator.async_command(Control.PUMP1, PumpState.LOW))
            )
            await eventually(lambda: len(seen) == 3)
            assert seen[2][0] != seen[0][0]
            assert runtime.engine.intent(seen[0][0]).stage == Stage.SUPERSEDED
            await eventually(lambda: runtime.engine.intent(seen[2][0]).stage == Stage.VERIFIED)
            release.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            assert all(isinstance(result, HomeAssistantError) for result in results[:2])
            assert results[2] is None
            assert simulator.physical_commands == 1
        finally:
            release.set()
            for task in tasks:
                task.cancel()
                with suppress(asyncio.CancelledError, HomeAssistantError):
                    await task
            await hass.config_entries.async_unload(entry.entry_id)
