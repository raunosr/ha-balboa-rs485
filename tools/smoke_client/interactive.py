"""Console input stays on the main thread; one joined worker owns all async sockets."""

import asyncio
import math
import sys
import threading
from collections.abc import Callable, Coroutine
from typing import Any

from balboa_rs485.runtime import SpaRuntime
from balboa_rs485.state.model import Control
from balboa_rs485.transport.policy import Mode

from .controls import ready, report, show_history, submit, validate_endpoint


def run_interactive(
    host: str, port: int, mode: str, deadline: float, emit: Callable[[str], None] = print
) -> int:
    validate_endpoint(host, mode)
    if not math.isfinite(deadline) or deadline <= 0:
        raise ValueError("Command deadline must be finite and positive")
    runtime = SpaRuntime(host, port, mode=Mode(mode))
    loop = asyncio.new_event_loop()
    worker = threading.Thread(target=loop.run_forever, name="balboa-lab-network")
    tasks: set[asyncio.Task[bool]] = set()

    def call[T](coroutine: Coroutine[Any, Any, T]) -> T:
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        try:
            return future.result(timeout=deadline + 3)
        except BaseException:
            future.cancel()
            raise

    def done(task: asyncio.Task[bool]) -> None:
        tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            emit(f"ERROR verification: {error}")

    async def command(line: str) -> None:
        if line == "wait":
            await asyncio.gather(*tuple(tasks))
        elif line == "history":
            show_history(runtime, emit)
        elif line == "status":
            state = runtime.state
            if state is None:
                emit("STATUS unknown")
            else:
                emit(
                    f"Current {state.current_temperature} {state.status.unit} -> "
                    f"Target {state.target_temperature}; available={state.available}"
                )
        elif line.startswith("cancel "):
            runtime.engine.cancel(Control(line.split(maxsplit=1)[1]))
        else:
            intent = submit(runtime, line, emit)
            task = asyncio.create_task(report(runtime, intent, deadline, emit))
            tasks.add(task)
            task.add_done_callback(done)

    async def shutdown() -> None:
        pending = tuple(tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await runtime.__aexit__(None, None, None)

    entered = False
    worker.start()
    try:
        call(runtime.__aenter__())
        entered = True
        call(ready(runtime, deadline))
        emit("CONFIG synchronized | loopback command lab READY")
        emit(
            "Commands: pump1 high, target 39, light1 on, status, history, wait, cancel pump1, quit"
        )
        for raw in sys.stdin:
            line = raw.strip().lower()
            if line == "quit":
                break
            if not line:
                continue
            try:
                call(command(line))
            except (ValueError, TimeoutError) as error:
                emit(f"ERROR {error}")
        return 0
    finally:
        try:
            if entered:
                call(shutdown())
        finally:
            loop.call_soon_threadsafe(loop.stop)
            worker.join()
            loop.close()
