"""Portable equivalents of Make targets, using the currently selected Python."""

import argparse
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Balboa development commands")
    parser.add_argument("command", choices=("test", "lint", "simulator", "smoke", "lab"))
    args, extra = parser.parse_known_args(argv)
    commands = {
        "test": [["pytest", "--cov", "--cov-report=term-missing", "--cov-report=json", *extra]],
        "lint": [["ruff", "check", "."], ["ruff", "format", "--check", "."], ["mypy"]],
        "simulator": [["tools.simulator", *extra]],
        "lab": [["tools.simulator", *extra]],
        "smoke": [["tools.smoke_client", *extra]],
    }
    if args.command == "lint" and extra:
        parser.error("lint does not accept extra arguments")
    for command in commands[args.command]:
        result = subprocess.run([sys.executable, "-m", *command], check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
