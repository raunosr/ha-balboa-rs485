"""One next physical step, recomputed from authoritative state and latest intent."""

from ..protocol.commands import (
    ToggleItem,
    set_clock,
    set_clock_format,
    set_temperature,
    set_temperature_unit,
    toggle,
)
from ..protocol.frames import Frame
from ..protocol.messages import HeatMode, TemperatureUnit
from ..protocol.settings import FilterSchedule
from ..state.model import Control, SpaState, Value


def plan(state: SpaState, control: Control, desired: Value) -> tuple[Frame, Value]:
    state.validate(control, desired)
    if control in (Control.NORMAL_OPERATION, Control.SOAK, Control.ACK_REMINDER):
        return toggle(ToggleItem[control.name]), True
    if control == Control.TEMPERATURE_UNIT:
        assert isinstance(desired, TemperatureUnit)
        return set_temperature_unit(desired), desired
    if control == Control.CLOCK_FORMAT:
        assert isinstance(desired, bool)
        return set_clock_format(desired), desired
    if control == Control.CLOCK_TIME:
        assert isinstance(desired, int)
        return set_clock(desired, state.status.clock_24h), desired
    if control == Control.FILTERS:
        assert isinstance(desired, FilterSchedule)
        return desired.frame(), desired
    if control == Control.TARGET:
        assert isinstance(desired, (int, float))
        return set_temperature(float(desired), state.status.unit), desired
    value = state.value(control)
    options = state.options(control)
    if control == Control.HEAT_MODE and value == HeatMode.READY_IN_REST:
        expected: Value = HeatMode.REST
    else:
        assert value is not None
        expected = options[(options.index(value) + 1) % len(options)]
    return toggle(ToggleItem[control.name]), expected
