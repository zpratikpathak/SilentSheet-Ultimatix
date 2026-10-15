"""Stdlib-only setup and interactive configuration orchestration."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .config_manager import load_config, write_config


def select_option(prompt: str, options: list[str], default: int = 0) -> int:
    if not options or not 0 <= default < len(options):
        raise ValueError("Invalid menu options/default")
    print(prompt)
    for i, option in enumerate(options, 1):
        print(f"{i}. {option}")
    if os.name == "nt" and sys.stdin.isatty() and sys.stdout.isatty():
        import msvcrt
        selected = default
        # ponytail: line-based redraw avoids ANSI/cursor mutation; add native console rendering if needed.
        print(f"Selected: {options[selected]} (arrows, Enter, Escape)")
        while True:
            key = msvcrt.getwch()
            if key in ("\x1b", "\x03"):
                raise KeyboardInterrupt
            if key == "\r":
                return selected
            if key in ("\x00", "\xe0"):
                key = msvcrt.getwch()
                if key == "H":
                    selected = max(0, selected - 1)
                elif key == "P":
                    selected = min(len(options) - 1, selected + 1)
                print(f"Selected: {options[selected]}")
    while True:
        answer = input(f"Choice [{default + 1}] (q cancels): ").strip()
        if answer.lower() == "q" or answer == "\x1b":
            raise KeyboardInterrupt
        if not answer:
            return default
        if answer.isdecimal() and 1 <= int(answer) <= len(options):
            return int(answer) - 1


def _prompt(label: str, default: str = "") -> str:
    value = input(f"{label} [{default}] (Escape cancels): ").strip()
    if value == "\x1b":
        raise KeyboardInterrupt
    value = value or default
    if not value:
        raise ValueError(f"{label} is required")
    return value


def venv_python(root: Path) -> Path:
    return root.resolve() / ".venv" / "Scripts" / "python.exe"


def _run(root: Path, command: list[str], **kwargs):
    return subprocess.run(command, cwd=root.resolve(), check=True, **kwargs)


def validate_python(root: Path, python: Path) -> None:
    _run(root, [str(python), "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"],
         capture_output=True, text=True, timeout=30)


def install_dependencies(root: Path) -> None:
    root = root.resolve()
    python = venv_python(root)
    if not python.exists():
        if (root / ".venv").exists():
            raise RuntimeError("Incomplete .venv; repair or move it before setup")
        base = Path(sys.executable).resolve()
        validate_python(root, base)
        _run(root, [str(base), "-m", "venv", str(root / ".venv")])
    validate_python(root, python)
    uv = shutil.which("uv")
    pip = [str(python), "-m", "pip", "install", "--no-input"]
    installers = [[uv, "pip", "install", "--python", str(python)], pip] if uv else [pip]
    failures = []
    for offline in (True, False):
        for installer in installers:
            command = installer + ["-r", str(root / "requirements.txt")]
            if offline:
                command += ["--no-index", "--find-links", str(root / "packages")]
            try:
                _run(root, command)
                return
            except (OSError, subprocess.CalledProcessError) as error:
                failures.append(str(error))
    raise RuntimeError("Dependency installation failed (offline and online): " + "; ".join(failures))


def find_browser() -> Path | None:
    for name in ("chrome.exe", "msedge.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        if base := os.environ.get(variable):
            for relative in ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe"):
                candidate = Path(base) / relative
                if candidate.is_file():
                    return candidate
    return None


def ensure_browser(root: Path, silent: bool) -> None:
    if find_browser():
        return
    if silent or not shutil.which("winget"):
        raise RuntimeError("Chrome or Edge is required; install one and rerun setup")
    if select_option("No browser found. Install Edge?", ["Cancel", "Install Edge"]) == 0:
        raise KeyboardInterrupt
    _run(root, ["winget", "install", "--id", "Microsoft.Edge", "--exact"])
    if not find_browser():
        raise RuntimeError("Browser still unavailable; finish installation and rerun setup")


def scrape_tasks(root: Path, employee_id: str) -> list[dict[str, str]]:
    root = root.resolve()
    result = _run(root, [str(venv_python(root)), str(root / "src" / "scrape_tasks.py"), employee_id],
                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                  env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    payloads = [line.removeprefix("SCRAPE_RESULT:") for line in result.stdout.splitlines()
                if line.startswith("SCRAPE_RESULT:")]
    if len(payloads) != 1:
        raise ValueError("Expected one SCRAPE_RESULT")
    tasks = json.loads(payloads[0])
    if not isinstance(tasks, list) or any(
        not isinstance(task, dict) or any(
            not isinstance(task.get(key), str) or not task[key].strip()
            for key in ("task_name", "charge_type")) for task in tasks
    ):
        raise ValueError("Invalid scraper task data")
    if not tasks:
        raise ValueError("No tasks available")
    return tasks


def _select_task(tasks: list[dict[str, str]]) -> dict[str, str]:
    return tasks[select_option("Select task", [f"{t['task_name']} [{t['charge_type']}]" for t in tasks])]


def _required_config(root: Path) -> dict:
    config = load_config(root / "config.toml")
    if any(not config.get("timesheet", {}).get(key, "").strip() for key in ("task_name", "charge_type")):
        raise ValueError("Complete task configuration required")
    return config


def configure(root: Path, silent: bool = False) -> None:
    root = root.resolve()
    if silent:
        _required_config(root)
        return
    path = root / "config.toml"
    existing = load_config(path) if path.exists() else {}
    employee = _prompt("Employee ID", existing.get("employee", {}).get("EMPLOYEE_ID", ""))
    task = existing.get("timesheet", {})
    if select_option("Task source", ["Fetch available tasks", "Enter manually"]) == 0:
        try:
            task = _select_task(scrape_tasks(root, employee))
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            print(f"Task lookup failed: {error}")
            if select_option("Continue manually?", ["Cancel", "Enter manually"]) == 0:
                raise KeyboardInterrupt
        else:
            write_config(path, employee, task["task_name"], task["charge_type"])
            return
    name = _prompt("Task name", task.get("task_name", "Development"))
    charge = _prompt("Charge type", task.get("charge_type", "Billable"))
    write_config(path, employee, name, charge)


def choose_task(root: Path, silent: bool = False) -> None:
    root = root.resolve()
    if silent:
        raise ValueError("choose-task requires interactive selection")
    config = load_config(root / "config.toml")
    employee = config["employee"]["EMPLOYEE_ID"]
    task = _select_task(scrape_tasks(root, employee))
    write_config(root / "config.toml", employee, task["task_name"], task["charge_type"])
    subprocess.Popen([str(venv_python(root).with_name("pythonw.exe")),
                      str(root / "fill_timesheet.py")], cwd=root)


def register_aumid(root: Path) -> None:
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\AppUserModelId\SilentSheet") as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "SilentSheet")
        winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(root / "favicon.ico"))


def setup(root: Path, silent: bool = False) -> None:
    root = root.resolve()
    if os.name != "nt":
        raise RuntimeError("Setup requires Windows")
    if silent:
        _required_config(root)
    install_dependencies(root)
    ensure_browser(root, silent)
    register_aumid(root)
    configure(root, silent=silent)
    from . import setup_startup
    if root != setup_startup.PROJECT_DIR.resolve():
        raise ValueError("Startup module installation root mismatch")
    # Existing installations keep their mode; new interactive installs choose it.
    if setup_startup.SHORTCUT_DEST.exists():
        setup_startup.install_startup()
    else:
        status = subprocess.run(["schtasks", "/query", "/tn", setup_startup.SCHED_TASK_NAME],
                                cwd=root, capture_output=True, text=True, timeout=30)
        if status.returncode == 0 or silent:
            setup_startup.install_logon()
        elif select_option("Run automatically", ["Logon and unlock", "Startup folder"]) == 0:
            setup_startup.install_logon()
        else:
            setup_startup.install_startup()
    # ponytail: setup never submits a timesheet; runtime launch remains explicit.