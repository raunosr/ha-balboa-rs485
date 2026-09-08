"""Low and High are independent spa targets, not a clamped shared setpoint."""

from balboa_rs485.command.engine import Stage
from balboa_rs485.state.model import Control

from .test_session_runner import lab


async def test_switching_profiles_preserves_each_targets_temperature():
    async with lab() as (simulator, runtime):

        async def command(control, value):
            intent = runtime.request(control, value)
            assert (await runtime.wait_for_intent(intent.id, timeout=2)).stage == Stage.VERIFIED

        await command(Control.TARGET, 39.0)
        await command(Control.HIGH_RANGE, False)
        await command(Control.TARGET, 26.0)
        await command(Control.HIGH_RANGE, True)
        assert runtime.state.target_temperature == 39.0
        await command(Control.HIGH_RANGE, False)
        assert runtime.state.target_temperature == 26.0
        assert simulator.physical_commands == 5
