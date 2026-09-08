"""Durable session decisions over real TCP, with only clock/storage boundaries replaced."""

import asyncio
from contextlib import asynccontextmanager

import pytest

from balboa_rs485.command.engine import CommandEngine
from balboa_rs485.protocol.messages import TemperatureUnit
from balboa_rs485.runtime import SpaRuntime
from balboa_rs485.session import Session, SessionPhase
from balboa_rs485.session_runner import SessionRunner
from balboa_rs485.state.model import Control
from balboa_rs485.transport.policy import Mode
from tools.simulator.server import Simulator

from .test_connection import FAST


@asynccontextmanager
async def lab(*, scenario="normal"):
    async with Simulator(port=0, interval=0.03, control_lab=True, scenario=scenario) as simulator:
        async with SpaRuntime(
            "127.0.0.1",
            simulator.port,
            mode=Mode.CLASSIC_RS485,
            timing=FAST,
            engine=CommandEngine(
                confirmation_guard=0.02, confirmation_timeout=0.12, resync_settle=0.06
            ),
        ) as runtime:
            await runtime.connection.wait_for(lambda _: runtime.metadata_complete, timeout=4)
            yield simulator, runtime


async def settle(runner, predicate):
    async with asyncio.timeout(4):
        while not predicate():
            await runner.async_tick()
            await asyncio.sleep(0.01)


async def save_noop(session):
    pass


async def test_manual_range_change_waits_for_pending_session_storage_then_refuses():
    async with lab() as (simulator, runtime):
        writing, release = asyncio.Event(), asyncio.Event()

        async def save(session):
            writing.set()
            await release.wait()

        called = []

        async def apply(control, desired):
            called.append((control, desired))

        runner = SessionRunner(runtime, save=save, enabled=lambda: True, now=lambda: 1000)
        start = asyncio.create_task(
            runner.async_start(end=4600, target=38, maintenance=27, unit=TemperatureUnit.CELSIUS)
        )
        await writing.wait()
        change = asyncio.create_task(
            runner.async_manual_change(Control.HIGH_RANGE, False, apply=apply)
        )
        await asyncio.sleep(0)
        assert not change.done()
        release.set()
        await start
        with pytest.raises(ValueError, match="session"):
            await change
        assert called == []
        assert simulator.physical_commands == 0
        runner.close()


async def test_manual_settings_validate_before_abandoning_and_serialize_the_physical_write():
    async with lab() as (simulator, runtime):
        saved, applied = [], []

        async def save(session):
            saved.append(session)

        async def apply(control, desired):
            applied.append((saved[-1], control, desired))
            intent = runtime.request(control, desired)
            await runtime.wait_for_intent(intent.id, timeout=2)

        enabled = [True]
        runner = SessionRunner(runtime, save=save, enabled=lambda: enabled[0], now=lambda: 1000)
        await runner.async_start(end=4600, target=38, maintenance=27, unit=TemperatureUnit.CELSIUS)
        with pytest.raises(ValueError):
            await runner.async_manual_change(Control.TARGET, 33.3, apply=apply)
        assert runner.session is not None
        with pytest.raises(ValueError, match="session-related"):
            await runner.async_manual_change(Control.PUMP1, False, apply=apply)
        enabled[0] = False
        with pytest.raises(ValueError, match="disabled"):
            await runner.async_manual_change(Control.TARGET, 37, apply=apply)
        assert runner.session is not None
        enabled[0] = True
        await runner.async_manual_change(Control.TARGET, 37, apply=apply)
        assert applied == [(None, Control.TARGET, 37)]
        assert runner.session is None
        assert simulator.target_temperature == 37
        runner.close()


async def test_session_start_waits_for_manual_range_write_and_validates_the_new_range():
    async with lab() as (simulator, runtime):
        sending, release = asyncio.Event(), asyncio.Event()

        async def apply(control, desired):
            sending.set()
            await release.wait()
            intent = runtime.request(control, desired)
            await runtime.wait_for_intent(intent.id, timeout=2)

        runner = SessionRunner(runtime, save=save_noop, enabled=lambda: True, now=lambda: 1000)
        change = asyncio.create_task(
            runner.async_manual_change(Control.HIGH_RANGE, False, apply=apply)
        )
        await sending.wait()
        start = asyncio.create_task(
            runner.async_start(end=4600, target=38, maintenance=27, unit=TemperatureUnit.CELSIUS)
        )
        await asyncio.sleep(0)
        assert not start.done()
        release.set()
        await change
        with pytest.raises(ValueError, match="Unsupported"):
            await start
        assert runner.session is None
        assert simulator.target_temperature == 27
        assert simulator.physical_commands == 1
        runner.close()


async def test_interrupted_storage_blocks_ambiguous_session_intent_until_reload():
    async with lab() as (simulator, runtime):
        writing = asyncio.Event()

        async def save(session):
            writing.set()
            await asyncio.Event().wait()

        runner = SessionRunner(runtime, save=save, enabled=lambda: True, now=lambda: 1000)
        task = asyncio.create_task(
            runner.async_start(end=4600, target=37, maintenance=27, unit=TemperatureUnit.CELSIUS)
        )
        await writing.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert runner.storage_failed
        await runner.async_tick()
        assert simulator.physical_commands == 0
        runner.close()


async def test_expiry_seen_at_transmission_stays_latched_after_clock_moves_backward():
    async with lab() as (simulator, runtime):
        clock = [1000.0]
        runner = SessionRunner(runtime, save=save_noop, enabled=lambda: True, now=lambda: clock[0])
        await runner.async_start(end=1001, target=37, maintenance=27, unit=TemperatureUnit.CELSIUS)
        clock[0] = 1002
        await asyncio.sleep(0.1)
        clock[0] = 1000
        with pytest.raises(ValueError, match="ended"):
            await runner.async_adjust(seconds=1800)
        await settle(runner, lambda: runner.session is None)
        assert simulator.target_temperature == 27
        assert simulator.physical_commands == 1
        runner.close()


@pytest.mark.parametrize("disabled", [False, True])
async def test_restart_checks_expiry_before_heating_and_waits_for_controls(disabled):
    async with lab() as (simulator, runtime):
        enabled = [not disabled]
        session = Session(100, 900, 37, 27, TemperatureUnit.CELSIUS)
        runner = SessionRunner(
            runtime,
            save=save_noop,
            enabled=lambda: enabled[0],
            now=lambda: 1000,
            session=Session.from_record(session.to_record()),
        )
        await runner.async_tick()
        assert runner.session.phase == SessionPhase.RESTORING
        if disabled:
            await asyncio.sleep(0.1)
            assert simulator.physical_commands == 0
        enabled[0] = True
        await settle(runner, lambda: runner.session is None)
        assert simulator.target_temperature == 27
        assert simulator.physical_commands == 1
        runner.close()


async def test_delayed_storage_and_concurrent_start_cannot_send_expired_target():
    async with lab() as (simulator, runtime):
        clock = [1000.0]

        async def save(session):
            await asyncio.sleep(0)
            clock[0] = 4600

        runner = SessionRunner(runtime, save=save, enabled=lambda: True, now=lambda: clock[0])
        results = await asyncio.gather(
            *(
                runner.async_start(
                    end=4600, target=37, maintenance=27, unit=TemperatureUnit.CELSIUS
                )
                for _ in range(2)
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(result, ValueError) for result in results) == 1
        await settle(runner, lambda: runner.session is None)
        assert simulator.physical_commands == 1
        assert simulator.target_temperature == 27
        runner.close()


async def test_disabled_start_and_unit_change_fail_closed():
    async with lab() as (simulator, runtime):
        enabled = [False]
        runner = SessionRunner(
            runtime, save=save_noop, enabled=lambda: enabled[0], now=lambda: 1000
        )
        with pytest.raises(ValueError, match="disabled"):
            await runner.async_start(
                end=4600, target=37, maintenance=27, unit=TemperatureUnit.CELSIUS
            )
        # A saved Fahrenheit intent must never be interpreted as Celsius.
        runner = SessionRunner(
            runtime,
            save=save_noop,
            enabled=lambda: True,
            now=lambda: 1000,
            session=Session(100, 4600, 100, 80, TemperatureUnit.FAHRENHEIT),
        )
        await runner.async_tick()
        assert runner.blocked_reason == "unsupported_state"
        assert simulator.physical_commands == 0
        runner.close()


async def test_offline_expiry_restores_after_resynchronization_without_replaying_heating():
    async with lab(scenario="lost-status-after-command") as (simulator, runtime):
        clock = [1000.0]
        runner = SessionRunner(runtime, save=save_noop, enabled=lambda: True, now=lambda: clock[0])
        await runner.async_start(end=4600, target=37, maintenance=27, unit=TemperatureUnit.CELSIUS)
        await runtime.connection.wait_for(lambda _: runtime.engine.busy, timeout=2)
        clock[0] = 4600
        await runner.async_tick()
        assert runner.session.phase == SessionPhase.RESTORING
        await settle(runner, lambda: runner.session is None)
        assert simulator.physical_commands == 2
        assert simulator.target_temperature == 27
        runner.close()


async def test_expired_queued_target_is_never_sent_between_scheduler_ticks():
    async with lab() as (simulator, runtime):
        clock = [1000.0]
        runner = SessionRunner(runtime, save=save_noop, enabled=lambda: True, now=lambda: clock[0])
        await runner.async_start(end=1001, target=37, maintenance=27, unit=TemperatureUnit.CELSIUS)
        clock[0] = 1002
        # Deliberately no scheduler tick: the transport must refuse an expired goal.
        await asyncio.sleep(0.15)
        assert simulator.physical_commands == 0
        await settle(runner, lambda: runner.session is None)
        assert simulator.target_temperature == 27
        assert simulator.physical_commands == 1
        runner.close()


async def test_session_does_not_reassert_target_after_physical_panel_change():
    async with lab() as (simulator, runtime):
        runner = SessionRunner(runtime, save=save_noop, enabled=lambda: True, now=lambda: 1000)
        await runner.async_start(end=4600, target=37, maintenance=27, unit=TemperatureUnit.CELSIUS)
        await settle(
            runner, lambda: runtime.state.target_temperature == 37 and not runtime.engine.busy
        )
        simulator.target_temperature = 36  # External physical panel boundary.
        await runtime.connection.wait_for(
            lambda _: runtime.state.target_temperature == 36, timeout=2
        )
        for _ in range(5):
            await runner.async_tick()
            await asyncio.sleep(0.03)
        assert simulator.physical_commands == 1
        assert runner.blocked_reason == "setpoint_changed"
        await runner.async_cancel()
        await settle(runner, lambda: runner.session is None)
        assert simulator.physical_commands == 2
        runner.close()


async def test_manual_abandonment_and_close_cannot_cancel_a_newer_manual_command():
    async with lab() as (simulator, runtime):
        runner = SessionRunner(runtime, save=save_noop, enabled=lambda: True, now=lambda: 1000)
        await runner.async_start(end=4600, target=37, maintenance=27, unit=TemperatureUnit.CELSIUS)
        await runner.async_abandon()
        assert runner.session is None
        manual = runtime.request(Control.TARGET, 36)
        runner.close()
        await runtime.wait_for_intent(manual.id)
        assert runtime.state.target_temperature == 36
        assert simulator.physical_commands == 1
        with pytest.raises(ValueError, match="closed"):
            await runner.async_start(
                end=4600, target=37, maintenance=27, unit=TemperatureUnit.CELSIUS
            )
        await runner.async_tick()


async def test_adjustments_persist_deadline_and_reduction_restores_while_disabled():
    async with lab() as (simulator, runtime):
        enabled = [True]
        runner = SessionRunner(
            runtime, save=save_noop, enabled=lambda: enabled[0], now=lambda: 1000
        )
        with pytest.raises(ValueError, match="No active"):
            await runner.async_adjust(seconds=1800)
        await runner.async_start(end=4600, target=37, maintenance=27, unit=TemperatureUnit.CELSIUS)
        await settle(
            runner, lambda: runtime.state.target_temperature == 37 and not runtime.engine.busy
        )
        await runner.async_adjust(seconds=1800)
        assert runner.session.end_time == 6400
        enabled[0] = False
        await runner.async_adjust(seconds=-6000)
        assert runner.session.phase == SessionPhase.RESTORING
        assert runner.blocked_reason == "controls_disabled"
        assert simulator.physical_commands == 1
        with pytest.raises(ValueError, match="ended"):
            await runner.async_adjust(seconds=1800)
        enabled[0] = True
        await settle(runner, lambda: runner.session is None)
        assert simulator.physical_commands == 2
        runner.close()


async def test_expiry_persists_intent_before_send_and_finishes_from_observed_maintenance():
    async with lab() as (simulator, runtime):
        clock = [1000.0]
        saved = []

        async def save(session):
            saved.append((session, simulator.physical_commands))

        runner = SessionRunner(runtime, save=save, enabled=lambda: True, now=lambda: clock[0])
        await runner.async_start(end=4600, target=37, maintenance=27, unit=TemperatureUnit.CELSIUS)
        assert saved[0][1] == 0
        await settle(
            runner, lambda: runtime.state.target_temperature == 37 and not runtime.engine.busy
        )
        clock[0] = 4600
        await runner.async_tick()
        assert saved[-1][0].phase == SessionPhase.RESTORING
        assert saved[-1][1] == 1
        await settle(runner, lambda: runner.session is None)
        assert runtime.state.target_temperature == 27
        assert saved[-1] == (None, 2)
        assert simulator.physical_commands == 2
        runner.close()


async def test_storage_failure_blocks_commands_and_later_mutations():
    async with lab() as (simulator, runtime):

        async def save(session):
            raise OSError("disk full")

        runner = SessionRunner(runtime, save=save, enabled=lambda: True, now=lambda: 1000)
        with pytest.raises(ValueError, match="storage"):
            await runner.async_start(
                end=4600, target=37, maintenance=27, unit=TemperatureUnit.CELSIUS
            )
        assert runner.session is None
        assert runner.blocked_reason == "storage_error"
        await runner.async_tick()
        with pytest.raises(ValueError, match="storage"):
            await runner.async_start(
                end=4600, target=37, maintenance=27, unit=TemperatureUnit.CELSIUS
            )
        assert simulator.physical_commands == 0
        runner.close()


async def test_cancel_during_unconfirmed_command_does_not_finish_from_old_state():
    async with lab(scenario="lost-status-after-command") as (simulator, runtime):
        saved = []

        async def save(session):
            saved.append(session)

        runner = SessionRunner(runtime, save=save, enabled=lambda: True, now=lambda: 1000)
        await runner.async_start(end=4600, target=37, maintenance=38, unit=TemperatureUnit.CELSIUS)
        await runtime.connection.wait_for(lambda _: runtime.engine.busy, timeout=2)
        assert runtime.state.target_temperature == 38  # Old observation, not confirmation.
        await runner.async_cancel()
        assert runner.session.phase == SessionPhase.RESTORING
        await settle(runner, lambda: runner.session is None)
        assert runtime.state.target_temperature == 38
        assert simulator.physical_commands == 2
        assert runtime.connection.snapshot.epoch >= 2
        with pytest.raises(ValueError, match="No active"):
            await runner.async_cancel()
        runner.close()
