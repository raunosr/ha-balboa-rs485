"""Loopback server boundary with owned tasks and deterministic cleanup."""

import asyncio
from contextlib import asynccontextmanager


def install_filter_reminder_variant(monkeypatch):
    """Synthetic protocol variant, not a replay of a private hardware capture."""
    from dataclasses import replace

    from balboa_rs485.protocol.configuration import Query
    from tools.simulator import server

    status_fixture = server.load_status_fixture
    configuration_fixture = server.configuration_fixture

    def status():
        frame = status_fixture()
        data = bytearray(frame.payload)
        data[0], data[1], data[6], data[9] = 0, 3, 4, 3
        data[18], data[19], data[21] = 1, 32, 0
        return replace(frame, payload=bytes(data))

    def configuration(query, **kwargs):
        frame = configuration_fixture(query, **kwargs)
        return replace(frame, payload=frame.payload + b"\x02") if query == Query.SETUP else frame

    monkeypatch.setattr(server, "load_status_fixture", status)
    monkeypatch.setattr(server, "configuration_fixture", configuration)


@asynccontextmanager
async def loopback_server(handler):
    tasks = set()

    async def client(reader, writer):
        try:
            await handler(reader, writer)
        except ConnectionError:
            pass  # Expected when a deadline/cancellation test closes its client.
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    def accept(reader, writer):
        tasks.add(asyncio.create_task(client(reader, writer)))

    server = await asyncio.start_server(accept, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        server.close()
        for task in tasks:
            if not task.done():
                task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        await server.wait_closed()
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                raise result
