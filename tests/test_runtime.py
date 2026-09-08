"""Real TCP command transactions against shared synthetic physical state."""

import pytest

from balboa_rs485.command.engine import CommandEngine, Stage
from balboa_rs485.runtime import SpaRuntime
from balboa_rs485.state.model import Control, PumpState
from balboa_rs485.transport.policy import Mode
from tools.simulator.server import Simulator

from .test_connection import FAST


@pytest.mark.parametrize("channel_lab", [False, True])
async def test_forced_low_pump_confirms_final_goal_without_reconnect(channel_lab):
    async with Simulator(
        port=0, interval=0.03, control_lab=True, channel_lab=channel_lab
    ) as simulator:
        simulator.pump1_forced_low = True
        simulator.pump_states[0] = 2
        async with SpaRuntime(
            "127.0.0.1",
            simulator.port,
            mode=Mode.CHANNEL_RS485 if channel_lab else Mode.CLASSIC_RS485,
            timing=FAST,
            engine=CommandEngine(confirmation_guard=0.02, confirmation_timeout=0.12),
        ) as runtime:
            await runtime.connection.wait_for(lambda s: s.available, timeout=3)
            intent = runtime.request(Control.PUMP1, PumpState.LOW)
            assert (await runtime.wait_for_intent(intent.id, timeout=2)).stage == Stage.VERIFIED
            assert simulator.physical_commands == 1
            assert simulator.stats.connections == 1
            assert runtime.connection.snapshot.recoveries == 0
            assert runtime.engine.history[-1].resulting_value == PumpState.LOW


@pytest.mark.parametrize("desired,commands", [(PumpState.LOW, 1), (PumpState.HIGH, 2)])
@pytest.mark.parametrize("channel_lab", [False, True])
async def test_tcp_lost_confirmation_resyncs_before_any_further_toggle(
    desired, commands, channel_lab
):
    engine = CommandEngine(confirmation_guard=0.02, confirmation_timeout=0.12, resync_settle=0.06)
    async with Simulator(
        port=0,
        interval=0.03,
        control_lab=True,
        channel_lab=channel_lab,
        scenario="lost-status-after-command",
    ) as simulator:
        async with SpaRuntime(
            "127.0.0.1",
            simulator.port,
            mode=Mode.CHANNEL_RS485 if channel_lab else Mode.CLASSIC_RS485,
            timing=FAST,
            engine=engine,
        ) as runtime:
            await runtime.connection.wait_for(lambda s: s.available, timeout=2)
            intent = runtime.request(Control.PUMP1, desired)
            assert (await runtime.wait_for_intent(intent.id, timeout=4)).stage == Stage.VERIFIED
            assert simulator.physical_commands == commands
            assert simulator.pump_states[0] == (1 if desired == PumpState.LOW else 2)
            assert runtime.connection.snapshot.epoch == 2
            assert engine.history[0].result == Stage.FAILED
            assert engine.history[0].reason.startswith("Confirmation timeout")
            if commands == 2:
                assert engine.history[1].action.epoch == 2
                assert engine.history[1].starting_value == PumpState.LOW


async def test_tcp_rapid_target_and_light_intents_send_only_final_values():
    engine = CommandEngine(confirmation_guard=0.02)
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        async with SpaRuntime(
            "127.0.0.1", simulator.port, mode=Mode.CLASSIC_RS485, timing=FAST, engine=engine
        ) as runtime:
            await runtime.connection.wait_for(
                lambda _: runtime.state is not None and runtime.state.setup is not None, timeout=4
            )
            targets = [runtime.request(Control.TARGET, value) for value in (35, 36, 37, 39)]
            lights = [runtime.request(Control.LIGHT1, value) for value in (True, False, True)]
            assert runtime.state.target_temperature == 38
            assert (
                await runtime.wait_for_intent(targets[-1].id, timeout=4)
            ).stage == Stage.VERIFIED
            assert (await runtime.wait_for_intent(lights[-1].id, timeout=4)).stage == Stage.VERIFIED
            assert simulator.physical_commands == 2
            assert runtime.state.target_temperature == 39
            assert runtime.state.value(Control.LIGHT1) is True
            assert runtime.state.filters is not None and runtime.state.fault is not None


async def test_single_speed_raw_two_turns_on_and_off_with_one_toggle_each():
    async with Simulator(
        port=0, interval=0.03, control_lab=True, scenario="single-speed-pump"
    ) as simulator:
        async with SpaRuntime(
            "127.0.0.1",
            simulator.port,
            mode=Mode.CLASSIC_RS485,
            timing=FAST,
            engine=CommandEngine(confirmation_guard=0.02),
        ) as runtime:
            await runtime.connection.wait_for(lambda s: s.available, timeout=2)
            on = runtime.request(Control.PUMP1, PumpState.ON)
            assert (await runtime.wait_for_intent(on.id, timeout=4)).stage == Stage.VERIFIED
            assert simulator.pump_states[0] == 2 and simulator.physical_commands == 1
            off = runtime.request(Control.PUMP1, PumpState.OFF)
            assert (await runtime.wait_for_intent(off.id, timeout=4)).stage == Stage.VERIFIED
            assert simulator.pump_states[0] == 0 and simulator.physical_commands == 2


async def test_disconnect_after_toggle_cancels_transaction_and_recomputes_from_physical_state():
    async with Simulator(
        port=0, interval=0.03, control_lab=True, scenario="reset-after-command"
    ) as simulator:
        async with SpaRuntime(
            "127.0.0.1",
            simulator.port,
            mode=Mode.CLASSIC_RS485,
            timing=FAST,
            engine=CommandEngine(confirmation_guard=0.02, resync_settle=0.06),
        ) as runtime:
            await runtime.connection.wait_for(lambda s: s.available, timeout=2)
            intent = runtime.request(Control.PUMP1, PumpState.HIGH)
            result = await runtime.wait_for_intent(intent.id, timeout=4)
            assert result.stage == Stage.VERIFIED
            assert simulator.physical_commands == 2
            assert runtime.engine.history[0].result == Stage.CANCELLED
            assert runtime.engine.history[1].action.epoch == 2
            assert runtime.engine.history[1].starting_value == PumpState.LOW


async def test_supported_accessory_mode_and_range_intents_are_observation_verified():
    from balboa_rs485.protocol.messages import HeatMode

    async with Simulator(
        port=0, interval=0.03, control_lab=True, scenario="accessories"
    ) as simulator:
        async with SpaRuntime(
            "127.0.0.1",
            simulator.port,
            mode=Mode.CLASSIC_RS485,
            timing=FAST,
            engine=CommandEngine(confirmation_guard=0.02),
        ) as runtime:
            await runtime.connection.wait_for(lambda s: s.available, timeout=2)
            for control, desired in [
                (Control.BLOWER, 2),
                (Control.LIGHT2, True),
                (Control.AUX1, True),
                (Control.AUX2, True),
                (Control.MISTER, True),
                (Control.HEAT_MODE, HeatMode.REST),
                (Control.HIGH_RANGE, False),
            ]:
                intent = runtime.request(control, desired)
                assert (await runtime.wait_for_intent(intent.id, timeout=3)).stage == Stage.VERIFIED
                assert runtime.state.value(control) == desired
            assert simulator.physical_commands == 8


async def test_missing_optional_metadata_is_reported_and_does_not_invent_target_limits():
    async with Simulator(
        port=0, interval=0.03, control_lab=True, scenario="missing-metadata"
    ) as simulator:
        async with SpaRuntime(
            "127.0.0.1",
            simulator.port,
            mode=Mode.CLASSIC_RS485,
            timing=FAST,
            engine=CommandEngine(confirmation_guard=0.02),
        ) as runtime:
            await runtime.connection.wait_for(
                lambda s: s.available and runtime.metadata_complete, timeout=4
            )
            assert runtime.metadata_failures == ("SETUP", "FILTERS", "FAULT")
            assert runtime.state.setup is None and runtime.state.fault is None
            with pytest.raises(ValueError):
                runtime.request(Control.TARGET, 38)
            intent = runtime.request(Control.PUMP1, PumpState.LOW)
            assert (await runtime.wait_for_intent(intent.id, timeout=2)).stage == Stage.VERIFIED
            with pytest.raises(ValueError):
                await runtime.wait_for_intent(-1)


async def test_unsolicited_typed_fault_observation_updates_immutable_state():
    async with Simulator(
        port=0, interval=0.03, control_lab=True, scenario="metadata-change"
    ) as simulator:
        async with SpaRuntime(
            "127.0.0.1", simulator.port, mode=Mode.CLASSIC_RS485, timing=FAST
        ) as runtime:
            await runtime.connection.wait_for(
                lambda _: runtime.state is not None and runtime.state.fault is not None, timeout=2
            )
            old = runtime.state
            await runtime.connection.wait_for(lambda _: runtime.state.fault.code == 17, timeout=2)
            assert old.fault.code == 0
            assert runtime.state.fault.code == 17
