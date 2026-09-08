"""Known physical command serialization. These functions never transmit."""

import math
from enum import IntEnum

from .frames import Frame
from .messages import TemperatureUnit


class ToggleItem(IntEnum):
    NORMAL_OPERATION = 1
    ACK_REMINDER = 3
    PUMP1 = 4
    PUMP2 = 5
    PUMP3 = 6
    PUMP4 = 7
    PUMP5 = 8
    PUMP6 = 9
    BLOWER = 12
    MISTER = 14
    LIGHT1 = 17
    LIGHT2 = 18
    AUX1 = 22
    AUX2 = 23
    SOAK = 29
    HOLD = 60
    HIGH_RANGE = 80
    HEAT_MODE = 81


def toggle(item: ToggleItem) -> Frame:
    if not isinstance(item, ToggleItem):
        raise ValueError("Only supported physical items may be encoded")
    return Frame(10, 191, 17, bytes((item, 0)))


def set_temperature(value: float, unit: TemperatureUnit) -> Frame:
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not isinstance(unit, TemperatureUnit)
    ):
        raise ValueError("A finite temperature and explicit unit are required")
    raw = value * (2 if unit == TemperatureUnit.CELSIUS else 1)
    low, high = (10, 40) if unit == TemperatureUnit.CELSIUS else (50, 104)
    if raw != int(raw):
        raise ValueError("Temperature must match the unit resolution")
    if not low <= value <= high:
        raise ValueError("Temperature is outside the conservative supported envelope")
    return Frame(10, 191, 32, bytes((int(raw),)))


def pump_toggle(index: int) -> Frame:
    if type(index) is not int or not 1 <= index <= 6:
        raise ValueError("pump index must be 1..6")
    return toggle(ToggleItem(3 + index))


def set_clock(minute_of_day: int, clock_24h: bool) -> Frame:
    if (
        type(minute_of_day) is not int
        or not 0 <= minute_of_day < 1440
        or type(clock_24h) is not bool
    ):
        raise ValueError("Clock requires minute-of-day 0..1439 and explicit format")
    hour, minute = divmod(minute_of_day, 60)
    return Frame(10, 0xBF, 0x21, bytes((hour | (0x80 if clock_24h else 0), minute)))


def set_temperature_unit(unit: TemperatureUnit) -> Frame:
    if not isinstance(unit, TemperatureUnit):
        raise ValueError("Explicit temperature unit required")
    return Frame(10, 0xBF, 0x27, bytes((1, int(unit == TemperatureUnit.CELSIUS))))


def set_clock_format(clock_24h: bool) -> Frame:
    if type(clock_24h) is not bool:
        raise ValueError("Clock format must be explicit")
    return Frame(10, 0xBF, 0x27, bytes((2, int(clock_24h))))
