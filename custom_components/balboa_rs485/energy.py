"""Optional passive energy estimate, isolated from command and connection lifecycles."""

import asyncio
import logging
import os.path
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers.storage import Store

from ._core.energy import (
    CirculationPump,
    EnergyCounter,
    circulation_pump_present,
    estimate,
    powers,
)
from ._core.state.model import SpaState
from ._core.transport.connection import ConnectionState, Snapshot
from .const import CONF_ENERGY, CONF_ENERGY_CIRCULATION, CONF_ENERGY_POWERS, DOMAIN

if TYPE_CHECKING:
    from .coordinator import SpaCoordinator

_LOGGER = logging.getLogger(__name__)
CHECKPOINT_SECONDS = 30


def energy_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    return Store(hass, 1, f"{DOMAIN}.energy.{entry_id}", private=True, atomic_writes=True)


class EnergyController:
    def __init__(self, coordinator: SpaCoordinator) -> None:
        self.coordinator = coordinator
        self.store = energy_store(coordinator.hass, coordinator.entry.entry_id)
        self.counter = EnergyCounter()
        self.committed_kwh: float | None = None
        self._committed_record = self.counter.record()
        self.watts: float | None = None
        self.storage_error = False
        self._load_failed = False
        self._ready_epoch: int | None = None
        self._last_sample: tuple[int, int, bool] | None = None
        self._task: asyncio.Task[None] | None = None
        self._save_lock = asyncio.Lock()
        self.enabled = False
        self.profile = powers({})
        self.circulation = CirculationPump.AUTO
        self.circulation_configuration_required = False
        self.configure()

    def configure(self) -> None:
        options = self.coordinator.entry.options
        enabled = options.get(CONF_ENERGY) is True
        try:
            profile = powers(options.get(CONF_ENERGY_POWERS, {}))
            circulation = CirculationPump(options.get(CONF_ENERGY_CIRCULATION, "auto"))
        except (ValueError, TypeError, AttributeError):
            # Malformed optional settings must never break physical controls.
            profile, enabled = powers({}), False
            circulation = CirculationPump.AUTO
            _LOGGER.error("Invalid energy estimate settings; estimate disabled")
        if self.profile != profile or self.enabled != enabled or self.circulation != circulation:
            self.counter.break_interval()
            self._last_sample = None
            self.watts = None
            self.circulation_configuration_required = False
        self.enabled, self.profile, self.circulation = enabled, profile, circulation

    async def async_load(self) -> None:
        try:
            async with asyncio.timeout(5):
                existed = await self.coordinator.hass.async_add_executor_job(
                    os.path.isfile, self.store.path
                )
                record = await self.store.async_load()
            if existed and record is None:
                raise ValueError("Existing energy storage was unreadable")
            if record is not None:
                self.counter = EnergyCounter.restore(record)
                self.committed_kwh = self.counter.kwh
                self._committed_record = self.counter.record()
        except (OSError, ValueError, TypeError, TimeoutError):
            self._load_failed = self.storage_error = True
            _LOGGER.error("Energy estimate storage could not be loaded; counter is not reset")

    def observe(self, snapshot: Snapshot) -> None:
        if snapshot.available:
            self._ready_epoch = snapshot.epoch
        refresh = (
            snapshot.state == ConnectionState.SYNCHRONIZING
            and self._ready_epoch == snapshot.epoch
            and not snapshot.health.ready_missing
        )
        state = (
            SpaState(
                snapshot.status,
                snapshot.configuration,
                snapshot.epoch,
                snapshot.status_sequence,
                snapshot.health.last_status or 0,
                snapshot.available,
            )
            if snapshot.status is not None and snapshot.configuration is not None
            else None
        )
        healthy = bool(
            (snapshot.available or refresh)
            and not snapshot.health.status_stale
            and snapshot.health.last_status is not None
            and state is not None
        )
        self.circulation_configuration_required = False
        self.watts = None
        if self.enabled and healthy and state:
            self.circulation_configuration_required = (
                circulation_pump_present(state, self.circulation) is None
            )
            self.watts = estimate(state, self.profile, circulation=self.circulation)
        key = (snapshot.epoch, snapshot.status_sequence, healthy)
        if not self.enabled or self._load_failed or key == self._last_sample:
            return
        self._last_sample = key
        at = snapshot.health.last_status if healthy else self.coordinator.hass.loop.time()
        assert at is not None
        self.counter.sample(at, self.watts, snapshot.epoch)

    def start(self) -> None:
        self._task = self.coordinator.entry.async_create_background_task(
            self.coordinator.hass, self._checkpoint_loop(), "balboa-energy-checkpoint"
        )

    async def _checkpoint_loop(self) -> None:
        while True:
            await asyncio.sleep(CHECKPOINT_SECONDS)
            await self.async_checkpoint()

    async def async_checkpoint(self) -> None:
        if self._load_failed or (
            not self.enabled
            and self.committed_kwh is None
            and not (self.counter.known_seconds or self.counter.unknown_seconds)
        ):
            return
        async with self._save_lock:
            record = self.counter.record()
            if (
                self.committed_kwh is not None
                and record == self._committed_record
                and not self.storage_error
            ):
                return
            try:
                async with asyncio.timeout(5):
                    await self.store.async_save(record)
                    # HA defers stopping-state writes until its final-write event.
                    if self.coordinator.hass.state == CoreState.stopping:
                        return
                    if await self.store.async_load() != record:
                        raise ValueError("Energy checkpoint verification failed")
            except (OSError, ValueError, TypeError, TimeoutError):
                if not self.storage_error:
                    _LOGGER.error("Energy estimate checkpoint failed; retaining published total")
                self.storage_error = True
            else:
                self.storage_error = False
                self.committed_kwh = record["kwh"]
                self._committed_record = record
            self.coordinator.async_set_updated_data(self.coordinator.runtime.connection.snapshot)

    async def async_close(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self.watts = None
        self.circulation_configuration_required = False
        self.counter.break_interval()
        await self.async_checkpoint()

    @property
    def configuration_attributes(self) -> dict[str, str | bool]:
        return {
            "circulation_configuration": self.circulation.value,
            "circulation_configuration_required": self.circulation_configuration_required,
        }

    @property
    def attributes(self) -> dict[str, Any]:
        return {
            "source": "observed_states_and_configured_watts",
            "estimated": True,
            "observed_seconds": round(self._committed_record["known_seconds"], 1),
            "unobserved_runtime_seconds": round(self._committed_record["unknown_seconds"], 1),
            "storage_error": self.storage_error,
            "power_profile_w": self.profile,
            **self.configuration_attributes,
        }
