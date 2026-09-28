"""Side-effect-free constants and state helpers shared by SilentSheet workflows."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

PORTAL_URL = "https://www.ultimatix.net/uxportal/uxportalhome.html/Megamenu"
TIMESHEET_URL = "https://timesheet.ultimatix.net/timesheet/"
WAIT_TIMEOUT = 30
NETWORK_TIMEOUT = 600
NAVIGATION_RETRIES = 5
TIMESHEET_LOAD_RETRIES = 5

DEFAULT_TASK_NAME = "Development"
DEFAULT_CHARGE_TYPE = "Billable"
DEFAULT_EFFORT = "9"

CHARGE_TYPE_COLUMNS = {
    "Billable": 2,
    "Non Billable": 3,
    "Over Time": 4,
    "Weekend Overtime": 5,
    "Morning Shift": 6,
    "Night Shift": 7,
    "Evening Shift": 8,
    "On Call": 9,
}


def read_daily_state(path: Path) -> dict[str, str]:
    """Read daily state, treating missing, invalid, or unreadable files as empty."""
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return state if isinstance(state, dict) else {}


def is_marked(path: Path, key: str, today: date | None = None) -> bool:
    """Return whether *key* is marked with the supplied date (today by default)."""
    current_date = today or date.today()
    return read_daily_state(path).get(key) == str(current_date)


def mark(path: Path, key: str, today: date | None = None) -> None:
    """Set *key* to the supplied date while preserving other state values."""
    current_date = today or date.today()
    state = read_daily_state(path)
    state[key] = str(current_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")
