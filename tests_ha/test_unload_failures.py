"""An entity-platform unload failure must never retain the physical bus writer."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.balboa_rs485 import async_unload_entry
from custom_components.balboa_rs485._core.state.model import Control
from tools.simulator.server import Simulator

from .test_lifecycle import eventually
from .test_sessions import setup_spa


async def test_failed_platform_unload_still_closes_connection_and_rejects_commands(
    hass, socket_enabled
):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        coordinator = entry.runtime_data
        try:
            await eventually(lambda: coordinator.runtime.metadata_complete)
            with patch.object(
                hass.config_entries, "async_unload_platforms", AsyncMock(return_value=False)
            ):
                assert not await async_unload_entry(hass, entry)
            assert not coordinator.runtime.connection.running
            await eventually(lambda: simulator.active_connections == 0)
            with pytest.raises(HomeAssistantError):
                await coordinator.async_command(Control.LIGHT1, True)
            assert simulator.physical_commands == 0
        finally:
            await coordinator.async_close()
            await hass.config_entries.async_unload(entry.entry_id)


async def test_failed_observation_task_does_not_prevent_socket_cleanup(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        coordinator = entry.runtime_data
        try:
            await eventually(lambda: coordinator.runtime.metadata_complete)
            coordinator._watcher.cancel()
            await asyncio.gather(coordinator._watcher, return_exceptions=True)

            async def failed():
                raise RuntimeError("test observation failure")

            coordinator._watcher = asyncio.create_task(failed())
            await asyncio.gather(coordinator._watcher, return_exceptions=True)
            with pytest.raises(RuntimeError, match="test observation failure"):
                await coordinator.async_close()
            assert not coordinator.runtime.connection.running
            await eventually(lambda: simulator.active_connections == 0)
        finally:
            await coordinator.async_close()
            await hass.config_entries.async_unload(entry.entry_id)


async def test_stop_and_unload_can_close_concurrently(hass, socket_enabled):
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        entry = await setup_spa(hass, simulator)
        coordinator = entry.runtime_data
        try:
            await asyncio.gather(coordinator.async_close(), coordinator.async_close())
            assert not coordinator.runtime.connection.running
            await eventually(lambda: simulator.active_connections == 0)
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
