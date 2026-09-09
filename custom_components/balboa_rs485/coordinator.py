"""Own one independent runtime and push observations into Home Assistant."""

import asyncio
import logging
from contextlib import suppress

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ._core.command.engine import TERMINAL, Stage
from ._core.runtime import SpaRuntime
from ._core.state.model import Control, Value
from ._core.transport.connection import Snapshot
from ._core.transport.policy import Mode
from .const import CONF_CONTROLS, CONF_DIRECT_RISK, CONF_MODE, DOMAIN
from .prediction import PredictionController
from .sessions import SessionController

_LOGGER = logging.getLogger(__name__)
_TERMINAL = TERMINAL
PUMP_COMMAND_TIMEOUT = 30.0
PUMP_COALESCE_WINDOW = 0.15  # Coalesce unsent UI goals, never a bus-ownership delay.


class SpaCoordinator(DataUpdateCoordinator[Snapshot]):
    """A push adapter; entities never open sockets or parse protocol bytes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=entry)
        self.entry = entry
        self.connection_data = dict(entry.data)
        self.runtime = SpaRuntime(
            entry.data[CONF_HOST],
            entry.data[CONF_PORT],
            mode=Mode(entry.data[CONF_MODE]),
            allow_unarbitrated_writes=entry.data.get(CONF_DIRECT_RISK) is True,
        )
        self._watcher: asyncio.Task[None] | None = None
        self._opened = False
        self._close_lock = asyncio.Lock()
        self._pending: dict[Control, int] = {}
        self._waiters: dict[int, int] = {}
        self._deadlines: dict[int, float] = {}
        self.sessions = SessionController(self)
        self.prediction = PredictionController(self)

    @property
    def controls_enabled(self) -> bool:
        return self.entry.options.get(CONF_CONTROLS, False) is True

    @callback
    def async_options_updated(self) -> None:
        self.prediction.configure()
        self.prediction.observe(self.runtime.connection.snapshot)
        if not self.controls_enabled:
            self._cancel_pending()
            self.sessions.runner.pause()
        self.async_set_updated_data(self.runtime.connection.snapshot)

    @callback
    def _cancel_pending(self) -> None:
        for control, identifier in tuple(self._pending.items()):
            intent = self.runtime.engine.intent(identifier)
            if intent is not None and intent.stage not in _TERMINAL:
                # Keep the in-flight transaction's ambiguity/confirmation guard;
                # cancel only its remaining goal, not physical observations.
                self.runtime.engine.cancel(control, now=self.hass.loop.time())

    async def async_command(self, control: Control, desired: Value) -> None:
        if not self._opened:
            raise HomeAssistantError("Spa integration is stopped or stopping")
        if not self.controls_enabled:
            raise HomeAssistantError("Physical controls are disabled in integration options")
        loop = asyncio.get_running_loop()
        pump = control.value.startswith("pump")
        identifier = self._pending.get(control)
        intent = self.runtime.engine.intent(identifier) if identifier is not None else None
        # Native pump aliases share an active goal, including during recovery.
        # Do not reset its action budget, deadline or in-flight confirmation.
        # Other actions (especially acknowledgements with validity guards) retain
        # their existing one-request semantics. A different target still wins.
        if not (
            pump
            and intent is not None
            and intent.desired == desired
            and intent.stage not in _TERMINAL
        ):
            try:
                intent = self.runtime.request(
                    control,
                    desired,
                    deadline=loop.time() + (PUMP_COMMAND_TIMEOUT if pump else 20),
                    defer_for=PUMP_COALESCE_WINDOW if pump else 0,
                    replace_pending=pump,
                )
            except ValueError as err:
                raise HomeAssistantError(str(err)) from err
        else:
            assert intent is not None
            self.runtime.engine.joined(intent.id, now=loop.time())
        assert intent is not None
        assert intent.deadline is not None
        deadline = self._deadlines.setdefault(intent.id, intent.deadline)
        self._waiters[intent.id] = self._waiters.get(intent.id, 0) + 1
        self._pending[control] = intent.id
        self.async_set_updated_data(self.runtime.connection.snapshot)
        try:
            result = await self.runtime.wait_for_intent(
                intent.id, timeout=max(0, deadline - loop.time())
            )
        except (TimeoutError, asyncio.CancelledError) as err:
            # One disconnected UI caller must not cancel another caller's same
            # goal. Last-caller cancellation and the original deadline still do.
            if self._pending.get(control) == intent.id and (
                isinstance(err, TimeoutError) or self._waiters[intent.id] == 1
            ):
                self.runtime.engine.cancel(control, now=loop.time())
            if isinstance(err, asyncio.CancelledError):
                raise
            raise HomeAssistantError("Command was not verified before the deadline") from err
        finally:
            self._waiters[intent.id] -= 1
            if self._waiters[intent.id] == 0:
                del self._waiters[intent.id]
                del self._deadlines[intent.id]
                if self._pending.get(control) == intent.id:
                    del self._pending[control]
            self.async_set_updated_data(self.runtime.connection.snapshot)
        if result.stage == Stage.SUPERSEDED:
            # Not a successful device write or a device fault. HA may show this
            # cancellation notice, but never report the old goal as VERIFIED.
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="command_replaced"
            )
        if result.stage != Stage.VERIFIED:
            raise HomeAssistantError(f"Command {result.stage.value}: {result.reason or ''}")

    async def async_open(self) -> None:
        await self.sessions.async_load()
        await self.prediction.async_load()
        await self.runtime.__aenter__()
        self._opened = True
        try:
            await self.runtime.connection.wait_for(lambda snapshot: snapshot.status is not None)
        except TimeoutError as err:
            if self.connection_data[CONF_MODE] != Mode.CHANNEL_RS485.value:
                raise ConfigEntryNotReady("No valid Balboa status received") from err
            # Automatic ConfigEntry retries would create a new runtime and reset
            # its finite channel-allocation budget. Keep the current owner and
            # diagnostics alive, with every physical entity unavailable.
            _LOGGER.warning(
                "No Balboa status; retaining channel runtime to preserve allocation limits"
            )
        self.prediction.observe(self.runtime.connection.snapshot)
        self.async_set_updated_data(self.runtime.connection.snapshot)
        self._watcher = self.entry.async_create_background_task(
            self.hass, self._watch(), "balboa-observations"
        )
        self.sessions.start()
        self.prediction.start()

    async def async_filter_change(
        self,
        index: int,
        *,
        start: int | None = None,
        end: int | None = None,
        enabled: bool | None = None,
    ) -> None:
        try:
            await self.runtime.async_update_filter(
                index,
                start=start,
                end=end,
                enabled=enabled,
                valid=lambda: self.controls_enabled and self._opened,
            )
        except (ValueError, TimeoutError) as err:
            raise HomeAssistantError(str(err) or "Filter change was not verified") from err
        finally:
            self.async_set_updated_data(self.runtime.connection.snapshot)

    def _key(self, snapshot: Snapshot) -> tuple[object, ...]:
        return (
            snapshot.state,
            snapshot.epoch,
            snapshot.status_sequence,
            snapshot.health.status_stale,
            snapshot.channel_failure,
            snapshot.channel_assignment,
            snapshot.configuration_revision,
            self.runtime.state,
            self.runtime.engine.revision,
        )

    async def _watch(self) -> None:
        while True:
            key = self._key(self.runtime.connection.snapshot)

            def changed(current: Snapshot, previous: tuple[object, ...] = key) -> bool:
                return self._key(current) != previous

            try:
                snapshot = await self.runtime.connection.wait_for(changed, timeout=30)
            except TimeoutError:
                snapshot = self.runtime.connection.snapshot
            self.prediction.observe(snapshot)
            self._update_device_information(snapshot)
            self.async_set_updated_data(snapshot)

    @callback
    def _update_device_information(self, snapshot: Snapshot) -> None:
        if snapshot.configuration is None:
            return
        info = snapshot.configuration.information
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, self.entry.entry_id)})
        version = ".".join(str(part) for part in info.software_version)
        if device is not None and (device.model != info.model or device.sw_version != version):
            registry.async_update_device(device.id, model=info.model, sw_version=version)

    async def async_close(self) -> None:
        # Stop/unload can overlap. No background-task exception or prediction
        # persistence failure may prevent closing the one owned spa connection.
        async with self._close_lock:
            opened = self._opened
            self._opened = False
            self._cancel_pending()
            self.sessions.runner.close()
            watcher, self._watcher = self._watcher, None
            try:
                if watcher is not None:
                    watcher.cancel()
                    with suppress(asyncio.CancelledError):
                        await watcher
            finally:
                try:
                    await self.sessions.async_close()
                finally:
                    try:
                        if opened:
                            await self.runtime.__aexit__(None, None, None)
                    finally:
                        self.async_set_updated_data(self.runtime.connection.snapshot)
                        # Persistence can wait only after the bus is relinquished.
                        await self.prediction.async_close()


type BalboaConfigEntry = ConfigEntry[SpaCoordinator]
