"""Optional model persistence and HA observations; never issues spa commands."""

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ._core.prediction import HeatingModel, SegmentCollector
from ._core.protocol.messages import HeatState, TemperatureUnit
from ._core.transport.connection import ConnectionState, Snapshot
from .const import CONF_FALLBACK, CONF_OUTDOOR, DOMAIN

if TYPE_CHECKING:
    from .coordinator import SpaCoordinator

_LOGGER = logging.getLogger(__name__)


def model_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    return Store(hass, 1, f"{DOMAIN}.prediction.{entry_id}", private=True, atomic_writes=True)


class PredictionController:
    def __init__(self, coordinator: SpaCoordinator) -> None:
        self.coordinator = coordinator
        self.outdoor_entity: str | None = None
        self.model = HeatingModel()
        self.collector = SegmentCollector()
        self.storage_failed = False
        self._dirty = False
        self._task: asyncio.Task[None] | None = None
        self._save_event = asyncio.Event()
        self._save_lock = asyncio.Lock()
        self._forecast_at = 0.0
        self._forecast_key: tuple[object, ...] = ()
        self._observation: tuple[int, int] | None = None
        self._ready_epoch: int | None = None
        self.values: dict[str, float | int | datetime | None] = {}
        self.configure()

    def configure(self) -> None:
        options = self.coordinator.entry.options
        entity = options.get(CONF_OUTDOOR) or None
        fallback = options.get(CONF_FALLBACK, 2.0)
        if entity != self.outdoor_entity:
            self.outdoor_entity = entity
            self.model = HeatingModel(outdoor=entity is not None, fallback=fallback)
            self.collector = SegmentCollector(outdoor=entity is not None)
            self._mark_dirty()
        self.model.fallback = fallback
        self._forecast_key = ()

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._save_event.set()

    @property
    def binding(self) -> dict[str, Any]:
        return {
            "connection": self.coordinator.connection_data,
            "outdoor_entity": self.outdoor_entity,
        }

    def _store(self) -> Store[dict[str, Any]]:
        return model_store(self.coordinator.hass, self.coordinator.entry.entry_id)

    async def async_load(self) -> None:
        try:
            record = await self._store().async_load()
            if record is None:
                return
            if not isinstance(record, dict) or set(record) != {"binding", "model"}:
                raise ValueError("Invalid prediction storage")
            if record["binding"] != self.binding:
                return  # A different endpoint/outdoor feature cannot reuse coefficients.
            self.model = HeatingModel.from_record(
                record["model"],
                outdoor=self.outdoor_entity is not None,
                fallback=self.model.fallback,
            )
            self._dirty = False
        except Exception:
            self.storage_failed = True
            _LOGGER.warning("Prediction storage is invalid; controls remain independent")

    def _outdoor(self, now: datetime) -> float | None:
        if self.outdoor_entity is None:
            return None
        state = self.coordinator.hass.states.get(self.outdoor_entity)
        if state is None or not 0 <= (now - state.last_reported).total_seconds() <= 900:
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        unit = state.attributes.get("unit_of_measurement")
        if unit == "°F":
            value = (value - 32) / 1.8
        elif unit != "°C":
            return None
        return value if -60 <= value <= 60 else None

    def observe(self, snapshot: Snapshot) -> None:
        now = dt_util.utcnow()
        status = snapshot.observed_status
        if snapshot.available:
            self._ready_epoch = snapshot.epoch
        refresh = (
            snapshot.state == ConnectionState.SYNCHRONIZING
            and self._ready_epoch == snapshot.epoch
            and not snapshot.health.ready_missing
        )
        # Routine metadata refresh does not interrupt healthy thermal observations.
        # Initial sync, a new epoch or missing bus traffic still cannot train.
        healthy = (snapshot.available or refresh) and status is not None
        water = status.current_temperature if status else None
        target = status.target_temperature if status else None
        if status and status.unit == TemperatureUnit.FAHRENHEIT:
            water = (water - 32) / 1.8 if water is not None else None
            target = (target - 32) / 1.8 if target is not None else None
        air = self._outdoor(now)
        healthy &= self.outdoor_entity is None or air is not None
        heating = status is not None and status.heat_state == HeatState.HEATING
        observation = (snapshot.epoch, snapshot.status_sequence)
        if not healthy:
            self.collector.reset()
        elif observation != self._observation:
            if self._observation is not None and self._observation[0] != snapshot.epoch:
                self.collector.reset()
            age = max(0, self.coordinator.hass.loop.time() - (snapshot.health.last_status or 0))
            segment = self.collector.observe(
                at=now.timestamp() - age, water=water, outdoor=air, heating=heating, healthy=healthy
            )
            if segment is not None:
                try:
                    self.model.update(segment)
                except ValueError:
                    self.collector.reset()  # Wall clock moved backwards past stored model time.
                else:
                    self._mark_dirty()
        self._observation = observation
        key = (healthy, water, target, air, heating, self.model.samples, self.model.fallback)
        if key == self._forecast_key and now.timestamp() - self._forecast_at < 30:
            return
        self._forecast_key, self._forecast_at = key, now.timestamp()
        rate = eta = None
        if (
            healthy
            and water is not None
            and target is not None
            and 0 <= water <= 45
            and 0 <= target <= 45
        ):
            rate = self.model.rate(water, air)
            eta = self.model.eta(water, target, air)
        ready = now + timedelta(minutes=eta) if eta is not None and (heating or eta == 0) else None
        self.values = {
            "heating_rate": round(rate, 3) if rate is not None else None,
            "heating_eta": round(eta, 1) if eta is not None else None,
            "ready_at": ready,
            "prediction_mae": round(self.model.mae, 1) if self.model.mae is not None else None,
            "prediction_samples": self.model.samples,
        }

    @property
    def attributes(self) -> dict[str, Any]:
        return {
            "prediction_quality": self.model.quality,
            "model_feature": "water_air_delta" if self.outdoor_entity else "water_temperature",
            "assumption": "continuous_heating",
            "error_scope": "pre_update_heating_segments",
            "median_absolute_error_minutes": self.model.median_error,
            "storage_error": self.storage_failed,
            "model_last_update": datetime.fromtimestamp(self.model.last_update, UTC).isoformat()
            if self.model.last_update is not None
            else None,
        }

    async def async_save(self) -> None:
        async with self._save_lock:
            if not self._dirty or self.storage_failed:
                return
            record = {"binding": self.binding, "model": self.model.to_record()}
            self._dirty = False
            try:
                await self._store().async_save(record)
                # HA queues saves received during stopping for its final-write event.
                # Do not confuse that documented deferral with a failed disk write.
                if self.coordinator.hass.state is not CoreState.stopping:
                    if await self._store().async_load() != record:
                        raise ValueError("Prediction write not verified")
            except asyncio.CancelledError:
                self._dirty = True  # Unload must retry an interrupted save.
                raise
            except Exception:
                self.storage_failed = True
                _LOGGER.warning("Prediction persistence failed; physical controls are unaffected")

    def start(self) -> None:
        self._task = self.coordinator.entry.async_create_background_task(
            self.coordinator.hass, self._run(), "balboa-prediction-save"
        )

    async def _run(self) -> None:
        while True:
            await self._save_event.wait()
            self._save_event.clear()
            await self.async_save()

    async def async_close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self.async_save()
