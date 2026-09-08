"""Foreground loopback simulator CLI."""

import argparse
import asyncio
import math
import sys

from .server import SCENARIOS, Simulator


async def run(args: argparse.Namespace) -> None:
    """Serve until cancelled or the optional finite demonstration duration elapses."""
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0):
        raise ValueError("duration must be finite and positive")
    async with Simulator(
        host=args.host,
        port=args.port,
        scenario=args.scenario,
        interval=args.interval,
        fragment_delay=args.fragment_delay,
        transport_lab=getattr(args, "transport_lab", False),
        control_lab=getattr(args, "control_lab", False),
        channel_lab=getattr(args, "channel_lab", False),
    ) as simulator:
        print("Balboa simulator (synthetic protocol/transport lab)", flush=True)
        print(f"Listening {args.host}:{simulator.port}", flush=True)
        protocol = "channel-rs485" if simulator.channel_lab else "classic-rs485"
        print(f"Protocol: {protocol} fixture | Scenario: {args.scenario}", flush=True)
        print("Water: 27.0 C | Target: 38.0 C | Pump1: OFF | Pump2: OFF | Heater: ON", flush=True)
        commands = "loopback physical simulation" if simulator.control_lab else "unsupported"
        print(f"READY interval: ~{args.interval:g}s | Commands: {commands}", flush=True)
        queries = "supported, CTS-gated" if simulator.transport_lab else "disabled"
        print(f"Configuration queries: {queries}", flush=True)
        print(
            f'Next terminal: "{sys.executable}" -m tools.smoke_client '
            f"--host 127.0.0.1 --port {simulator.port} --frames 6",
            flush=True,
        )
        if args.duration is None:
            await asyncio.Event().wait()
        else:
            try:
                async with asyncio.timeout(args.duration):
                    await asyncio.Event().wait()
            except TimeoutError:
                return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthetic Balboa/Elfin TCP simulator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--fragment-delay", type=float, default=0.01)
    parser.add_argument(
        "--control-lab", action="store_true", help="Emulate known physical command effects"
    )
    parser.add_argument(
        "--transport-lab", action="store_true", help="Emulate configuration queries and CTS slots"
    )
    parser.add_argument(
        "--channel-lab", action="store_true", help="Negotiate an epoch-scoped RS485 channel"
    )
    parser.add_argument(
        "--duration", type=float, help="Stop after this many seconds (demo/testing)"
    )
    args = parser.parse_args(argv)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except ValueError as error:
        parser.error(str(error))
    except OSError as error:
        print(f"Simulator error: {error}", file=sys.stderr)
        return 1
    return 0
