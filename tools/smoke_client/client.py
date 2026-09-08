"""Read a TCP stream without ever writing application bytes to it."""

import asyncio
import math
from collections.abc import Callable
from dataclasses import dataclass, field

from balboa_rs485.protocol.frames import FrameCounters, FrameParser
from balboa_rs485.protocol.messages import (
    MessageDecodeError,
    ReadyMessage,
    StatusMessage,
    UnknownMessage,
    decode_message,
)


@dataclass(slots=True)
class SmokeReport:
    """Bounded counters only; no retained stream or command queue."""

    frames: FrameCounters = field(default_factory=FrameCounters)
    received_bytes: int = 0
    ready_messages: int = 0
    status_messages: int = 0
    unknown_message_types: int = 0
    invalid_messages: int = 0
    tx_frames: int = 0
    configuration_messages: int = 0


async def observe(
    host: str,
    port: int,
    *,
    frame_limit: int = 0,
    timeout: float = 12.0,  # noqa: ASYNC109 -- per-frame deadline policy
    emit: Callable[[str], None] = print,
) -> SmokeReport:
    """Observe validated frames with a deadline that junk bytes cannot extend."""
    if not 1 <= port <= 65535 or frame_limit < 0:
        raise ValueError("port must be 1..65535 and frame_limit must be nonnegative")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    parser = FrameParser()
    report = SmokeReport(frames=parser.counters)
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    count = 0
    deadline = asyncio.get_running_loop().time() + timeout
    try:
        emit("TCP CONNECTED (read-only; spa availability not established)")
        emit("CONFIG pending (passive observer does not issue synchronization queries)")
        while frame_limit == 0 or count < frame_limit:
            async with asyncio.timeout_at(deadline):
                chunk = await reader.read(4096)
            if not chunk:
                emit("EOF")
                break
            report.received_bytes += len(chunk)
            for frame in parser.feed(chunk):
                if frame_limit and count >= frame_limit:
                    break
                count += 1
                deadline = asyncio.get_running_loop().time() + timeout
                try:
                    message = decode_message(frame)
                except MessageDecodeError as error:
                    report.invalid_messages += 1
                    emit(f"INVALID MESSAGE: {error}")
                    continue
                if isinstance(message, ReadyMessage):
                    report.ready_messages += 1
                    emit("READY 10 bf 06 observed (classic-rs485 signature; TX disabled)")
                elif isinstance(message, StatusMessage):
                    report.status_messages += 1
                    current = (
                        "unknown"
                        if message.current_temperature is None
                        else str(message.current_temperature)
                    )
                    target = (
                        "unknown"
                        if message.target_temperature is None
                        else str(message.target_temperature)
                    )
                    emit(
                        f"STATUS Current {current} {message.unit} -> "
                        f"Target {target} {message.unit}; "
                        f"Heat {message.heat_state.name}; Pump1 raw={message.pumps_raw[0]}"
                    )
                elif isinstance(message, UnknownMessage):
                    report.unknown_message_types += 1
                    emit(
                        f"UNKNOWN {frame.address:02x} {frame.family:02x} "
                        f"{frame.message_type:02x} ({len(frame.payload)} bytes)"
                    )
                else:
                    report.configuration_messages += 1
                    emit(f"OBSERVED CONFIG {type(message).__name__} ({len(frame.payload)} bytes)")
    finally:
        parser.reset()
        writer.close()
        try:
            async with asyncio.timeout(2):
                await writer.wait_closed()
        except (TimeoutError, ConnectionError):
            writer.transport.abort()
        emit(
            f"RX {report.frames.rx_frames} TX 0 CRC errors {report.frames.crc_errors} "
            f"invalid length {report.frames.invalid_length} "
            f"invalid end {report.frames.invalid_end} "
            f"discarded bytes {report.frames.discarded_bytes} "
            f"unknown {report.unknown_message_types} invalid messages {report.invalid_messages}"
        )
    return report
