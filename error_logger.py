"""Per-incident diagnostic report writer.

Used by ``fill_timesheet.py`` and ``scrape_tasks.py`` to capture a screenshot
plus an error markdown file under ``logs/`` whenever something goes wrong.
The user-facing toast notifications stay short and friendly; the technical
detail lives here.
"""

from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
LOGS_DIR = SCRIPT_DIR / "logs"


def _ensure_logs_dir() -> Path:
    LOGS_DIR.mkdir(exist_ok=True)
    return LOGS_DIR


def _safe_get(driver: Any, attr: str) -> str:
    """Best-effort access to a WebDriver attribute, swallowing any errors."""
    try:
        value = getattr(driver, attr)
        return str(value) if value is not None else ""
    except Exception:
        return ""


def write_report(
    context: str,
    exc: BaseException | None = None,
    driver: Any | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write a diagnostic markdown file (and screenshot) describing a failure.

    Parameters
    ----------
    context:
        Short human-readable label describing what was being attempted,
        e.g. ``"Filling timesheet"``.
    exc:
        Optional exception to record. Class name, message and traceback
        are included when provided.
    driver:
        Optional Selenium WebDriver. When alive, a PNG screenshot is saved
        next to the markdown file and the page URL/title are recorded.
    extra:
        Optional key/value pairs to include verbatim in an "Extra" section.

    Returns
    -------
    Path
        The path of the markdown report that was written.
    """
    logs_dir = _ensure_logs_dir()
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    md_path = logs_dir / f"{ts}_error.md"
    screenshot_path: Path | None = None
    page_url = ""
    page_title = ""

    if driver is not None:
        page_url = _safe_get(driver, "current_url")
        page_title = _safe_get(driver, "title")
        try:
            candidate = logs_dir / f"{ts}_screenshot.png"
            if driver.save_screenshot(str(candidate)):
                screenshot_path = candidate
        except Exception:
            screenshot_path = None

    lines: list[str] = []
    lines.append("# SilentSheet error report")
    lines.append("")
    lines.append(f"**When:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Where:** {context}")
    lines.append("")

    if page_url or page_title:
        lines.append("## Page")
        lines.append("")
        if page_url:
            lines.append(f"- **URL:** {page_url}")
        if page_title:
            lines.append(f"- **Title:** {page_title}")
        lines.append("")

    if screenshot_path is not None:
        lines.append("## Screenshot")
        lines.append("")
        lines.append(f"![screenshot](./{screenshot_path.name})")
        lines.append("")

    if exc is not None:
        lines.append("## Error")
        lines.append("")
        lines.append(f"- **Type:** `{type(exc).__name__}`")
        lines.append(f"- **Message:** {exc}")
        lines.append("")
        lines.append("## Traceback")
        lines.append("")
        lines.append("```text")
        lines.extend(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            .rstrip()
            .splitlines()
        )
        lines.append("```")
        lines.append("")

    if extra:
        lines.append("## Extra")
        lines.append("")
        lines.append("| Key | Value |")
        lines.append("| --- | --- |")
        for key, value in extra.items():
            lines.append(f"| {key} | {value} |")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path
