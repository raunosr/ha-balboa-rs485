"""User-facing CLI contracts."""

import asyncio
import subprocess
import sys

import pytest

from tools.simulator.server import Simulator

from .helpers import loopback_server


@pytest.mark.parametrize("module", ["tools.simulator", "tools.smoke_client", "tools.dev"])
def test_module_help_is_available(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", module, "--help"], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0
    assert "usage:" in result.stdout


@pytest.mark.parametrize(
    "module,args",
    [
        ("tools.simulator", ["--interval", "0"]),
        ("tools.simulator", ["--duration", "nan"]),
        ("tools.simulator", ["--duration", "-1"]),
        ("tools.simulator", ["--scenario", "typo"]),
        ("tools.smoke_client", ["--timeout", "nan"]),
        ("tools.smoke_client", ["--frames", "-1"]),
        ("tools.dev", ["lint", "--bad-option"]),
    ],
)
def test_invalid_cli_options_fail_clearly(module: str, args: list[str]) -> None:
    result = subprocess.run(
        [sys.executable, "-m", module, *args], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 2
    assert "error:" in result.stderr


async def test_smoke_cli_over_real_socket() -> None:
    async with Simulator(port=0) as simulator:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "tools.smoke_client",
            "--port",
            str(simulator.port),
            "--frames",
            "2",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), 10)
    assert process.returncode == 0, stderr.decode()
    assert b"Current 27.0 C -> Target 38.0 C" in stdout
    assert b"TX 0" in stdout


async def test_simulator_cli_serves_and_stops_after_duration() -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "tools.simulator",
        "--port",
        "0",
        "--duration",
        "0.3",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), 10)
    assert process.returncode == 0, stderr.decode()
    assert b"Listening 127.0.0.1:" in stdout and b"Commands: unsupported" in stdout


def test_cli_keyboard_interrupt_exits_cleanly(monkeypatch) -> None:
    from tools.simulator import cli as simulator_cli
    from tools.smoke_client import cli as smoke_cli

    def interrupted(coroutine):
        coroutine.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(asyncio, "run", interrupted)
    assert simulator_cli.main([]) == 130
    assert smoke_cli.main([]) == 130


def test_dev_runner_uses_selected_python_and_propagates_failure(monkeypatch) -> None:
    from tools.dev import main

    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 7 if "mypy" in command else 0)

    monkeypatch.setattr(subprocess, "run", run)
    assert main(["lint"]) == 7
    assert len(calls) == 3
    assert all(command[0] == sys.executable for command in calls)
    assert main(["test", "-q"]) == 0
    assert calls[-1][-1] == "-q"
    assert main(["lab", "--port", "9999"]) == 0
    assert calls[-1][-2:] == ["--port", "9999"]


async def test_smoke_cli_reports_timeout() -> None:
    async def silent(reader, writer):
        await reader.read()

    async with loopback_server(silent) as port:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "tools.smoke_client",
            "--port",
            str(port),
            "--timeout",
            "0.1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), 10)
    assert process.returncode == 1
    assert b"timed out" in stderr
    assert b"TX 0" in stdout


async def test_simulator_cli_reports_occupied_port() -> None:
    async with Simulator(port=0) as simulator:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "tools.simulator",
            "--port",
            str(simulator.port),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(process.communicate(), 10)
    assert process.returncode == 1
    assert b"Simulator error:" in stderr


def test_smoke_cli_reports_connection_error(monkeypatch, capsys) -> None:
    from tools.smoke_client import cli

    async def fail_connect(*args, **kwargs):
        raise ConnectionRefusedError("test refusal")

    monkeypatch.setattr(asyncio, "open_connection", fail_connect)
    assert cli.main([]) == 1
    assert "test refusal" in capsys.readouterr().err


async def test_unbounded_simulator_cli_run_can_be_cancelled(capsys) -> None:
    import argparse

    from tools.simulator.cli import run

    task = asyncio.create_task(
        run(
            argparse.Namespace(
                host="127.0.0.1",
                port=0,
                scenario="normal",
                interval=1,
                fragment_delay=0.01,
                duration=None,
            )
        )
    )
    output = ""
    async with asyncio.timeout(2):
        while "Listening" not in output:
            await asyncio.sleep(0.005)
            output += capsys.readouterr().out
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.parametrize("mode,expected", [("auto", b"TX 0"), ("classic-rs485", b"TX 2")])
async def test_transport_smoke_cli_reports_mode_configuration_and_query_counts(mode, expected):
    async with Simulator(port=0, interval=0.03, transport_lab=True) as simulator:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "tools.smoke_client",
            "--port",
            str(simulator.port),
            "--transport",
            "--mode",
            mode,
            "--duration",
            ".3",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), 10)
    assert process.returncode == 0, stderr.decode()
    assert expected in stdout
    if mode == "classic-rs485":
        assert b"READY" in stdout and b"CONFIG BP SIM" in stdout
    else:
        assert b"UNKNOWN_READ_ONLY" in stdout
