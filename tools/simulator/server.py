"""Async synthetic server. No real hardware commands are implemented."""

import asyncio
import json
import logging
import math
from collections import deque
from dataclasses import dataclass, replace
from importlib.resources import files
from types import TracebackType
from typing import Self

from balboa_rs485.protocol.configuration import Query, encode_query
from balboa_rs485.protocol.frames import Frame, FrameParser, encode_frame

SCENARIOS = (
    "normal",
    "bad-crc",
    "partial-frame",
    "garbage-before-frame",
    "silent-zombie-socket",
    "missing-configuration",
    "configuration-change",
    "slow-network",
    "connection-reset",
    "elfin-reboot",
    "missing-ready",
    "unknown-protocol",
    "channel-protocol",
    "channel-after-sync",
    "lost-status-after-command",
    "single-speed-pump",
    "reset-after-command",
    "accessories",
    "missing-metadata",
    "metadata-change",
    "rapid-setpoint-changes",
    "rapid-pump-intent-changes",
)
_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SimulatorStats:
    received_bytes: int = 0
    transmitted_frames: int = 0
    connection_errors: int = 0
    connections: int = 0
    rejected_queries: int = 0
    idle_replies: int = 0


@dataclass(frozen=True, slots=True)
class QueryRecord:
    connection: int
    cycle: int
    frame: Frame


def configuration_fixture(
    query: Query, *, changed: bool = False, single_speed: bool = False, accessories: bool = False
) -> Frame:
    """Synthetic descriptors, not a capture or claim about real spa capabilities."""
    if query == Query.INFORMATION:
        model = b"BP SIM2 " if changed else b"BP SIM  "
        return Frame(
            10,
            191,
            36,
            bytes.fromhex("64 dc 01 02") + model + bytes.fromhex("01 12 34 56 78 01 0a 00 01"),
        )
    if query == Query.SETUP:
        return Frame(10, 191, 37, bytes.fromhex("00 00 32 63 50 68 00 02 00"))
    if query == Query.FILTERS:
        return Frame(10, 191, 35, bytes((8, 0, 2, 0, 128 | 20, 0, 2, 0)))
    if query == Query.FAULT:
        return Frame(10, 191, 40, bytes(10))
    return Frame(
        10,
        191,
        46,
        bytes(
            (
                9 if single_speed else 10,
                0,
                69 if accessories else 1,
                130,
                19 if accessories else 0,
                0,
            )
        ),
    )


def load_status_fixture() -> Frame:
    """Read packaged synthetic status data, including when installed as a wheel."""
    data = json.loads(files("tools.simulator").joinpath("fixtures/normal.json").read_text())
    return Frame(
        data["address"],
        data["family"],
        data["message_type"],
        bytes.fromhex(data["payload_hex"]),
    )


class Simulator:
    """Shared synthetic physical state, per-connection bus slots, explicit task ownership."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8899,
        interval: float = 1.0,
        scenario: str = "normal",
        fragment_delay: float = 0.01,
        transport_lab: bool = False,
        control_lab: bool = False,
        channel_lab: bool = False,
    ) -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"Unknown scenario: {scenario}")
        if not 0 <= port <= 65535:
            raise ValueError("port must be 0..65535")
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("interval must be finite and positive")
        if not math.isfinite(fragment_delay) or fragment_delay < 0:
            raise ValueError("fragment_delay must be finite and nonnegative")
        self.host, self.port, self.interval = host, port, interval
        self.scenario, self.fragment_delay = scenario, fragment_delay
        self.transport_lab = (
            transport_lab or control_lab or channel_lab or scenario not in SCENARIOS[:4]
        )
        self.control_lab = control_lab
        self.channel_lab = channel_lab
        self.pump_states = [0] * 6
        self.pump1_forced_low = False
        self.physical_commands = 0
        self._profile_targets = {False: 27.0, True: 38.0}
        self.light_states = [False, False]
        self.aux_states = [False, False]
        self.mister = False
        self.blower = 0
        self.heat_mode = 0
        self.high_range = True
        self.filter_payload = configuration_fixture(Query.FILTERS).payload
        self.fault_payload = configuration_fixture(Query.FAULT).payload
        self.fahrenheit = False
        self.clock_minutes = 12 * 60
        self.clock_24h = False
        self.hold = False
        self.reminder_code: int | None = None
        self.reminder_queue: list[int] = []
        self._reminder_acknowledged = False
        self.physical_records: deque[QueryRecord] = deque(maxlen=128)
        self._drop_status_connection: int | None = None
        self.stats = SimulatorStats()
        self.query_records: deque[QueryRecord] = deque(maxlen=128)
        self._server: asyncio.Server | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._writers: set[asyncio.StreamWriter] = set()
        self._closing = False
        self._cycle = self._make_cycle()

    @property
    def target_temperature(self) -> float:
        return self._profile_targets[self.high_range]

    @target_temperature.setter
    def target_temperature(self, value: float) -> None:
        self._profile_targets[self.high_range] = value

    @property
    def active_connections(self) -> int:
        return len(self._tasks)

    async def __aenter__(self) -> Self:
        if self._server is not None:
            raise RuntimeError("Simulator is already started; use a new instance")
        self._server = await asyncio.start_server(self._accept, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._server is not None
        self._closing = True
        self._server.close()
        # Close connections before wait_closed(), which waits for clients too.
        # Track writers separately so a task cancelled before starting cannot leak one.
        for writer in tuple(self._writers):
            writer.close()
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.difference_update(tasks)
        await self._server.wait_closed()

    def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self._closing:
            writer.close()
            return
        self._writers.add(writer)
        task = asyncio.create_task(self._serve(reader, writer))
        self._tasks.add(task)
        task.add_done_callback(lambda done: self._client_done(done, writer))

    def _client_done(self, task: asyncio.Task[None], writer: asyncio.StreamWriter) -> None:
        writer.close()
        self._writers.discard(writer)
        self._tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            self.stats.connection_errors += 1
            _LOGGER.error("Simulator client failed: %s", error)

    def _make_cycle(self) -> bytes:
        ready = encode_frame(Frame(0x10, 0xBF, 0x06))
        status = encode_frame(load_status_fixture())
        cycle = ready + status
        if self.scenario == "bad-crc":
            bad = status[:-2] + bytes((status[-2] ^ 1, status[-1]))
            cycle = ready + bad + status
        elif self.scenario == "garbage-before-frame":
            cycle = b"\x00\xffELFIN-JUNK" + cycle
        return cycle

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        cycle = self._cycle
        self.stats.connections += 1
        connection = self.stats.connections
        try:
            if self.transport_lab:
                await self._serve_bus(reader, writer, connection)
                return
            while True:
                if self.scenario == "partial-frame":
                    # Fault injection only; not a command/bus synchronization mechanism.
                    for offset in range(0, len(cycle), 3):
                        writer.write(cycle[offset : offset + 3])
                        await writer.drain()
                        await asyncio.sleep(self.fragment_delay)
                else:
                    writer.write(cycle)
                    await writer.drain()
                self.stats.transmitted_frames += 3 if self.scenario == "bad-crc" else 2
                try:
                    data = await asyncio.wait_for(reader.read(4096), self.interval)
                except TimeoutError:
                    continue
                if not data:
                    break
                self.stats.received_bytes += len(data)
        finally:
            writer.close()
            try:
                async with asyncio.timeout(2):
                    await writer.wait_closed()
            except (TimeoutError, ConnectionError):
                writer.transport.abort()

    async def _serve_bus(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        connection: int,
    ) -> None:
        parser = FrameParser()
        address = await self._assign_channel(reader, writer, connection) if self.channel_lab else 10
        if address is None:
            return
        cts_address = address if self.channel_lab else 16
        cycle = 0
        while True:
            cycle += 1
            if (
                connection == 1
                and cycle > 4
                and self.scenario in ("connection-reset", "elfin-reboot")
            ):
                if self.scenario == "elfin-reboot":
                    writer.write(encode_frame(load_status_fixture())[:8])
                    await writer.drain()
                else:
                    writer.transport.abort()
                return
            if self.scenario == "silent-zombie-socket" and connection == 1 and cycle > 4:
                await reader.read()  # Deliberately hold an open, silent socket until peer closes.
                return
            # A final CTS opens a bus slot. Status never immediately closes it.
            status_frame = load_status_fixture()
            if self.control_lab:
                payload = bytearray(status_frame.payload)
                payload[0] = 5 if self.hold else payload[0]
                if self.reminder_code is not None:
                    payload[1], payload[6], payload[18] = 3, self.reminder_code, 1
                elif self._reminder_acknowledged:
                    payload[1], payload[6], payload[18] = 0, 0, 0
                payload[11] = sum(value << (2 * i) for i, value in enumerate(self.pump_states[:4]))
                payload[12] = self.pump_states[4] | self.pump_states[5] << 2
                payload[5] = self.heat_mode
                payload[10] = (payload[10] & ~4) | (4 if self.high_range else 0)
                payload[13] = 2 | (self.blower << 2)
                payload[15] = (
                    int(self.mister)
                    | (8 if self.aux_states[0] else 0)
                    | (16 if self.aux_states[1] else 0)
                )
                payload[14] = (3 if self.light_states[0] else 0) | (
                    12 if self.light_states[1] else 0
                )
                payload[20] = int(self.target_temperature * (1 if self.fahrenheit else 2))
                if self.fahrenheit and payload[2] != 255:
                    payload[2] = round(payload[2] / 2 * 1.8 + 32)
                payload[9] = (
                    (payload[9] & ~3) | (0 if self.fahrenheit else 1) | (2 if self.clock_24h else 0)
                )
                payload[3], payload[4] = divmod(self.clock_minutes, 60)
                status_frame = Frame(255, 175, 19, bytes(payload))
            status = encode_frame(status_frame)
            wire = status + encode_frame(Frame(cts_address, 191, 6))
            count = 2
            if self.scenario == "metadata-change" and cycle > 10:
                wire = (
                    encode_frame(Frame(10, 191, 40, bytes((1, 0, 17, 0, 12, 0, 0, 76, 72, 72))))
                    + wire
                )
                count += 1
            if connection == self._drop_status_connection:
                wire, count = encode_frame(Frame(cts_address, 191, 6)), 1
            if self.scenario == "missing-ready":
                wire, count = status, 1
            elif self.scenario == "unknown-protocol":
                wire, count = encode_frame(Frame(17, 238, 96, b"opaque")), 1
            elif (
                self.scenario == "channel-protocol"
                or self.scenario == "channel-after-sync"
                and cycle > 4
            ):
                wire = encode_frame(Frame(254, 191, 0)) + wire
                count += 1
            if self.scenario == "bad-crc":
                wire = status[:-2] + bytes((status[-2] ^ 1, status[-1])) + wire
                count += 1
            elif self.scenario == "garbage-before-frame":
                wire = b"\0\xffELFIN-JUNK" + wire
            if self.scenario in ("partial-frame", "slow-network"):
                delay = self.fragment_delay if self.scenario == "partial-frame" else self.interval
                for offset in range(0, len(wire), 3 if self.scenario == "partial-frame" else 12):
                    size = 3 if self.scenario == "partial-frame" else 12
                    writer.write(wire[offset : offset + size])
                    await writer.drain()
                    await asyncio.sleep(
                        delay
                    )  # Synthetic link latency, never a client TX strategy.
            else:
                writer.write(wire)
                await writer.drain()
            self.stats.transmitted_frames += count
            granted = self.scenario not in ("missing-ready", "unknown-protocol", "channel-protocol")
            deadline = asyncio.get_running_loop().time() + self.interval
            while asyncio.get_running_loop().time() < deadline:
                try:
                    async with asyncio.timeout_at(deadline):
                        data = await reader.read(4096)
                except TimeoutError:
                    break
                if not data:
                    return
                self.stats.received_bytes += len(data)
                for frame in parser.feed(data):
                    if self.channel_lab and granted and frame == Frame(address, 191, 7):
                        self.stats.idle_replies += 1
                        granted = False
                        continue
                    handled = False
                    if (
                        self.control_lab
                        and granted
                        and (frame.address, frame.family) == (address, 191)
                    ):
                        if (
                            frame.message_type == 32
                            and len(frame.payload) == 1
                            and (50 if self.fahrenheit else 20)
                            <= frame.payload[0]
                            <= (104 if self.fahrenheit else 80)
                        ):
                            self.target_temperature = frame.payload[0] / (
                                1 if self.fahrenheit else 2
                            )
                            handled = True
                        elif frame.message_type == 0x21 and len(frame.payload) == 2:
                            self.clock_24h = bool(frame.payload[0] & 128)
                            self.clock_minutes = (frame.payload[0] & 127) * 60 + frame.payload[1]
                            handled = True
                        elif frame.message_type == 0x27 and frame.payload in (
                            b"\x01\0",
                            b"\x01\x01",
                        ):
                            fahrenheit = frame.payload[1] == 0
                            if fahrenheit != self.fahrenheit:
                                self._profile_targets = {
                                    k: round(v * 1.8 + 32)
                                    if fahrenheit
                                    else round((v - 32) / 1.8 * 2) / 2
                                    for k, v in self._profile_targets.items()
                                }
                            self.fahrenheit = fahrenheit
                            handled = True
                        elif frame.message_type == 0x27 and frame.payload in (
                            b"\x02\0",
                            b"\x02\x01",
                        ):
                            self.clock_24h = bool(frame.payload[1])
                            handled = True
                        elif frame.message_type == 35 and len(frame.payload) == 8:
                            self.filter_payload = frame.payload
                            handled = True
                        elif frame.message_type == 17 and frame.payload == b"\x11\0":
                            self.light_states[0] = not self.light_states[0]
                            handled = True
                        elif (
                            frame.message_type == 17
                            and len(frame.payload) == 2
                            and frame.payload[1] == 0
                        ):
                            item = frame.payload[0]
                            if item == 12:
                                self.blower = (self.blower + 1) % 3
                                handled = True
                            elif item == 60:
                                self.hold = not self.hold
                                handled = True
                            elif item == 3:
                                self.reminder_code = (
                                    self.reminder_queue.pop(0) if self.reminder_queue else None
                                )
                                self._reminder_acknowledged = True
                                handled = True
                            elif item == 1:
                                self.hold = False
                                handled = True
                            elif item == 29:
                                self.pump_states = [0] * 6
                                handled = True
                            elif item == 80:
                                self.high_range = not self.high_range
                                handled = True
                            elif item == 81:
                                self.heat_mode = 1 if self.heat_mode in (0, 2) else 0
                                handled = True
                            elif self.scenario == "accessories":
                                if item == 18:
                                    self.light_states[1] = not self.light_states[1]
                                    handled = True
                                elif item == 14:
                                    self.mister = not self.mister
                                    handled = True
                                elif item in (22, 23):
                                    self.aux_states[item - 22] = not self.aux_states[item - 22]
                                    handled = True
                    if (
                        self.control_lab
                        and granted
                        and frame.address == address
                        and frame.family == 191
                        and frame.message_type == 17
                        and len(frame.payload) == 2
                        and frame.payload[1] == 0
                        and 4 <= frame.payload[0] <= 5
                    ):
                        index = frame.payload[0] - 4
                        if self.scenario == "single-speed-pump" and index == 0:
                            self.pump_states[index] = 0 if self.pump_states[index] else 2
                        else:
                            self.pump_states[index] = (self.pump_states[index] + 1) % 3
                        if index == 0 and self.pump1_forced_low and self.pump_states[0] == 0:
                            self.pump_states[0] = 1
                        handled = True
                    if handled:
                        self.physical_commands += 1
                        self.physical_records.append(QueryRecord(connection, cycle, frame))
                        granted = False
                        if self.scenario == "reset-after-command" and self.physical_commands == 1:
                            writer.transport.abort()
                            return
                        if (
                            self.scenario == "lost-status-after-command"
                            and self.physical_commands == 1
                        ):
                            self._drop_status_connection = connection
                        continue
                    query = next(
                        (q for q in Query if frame == replace(encode_query(q), address=address)),
                        None,
                    )
                    if not granted or query is None:
                        self.stats.rejected_queries += 1
                        continue
                    granted = False
                    self.query_records.append(QueryRecord(connection, cycle, frame))
                    if self.scenario == "missing-configuration" or (
                        self.scenario == "missing-metadata"
                        and query in (Query.SETUP, Query.FILTERS, Query.FAULT)
                    ):
                        continue
                    response = configuration_fixture(
                        query,
                        changed=self.scenario == "configuration-change" and cycle > 4,
                        single_speed=self.scenario == "single-speed-pump",
                        accessories=self.scenario == "accessories",
                    )
                    if query == Query.FILTERS:
                        response = replace(response, payload=self.filter_payload)
                    if query == Query.FAULT:
                        response = replace(response, payload=self.fault_payload)
                    writer.write(
                        encode_frame(
                            replace(
                                response,
                                address=address,
                            )
                        )
                    )
                    await writer.drain()
                    self.stats.transmitted_frames += 1

    async def _assign_channel(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        connection: int,
    ) -> int | None:
        parser = FrameParser()
        address = 17 + connection
        while True:
            writer.write(
                encode_frame(load_status_fixture())
                + encode_frame(Frame(17, 191, 7))
                + encode_frame(Frame(254, 191, 0))
            )
            await writer.drain()
            try:
                data = await asyncio.wait_for(reader.read(4096), self.interval)
            except TimeoutError:
                continue
            if not data:
                return None
            for frame in parser.feed(data):
                if (frame.address, frame.family, frame.message_type) != (254, 191, 1):
                    self.stats.rejected_queries += 1
                    continue
                if len(frame.payload) != 3 or frame.payload[0] != 2:
                    self.stats.rejected_queries += 1
                    continue
                writer.write(
                    encode_frame(Frame(254, 191, 2, bytes((address,)) + frame.payload[1:]))
                )
                await writer.drain()
                async with asyncio.timeout(2):
                    while data := await reader.read(4096):
                        if Frame(address, 191, 3) in parser.feed(data):
                            return address
                return None
