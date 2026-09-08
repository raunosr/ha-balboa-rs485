"""Passive by default, with explicit transport and loopback-only control lab modes."""

import argparse
import asyncio
import sys

from balboa_rs485.transport.policy import Mode

from .client import observe
from .controls import DEMOS, run_commands
from .interactive import run_interactive
from .transport import inspect_transport


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Balboa TCP smoke client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument(
        "--frames", type=int, default=0, help="Valid frame count; 0 watches until EOF/Ctrl+C"
    )
    parser.add_argument("--timeout", type=float, default=12.0, help="Seconds per valid-frame wait")
    parser.add_argument("--demo", choices=tuple(DEMOS), help="Named loopback desired-state burst")
    parser.add_argument("--transport", action="store_true", help="Phase 2 lifecycle diagnostic")
    parser.add_argument(
        "--interactive", action="store_true", help="Loopback-only interactive command lab"
    )
    parser.add_argument("--mode", choices=[m.value for m in Mode], default="auto")
    parser.add_argument("--duration", type=float, default=15, help="Bounded transport run, seconds")
    parser.add_argument(
        "--command",
        action="append",
        default=[],
        help="Loopback-only desired command; repeat to coalesce a burst",
    )
    args = parser.parse_args(argv)
    try:
        if args.demo:
            if args.command or args.interactive:
                parser.error("--demo cannot be combined with --command or --interactive")
            args.command = list(DEMOS[args.demo])
        if args.interactive:
            if args.transport or args.frames or args.command:
                parser.error("--interactive cannot be combined with other run modes")
            return run_interactive(
                args.host,
                args.port,
                args.mode,
                args.timeout,
                emit=lambda line: print(line, flush=True),
            )
        if args.command:
            if args.transport or args.frames:
                parser.error("--command cannot be combined with --transport or --frames")
            return asyncio.run(
                run_commands(
                    args.host,
                    args.port,
                    args.mode,
                    args.command,
                    args.timeout,
                    emit=lambda line: print(line, flush=True),
                )
            )
        if args.transport:
            if args.frames:
                parser.error("--frames is for the passive observer, not --transport")
            result = asyncio.run(
                inspect_transport(
                    args.host,
                    args.port,
                    mode=Mode(args.mode),
                    duration=args.duration,
                    first_frame_timeout=args.timeout,
                    emit=lambda line: print(line, flush=True),
                )
            )
            return (
                0
                if result.available
                or (
                    args.mode in ("auto", "unknown-read-only", "channel-rs485")
                    and result.rx_frames > 0
                )
                else 1
            )
        if args.mode != "auto":
            parser.error("--mode requires --transport; the default observer never transmits")
        asyncio.run(
            observe(
                args.host,
                args.port,
                frame_limit=args.frames,
                timeout=args.timeout,
                emit=lambda line: print(line, flush=True),
            )
        )
    except KeyboardInterrupt:
        return 130
    except ValueError as error:
        parser.error(str(error))
    except TimeoutError:
        print(
            "Smoke error: timed out connecting or waiting for a valid Balboa frame", file=sys.stderr
        )
        return 1
    except OSError as error:
        print(f"Smoke error: {error}", file=sys.stderr)
        return 1
    return 0
