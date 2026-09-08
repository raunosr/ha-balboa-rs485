"""HA storage and lifecycle for the independent heating-session runner."""

import asyncio
import logging
import os.path
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ._core.range_session import RangeSession
from ._core.session import Session
from ._core.session_runner import SessionIntent, SessionRunner
from ._core.state.model import Control, Value
from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import SpaCoordinator

_LOGGER = logging.getLogger(__name__)
_STOPPING = (CoreState.stopping, CoreState.final_write, CoreState.stopped)


def session_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    return Store(hass, 1, f"{DOMAIN}.session.{entry_id}", private=True, atomic_writes=True)


class SessionController:
    def __init__(self, coordinator: SpaCoordinator) -> None:
        self.coordinator = coordinator
        self.runner = SessionRunner(
            coordinator.runtime,
            save=self._save,
            enabled=lambda: (
                coordinator.controls_enabled and coordinator.hass.state not in _STOPPING
            ),
            now=lambda: dt_util.utcnow().timestamp(),
        )
        self._task: asyncio.Task[None] | None = None

    @property
    def session(self) -> SessionIntent | None:
        return self.runner.session

    def _store(self) -> Store[dict[str, Any]]:
        return session_store(self.coordinator.hass, self.coordinator.entry.entry_id)

    async def async_load(self) -> None:
        try:
            store = self._store()
            existed = await self.coordinator.hass.async_add_executor_job(os.path.isfile, store.path)
            record = await store.async_load()
            if record is None:
                if existed:
                    raise ValueError("Session storage could not be read")
                return
            if not isinstance(record, dict) or set(record) != {"connection", "session"}:
                raise ValueError("Invalid session storage")
            if record["session"] is not None:
                if record["connection"] != self.coordinator.connection_data:
                    raise ValueError("Stored session belongs to a different spa endpoint")
                saved = record["session"]
                session_type = (
                    RangeSession
                    if isinstance(saved, dict) and saved.get("version") == 2
                    else Session
                )
                self.runner.session = session_type.from_record(saved)
        except Exception:
            self.runner.storage_failed = True
            self.runner.blocked_reason = "storage_error"
            _LOGGER.error("Heating session storage is invalid; repair storage before reloading")

    async def _save(self, session: SessionIntent | None) -> None:
        hass = self.coordinator.hass
        if hass.state in _STOPPING:
            raise ValueError("Heating session changes are unavailable during shutdown")
        record = {
            "connection": self.coordinator.connection_data,
            "session": session.to_record() if session is not None else None,
        }
        await self._store().async_save(record)
        # Store logs some write failures without raising. A fresh Store reads the
        # durable record, not an in-memory value from the just-saved instance.
        if await self._store().async_load() != record:
            raise ValueError("Session storage write could not be verified")

    def start(self) -> None:
        self._task = self.coordinator.entry.async_create_background_task(
            self.coordinator.hass, self._run(), "balboa-heating-session"
        )

    async def async_tick(self) -> None:
        before = self.session, self.runner.blocked_reason
        try:
            await self.runner.async_tick()
        except ValueError:
            _LOGGER.error("Heating session persistence failed; session commands are blocked")
        if before != (self.session, self.runner.blocked_reason):
            self.coordinator.async_set_updated_data(self.coordinator.runtime.connection.snapshot)

    async def _run(self) -> None:
        while True:
            await self.async_tick()
            await asyncio.sleep(0.25)

    async def async_manual_temperature(self, desired: Value) -> None:
        await self.async_manual_setting(Control.TARGET, desired)

    async def async_manual_setting(self, control: Control, desired: Value) -> None:
        await self.runner.async_manual_change(
            control, desired, apply=self.coordinator.async_command
        )

    async def async_close(self) -> None:
        self.runner.close()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
