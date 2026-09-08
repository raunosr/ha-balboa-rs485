"""Loopback-only command lab; the real spa is not write-supported yet."""

import ipaddress
import math
from collections.abc import Callable

from balboa_rs485.command.engine import Intent, Stage
from balboa_rs485.protocol.messages import HeatMode
from balboa_rs485.runtime import SpaRuntime
from balboa_rs485.state.model import Control, PumpState, Value
from balboa_rs485.transport.policy import Mode

DEMOS = {
    "rapid-setpoint-changes": ("target 35", "target 36", "target 37", "target 39"),
    "rapid-pump-intent-changes": ("pump1 high", "pump1 off", "pump1 low"),
}


def validate_endpoint(host: str, mode: str) -> None:
    if not ipaddress.ip_address(host).is_loopback:
        raise ValueError("Physical command lab is restricted to numeric loopback addresses")
    if mode != Mode.CLASSIC_RS485:
        raise ValueError("Command lab requires explicit --mode classic-rs485")


def parse_command(line: str) -> tuple[Control, Value]:
    parts = line.lower().split()
    if len(parts) != 2:
        raise ValueError(
            "Use: pump1 high | target 39 | light1 on | heat_mode rest | high_range low"
        )
    control = Control(parts[0])
    word = parts[1]
    if control.value.startswith("pump"):
        value: Value = PumpState(word)
    elif control == Control.TARGET:
        value = float(word)
    elif control == Control.BLOWER:
        value = int(word)
    elif control == Control.HEAT_MODE:
        if word not in ("ready", "rest"):
            raise ValueError("heat_mode must be ready or rest")
        value = HeatMode.READY if word == "ready" else HeatMode.REST
    else:
        allowed = ("low", "high") if control == Control.HIGH_RANGE else ("off", "on")
        if word not in allowed:
            raise ValueError(f"{control.value} must be {allowed[0]} or {allowed[1]}")
        value = word == allowed[1]
    return control, value


async def ready(runtime: SpaRuntime, deadline: float) -> None:
    await runtime.connection.wait_for(
        lambda s: s.available and runtime.metadata_complete,
        timeout=deadline,
    )


def submit(runtime: SpaRuntime, line: str, emit: Callable[[str], None]) -> Intent:
    control, value = parse_command(line)
    intent = runtime.request(control, value)
    emit(f"desired {control.value}={value} | intent {intent.id} | WAITING_FOR_BUS")
    return intent


async def report(
    runtime: SpaRuntime, intent: Intent, deadline: float, emit: Callable[[str], None]
) -> bool:
    result = await runtime.wait_for_intent(intent.id, timeout=deadline)
    emit(
        f"{result.stage} {result.control.value}={result.desired} | "
        f"{result.reason or 'observed outcome'}"
    )
    return result.stage in (Stage.VERIFIED, Stage.SUPERSEDED)


def show_history(runtime: SpaRuntime, emit: Callable[[str], None]) -> None:
    for row in runtime.engine.history:
        emit(
            f"TX {row.action.frame.message_type:02x} {row.action.intent.control.value} "
            f"{row.starting_value} -> {row.resulting_value} | epoch {row.action.epoch} "
            f"CTS {row.cts_at} sent {row.sent_at:.3f} | {row.result} "
            f"latency {row.latency if row.latency is not None else 'pending'}s"
        )


async def run_commands(
    host: str,
    port: int,
    mode: str,
    commands: list[str],
    deadline: float,
    emit: Callable[[str], None] = print,
) -> int:
    validate_endpoint(host, mode)
    if not math.isfinite(deadline) or deadline <= 0:
        raise ValueError("Command deadline must be finite and positive")
    async with SpaRuntime(host, port, mode=Mode(mode)) as runtime:
        await ready(runtime, deadline)
        emit("CONFIG synchronized | loopback command lab READY")
        if runtime.metadata_failures:
            emit(f"METADATA unavailable: {', '.join(runtime.metadata_failures)}")
        intents = [submit(runtime, command, emit) for command in commands]
        results = [await report(runtime, intent, deadline, emit) for intent in intents]
        show_history(runtime, emit)
        return 0 if all(results) else 1
