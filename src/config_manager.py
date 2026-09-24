"""Canonical configuration parser, writer, and PowerShell-facing CLI."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import tomllib
from pathlib import Path
from typing import Any

DEFAULT_TASK_NAME = "Development"
DEFAULT_CHARGE_TYPE = "Billable"
_SECTION_RE = re.compile(r"^\s*\[([^]]+)]\s*(?:#.*)?$")


def load_config(path: Path) -> dict[str, Any]:
    """Load and validate a SilentSheet TOML configuration file."""
    config = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    employee_id = config.get("employee", {}).get("EMPLOYEE_ID")
    timesheet = config.get("timesheet", {})
    if not isinstance(employee_id, str) or not employee_id.strip():
        raise ValueError("employee.EMPLOYEE_ID must be a non-empty string")
    for key in ("task_name", "charge_type"):
        value = timesheet.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"timesheet.{key} must be a string")
    return config


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _replace_owned_values(text: str, values: dict[tuple[str, str], str]) -> str:
    lines = text.splitlines()
    current_section = ""
    replaced: set[tuple[str, str]] = set()
    output: list[str] = []

    for line in lines:
        section_match = _SECTION_RE.match(line)
        if section_match:
            current_section = section_match.group(1).strip()
        replacement = None
        for (section, key), value in values.items():
            if current_section == section and re.match(
                rf"^\s*{re.escape(key)}\s*=", line
            ):
                indent = line[: len(line) - len(line.lstrip())]
                replacement = f"{indent}{key} = {_toml_string(value)}"
                replaced.add((section, key))
                break
        output.append(replacement if replacement is not None else line)

    for section in ("employee", "timesheet"):
        missing = [
            (key, value)
            for (owner, key), value in values.items()
            if owner == section and (owner, key) not in replaced
        ]
        if not missing:
            continue
        if output and output[-1].strip():
            output.append("")
        output.append(f"[{section}]")
        output.extend(f"{key} = {_toml_string(value)}" for key, value in missing)

    return "\n".join(output).rstrip() + "\n"


def write_config(
    path: Path, employee_id: str, task_name: str, charge_type: str
) -> None:
    """Atomically write owned config values while preserving unrelated content."""
    if not employee_id.strip() or not task_name.strip() or not charge_type.strip():
        raise ValueError("employee ID, task name, and charge type must be non-empty")
    existing = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    content = _replace_owned_values(
        existing,
        {
            ("employee", "EMPLOYEE_ID"): employee_id,
            ("timesheet", "task_name"): task_name,
            ("timesheet", "charge_type"): charge_type,
        },
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def update_task(path: Path, task_name: str, charge_type: str) -> None:
    config = load_config(path)
    write_config(path, config["employee"]["EMPLOYEE_ID"], task_name, charge_type)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read and write SilentSheet configuration"
    )
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("read")
    subparsers.add_parser("read-employee")
    write_parser = subparsers.add_parser("write")
    write_parser.add_argument("employee_id")
    write_parser.add_argument("task_name")
    write_parser.add_argument("charge_type")
    update_parser = subparsers.add_parser("update-task")
    update_parser.add_argument("task_name")
    update_parser.add_argument("charge_type")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "read":
        config = load_config(args.config)
        print(
            json.dumps(
                {
                    "employee_id": config["employee"]["EMPLOYEE_ID"],
                    "task_name": config.get("timesheet", {}).get(
                        "task_name", DEFAULT_TASK_NAME
                    ),
                    "charge_type": config.get("timesheet", {}).get(
                        "charge_type", DEFAULT_CHARGE_TYPE
                    ),
                }
            )
        )
    elif args.command == "read-employee":
        print(load_config(args.config)["employee"]["EMPLOYEE_ID"])
    elif args.command == "write":
        write_config(args.config, args.employee_id, args.task_name, args.charge_type)
    else:
        update_task(args.config, args.task_name, args.charge_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
