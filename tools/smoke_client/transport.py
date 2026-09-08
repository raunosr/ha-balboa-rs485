"""Bounded transport diagnostic. Only explicit supported modes issue read queries."""

import asyncio
import math
from collections.abc import Callable

from balboa_rs485.transport.connection import Snapshot, SpaConnection
from balboa_rs485.transport.policy import Mode
from balboa_rs485.transport.timing import Timing

type SnapshotKey = tuple[object, ...]


def _key(snapshot: Snapshot) -> SnapshotKey:
    return (
        snapshot.state,
        snapshot.epoch,
        snapshot.configuration_revision,
        snapshot.tx_frames,
        snapshot.recoveries,
        snapshot.candidate,
    )


def _different(previous: SnapshotKey | None) -> Callable[[Snapshot], bool]:
    return lambda snapshot: _key(snapshot) != previous


async def inspect_transport(
    host: str,
    port: int,
    *,
    mode: Mode = Mode.AUTO,
    duration: float = 15,
    first_frame_timeout: float = 12,
    emit: Callable[[str], None] = print,
) -> Snapshot:
    """Return the last live snapshot after shutting down all owned socket work."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration must be finite and positive")
    timing = Timing(connect=first_frame_timeout, first_frame=first_frame_timeout)
    async with SpaConnection(host, port, mode=mode, timing=timing) as connection:
        key: SnapshotKey | None = None
        try:
            async with asyncio.timeout(duration):
                while True:
                    snapshot = await connection.wait_for(_different(key), timeout=duration)
                    key = _key(snapshot)
                    emit(
                        f"STATE {snapshot.state} | mode {snapshot.mode.name} | "
                        f"candidate {snapshot.candidate.value} | epoch {snapshot.epoch}"
                    )
                    if snapshot.configuration:
                        emit(
                            f"CONFIG {snapshot.configuration.information.model} "
                            f"revision {snapshot.configuration_revision} "
                            f"signature {snapshot.configuration.signature}"
                        )
                    if snapshot.last_error:
                        emit(f"RECOVERY {snapshot.last_error}")
        except TimeoutError:
            pass
        result = connection.snapshot
    emit(
        f"RX {result.rx_frames} TX {result.tx_frames} CRC errors {result.crc_errors} "
        f"invalid messages {result.invalid_messages} recoveries {result.recoveries} "
        f"rate {result.health.frames_per_second:.1f}/s available={result.available}"
    )
    return result
