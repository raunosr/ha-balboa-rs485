"""The command lab is explicitly loopback-only and uses the real runtime."""

import asyncio
import sys

import pytest

from tools.simulator.server import Simulator


async def test_scripted_smoke_coalesces_burst_through_real_command_engine():
    async with Simulator(port=0, interval=0.05, control_lab=True) as simulator:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "tools.smoke_client",
            "--port",
            str(simulator.port),
            "--mode",
            "classic-rs485",
            "--command",
            "target 35",
            "--command",
            "target 39",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), 10)
        assert process.returncode == 0, stderr.decode()
        assert b"VERIFIED" in stdout and b"SUPERSEDED" in stdout
        assert simulator.physical_commands == 1


@pytest.mark.parametrize("demo", ["rapid-setpoint-changes", "rapid-pump-intent-changes"])
async def test_named_rapid_intent_demo_is_a_client_burst_not_raw_toggle_replay(demo):
    async with Simulator(port=0, interval=0.05, control_lab=True, scenario=demo) as simulator:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "tools.smoke_client",
            "--port",
            str(simulator.port),
            "--mode",
            "classic-rs485",
            "--demo",
            demo,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), 10)
        assert process.returncode == 0, stderr.decode()
        assert b"VERIFIED" in stdout and b"SUPERSEDED" in stdout
        assert simulator.physical_commands == 1
        if demo == "rapid-setpoint-changes":
            assert simulator.target_temperature == 39
        else:
            assert simulator.pump_states[0] == 1


def test_control_lab_rejects_non_loopback_before_any_network_access():
    from tools.smoke_client.controls import validate_endpoint

    with pytest.raises(ValueError, match="loopback"):
        validate_endpoint("192.0.2.20", "classic-rs485")


async def test_interactive_smoke_accepts_commands_without_blocking_socket_reads():
    async with Simulator(port=0, interval=0.05, control_lab=True) as simulator:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "tools.smoke_client",
            "--port",
            str(simulator.port),
            "--mode",
            "classic-rs485",
            "--interactive",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(b"status\ninvalid\npump1 low\nwait\nhistory\nquit\n"), 10
        )
        assert process.returncode == 0, stderr.decode()
        assert b"VERIFIED pump1=low" in stdout
        assert b"ERROR" in stdout and b"Current 27.0" in stdout
        assert simulator.physical_commands == 1
