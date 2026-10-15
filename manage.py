"""Dependency-light management CLI; safe to import before setup."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage SilentSheet")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("setup", "configure", "choose-task", "update"):
        commands.add_parser(name).add_argument("--silent", action="store_true")
    uninstall = commands.add_parser("uninstall")
    uninstall.add_argument("--purge", action="store_true")
    uninstall.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    try:
        if sys.version_info < (
            3,
            12,
        ):  # noqa: UP036 -- bootstrap may run before supported Python exists
            raise RuntimeError("Python >=3.12 is required")
        if args.command in ("update", "uninstall"):
            from src import installation

            if args.command == "update":
                result = installation.update(ROOT, silent=args.silent)
            else:
                result = installation.uninstall(ROOT, purge=args.purge, yes=args.yes)
        else:
            from src import setup_workflow

            action = getattr(setup_workflow, args.command.replace("-", "_"))
            result = action(ROOT, silent=args.silent)
        return result if isinstance(result, int) else 0
    except (KeyboardInterrupt, EOFError):
        print("Cancelled.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Management failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
