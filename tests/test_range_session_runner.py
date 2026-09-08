"""Real TCP bathing-session acceptance with independent Low/High spa targets."""

import asyncio

import pytest

from balboa_rs485.command.engine import Stage
from balboa_rs485.range_session import RangeSession, RangeStep
from balboa_rs485.session_runner import SessionRunner
from balboa_rs485.state.model import Control

from .test_range_session import observed
from .test_session_runner import lab, save_noop, settle


@pytest.mark.parametrize("original_high", [35.0, 36.5, 38.0])
@pytest.mark.parametrize("original_range", [False, True])
async def test_bathing_session_applies_minimum_without_lowering_high_then_restores(
    original_high, original_range
):
    async with lab() as (simulator, runtime):
        simulator.high_range = False
        simulator.target_temperature = 26.0
        simulator.high_range = True
        simulator.target_temperature = original_high
        simulator.high_range = original_range
        simulator.heat_mode = 1
        await runtime.connection.wait_for(
            lambda _: (
                runtime.state.status.high_range == original_range
                and runtime.state.target_temperature == (original_high if original_range else 26)
                and runtime.state.status.heat_mode == 1
            ),
            timeout=2,
        )
        saved, clock = [], [1000.0]

        async def save(session):
            saved.append(None if session is None else RangeSession.from_record(session.to_record()))

        runner = SessionRunner(runtime, save=save, enabled=lambda: True, now=lambda: clock[0])
        await runner.async_start_bathing(end=4600, minimum_c=36.5)
        await settle(runner, lambda: runner.session.step == RangeStep.ACTIVE)
        assert simulator.high_range
        assert simulator.target_temperature == max(36.5, original_high)
        assert simulator.heat_mode == 0
        assert any(s is not None and s.original_high == original_high for s in saved)
        clock[0] = 4600
        await settle(runner, lambda: runner.session is None)
        assert simulator.high_range == original_range
        assert simulator.heat_mode == 1
        assert simulator.target_temperature == (original_high if original_range else 26.0)
        target_writes = [r for r in simulator.physical_records if r.frame.message_type == 32]
        assert len(target_writes) == (2 if original_high < 36.5 else 0)
        if not original_range:
            intent = runtime.request(Control.HIGH_RANGE, True)
            assert (await runtime.wait_for_intent(intent.id, timeout=2)).stage == Stage.VERIFIED
            assert runtime.state.target_temperature == original_high
        runner.close()


@pytest.mark.parametrize(
    "fail_step", [RangeStep.ACTIVATE_HIGH, RangeStep.SET_TARGET, RangeStep.SET_MODE]
)
async def test_failed_checkpoint_never_allows_next_write_and_last_record_can_restore(fail_step):
    async with lab() as (simulator, runtime):
        simulator.target_temperature = 35
        simulator.high_range = False
        simulator.heat_mode = 1
        await runtime.connection.wait_for(
            lambda _: not runtime.state.status.high_range and runtime.state.status.heat_mode == 1,
            timeout=2,
        )
        saved, clock = [], [1000]

        async def save(session):
            if session is not None and session.step == fail_step:
                raise OSError("full disk")
            saved.append(session)

        runner = SessionRunner(runtime, save=save, enabled=lambda: True, now=lambda: clock[0])
        with pytest.raises(ValueError, match="storage"):
            await runner.async_start_bathing(end=4600)
            await settle(runner, lambda: runner.storage_failed)
        count = simulator.physical_commands
        await runner.async_tick()
        await asyncio.sleep(0.1)
        assert simulator.physical_commands == count
        assert (
            count
            == {RangeStep.ACTIVATE_HIGH: 0, RangeStep.SET_TARGET: 1, RangeStep.SET_MODE: 2}[
                fail_step
            ]
        )
        runner.close()
        if saved:
            resumed = SessionRunner(
                runtime,
                save=save_noop,
                enabled=lambda: True,
                now=lambda: 5000,
                session=RangeSession.from_record(saved[-1].to_record()),
            )
            await settle(resumed, lambda: resumed.session is None)
            assert simulator.high_range is False
            assert simulator.heat_mode == 1
            assert not any(
                r.frame.message_type == 32 and r.frame.payload[0] == 73
                for r in list(simulator.physical_records)[count:]
            )
            resumed.close()


async def test_manual_high_edit_preserves_user_value_but_restores_owned_range_and_mode():
    async with lab() as (simulator, runtime):
        simulator.target_temperature = 35
        simulator.high_range = False
        simulator.heat_mode = 1
        await runtime.connection.wait_for(
            lambda _: not runtime.state.status.high_range and runtime.state.status.heat_mode == 1,
            timeout=2,
        )
        runner = SessionRunner(runtime, save=save_noop, enabled=lambda: True, now=lambda: 1000)
        await runner.async_start_bathing(end=4600)
        await settle(runner, lambda: runner.session.step == RangeStep.ACTIVE)

        async def apply(control, desired):
            assert not runner.session.target_owned
            intent = runtime.request(control, desired)
            assert (await runtime.wait_for_intent(intent.id, timeout=2)).stage == Stage.VERIFIED

        await runner.async_manual_change(Control.TARGET, 37, apply=apply)
        await settle(runner, lambda: runner.session is None)
        assert not simulator.high_range
        assert simulator.heat_mode == 1
        intent = runtime.request(Control.HIGH_RANGE, True)
        await runtime.wait_for_intent(intent.id, timeout=2)
        assert simulator.target_temperature == 37
        runner.close()


@pytest.mark.parametrize(
    "field,value", [("target_temperature", 39), ("high_range", False), ("heat_mode", 1)]
)
async def test_external_edit_stops_session_and_explicit_abandon_sends_nothing(field, value):
    async with lab() as (simulator, runtime):
        runner = SessionRunner(runtime, save=save_noop, enabled=lambda: True, now=lambda: 1000)
        await runner.async_start_bathing(end=4600)
        await settle(runner, lambda: runner.session.step == RangeStep.ACTIVE)
        count = simulator.physical_commands
        setattr(simulator, field, value)
        await settle(runner, lambda: runner.blocked_reason == "external_change")
        assert simulator.physical_commands == count
        await runner.async_abandon()
        assert runner.session is None
        assert simulator.physical_commands == count
        runner.close()


def crash_checkpoints():
    first = RangeSession.start(now=1000, end=4600, minimum_c=36.5, state=observed())
    target = first.reconcile(now=1001, state=observed(high=True, target=35))
    mode = target.reconcile(now=1002, state=observed(high=True, target=36.5))
    active = mode.reconcile(now=1003, state=observed(high=True, target=36.5, mode=0))
    restoring = active.cancel()
    restore_range = restoring.reconcile(now=4700, state=observed(high=True, target=35, mode=0))
    restore_mode = restore_range.reconcile(now=4700, state=observed(mode=0))
    return [
        (first, False, 35, 1),
        (first, True, 35, 1),  # Range changed, High not captured yet.
        (target, True, 35, 1),
        (target, True, 36.5, 1),  # Target sent before confirmation/save.
        (mode, True, 36.5, 0),  # Ready sent before active checkpoint.
        (active, True, 36.5, 0),
        (restoring, True, 35, 0),
        (restore_range, False, 35, 0),
        (restore_mode, False, 35, 1),
    ]


@pytest.mark.parametrize("exit_control", [Control.HOLD, Control.NORMAL_OPERATION])
async def test_session_rejects_hold_entry_but_explicit_exit_unblocks_restoration(exit_control):
    async with lab() as (simulator, runtime):
        runner = SessionRunner(runtime, save=save_noop, enabled=lambda: True, now=lambda: 1000)
        await runner.async_start_bathing(end=4600)
        await settle(runner, lambda: runner.session.step == RangeStep.ACTIVE)

        async def apply(control, desired):
            intent = runtime.request(control, desired)
            assert (await runtime.wait_for_intent(intent.id, timeout=2)).stage == Stage.VERIFIED

        before = simulator.physical_commands
        with pytest.raises(ValueError, match="End the heating session"):
            await runner.async_manual_change(Control.HOLD, True, apply=apply)
        assert simulator.physical_commands == before
        simulator.hold = True
        await runtime.connection.wait_for(lambda _: runtime.state.hold, timeout=2)
        await runner.async_cancel()
        await runner.async_tick()
        assert runner.session is not None
        await runner.async_manual_change(
            exit_control, exit_control == Control.NORMAL_OPERATION, apply=apply
        )
        assert not simulator.hold
        await settle(runner, lambda: runner.session is None)
        runner.close()


@pytest.mark.parametrize("checkpoint,high,high_target,heat_mode", crash_checkpoints())
async def test_expired_restart_at_each_write_boundary_only_restores(
    checkpoint, high, high_target, heat_mode
):
    async with lab() as (simulator, runtime):
        simulator.high_range = False
        simulator.target_temperature = 26
        simulator.high_range = True
        simulator.target_temperature = high_target
        simulator.high_range = high
        simulator.heat_mode = heat_mode
        await runtime.connection.wait_for(
            lambda _: (
                runtime.state.status.high_range == high
                and runtime.state.target_temperature == (high_target if high else 26)
                and runtime.state.status.heat_mode == heat_mode
            ),
            timeout=2,
        )
        saved, enabled = [], [False]

        async def save(session):
            saved.append(session)

        runner = SessionRunner(
            runtime,
            save=save,
            enabled=lambda: enabled[0],
            now=lambda: 5000,
            session=RangeSession.from_record(checkpoint.to_record()),
        )
        await runner.async_tick()
        assert simulator.physical_commands == 0
        enabled[0] = True
        await settle(runner, lambda: runner.session is None)
        assert simulator.high_range is False
        assert simulator.target_temperature == 26
        assert simulator.heat_mode == 1
        targets = [
            r.frame.payload[0] for r in simulator.physical_records if r.frame.message_type == 32
        ]
        assert all(raw == 70 for raw in targets)  # 35 C restore, never 36.5 C heating.
        runner.close()
