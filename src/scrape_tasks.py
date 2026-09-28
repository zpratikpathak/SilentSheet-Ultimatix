"""Authenticate headlessly and emit available timesheet tasks as structured JSON.

Usage:
    python scrape_tasks.py <employee_id>
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

import error_logger
from browser_session import authenticate_and_open_timesheet, is_transient_page
from notification import notify, set_default_icon
from timesheet_common import CHARGE_TYPE_COLUMNS

PROJECT_DIR = Path(__file__).resolve().parent.parent
set_default_icon(PROJECT_DIR / "favicon.ico")


def scrape_tasks(driver, wait) -> list[dict[str, str]]:
    """Read visible task/charge combinations from the current timesheet page."""
    try:
        wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "span.taskNameFont"))
        )
    except TimeoutException:
        if is_transient_page(driver):
            raise RuntimeError("Timesheet returned a transient error page")
        raise
    time.sleep(2)

    tasks: list[dict[str, str]] = []
    for prefix in ("effortAssign", "effortUnassign"):
        rows = driver.find_elements(
            By.XPATH,
            f"//tr[.//span[contains(@class, 'taskNameFont')]]"
            f"[.//input[contains(@id, '{prefix}')]]",
        )
        for row in rows:
            try:
                task_name = row.find_element(
                    By.CSS_SELECTOR, "span.taskNameFont"
                ).text.strip()
            except Exception:
                continue
            if not task_name:
                continue
            for charge_type, column_index in CHARGE_TYPE_COLUMNS.items():
                inputs = row.find_elements(
                    By.XPATH,
                    f"td[{column_index}]//input[contains(@id, '{prefix}')]",
                )
                if any(element.is_displayed() for element in inputs):
                    entry = {"task_name": task_name, "charge_type": charge_type}
                    if entry not in tasks:
                        tasks.append(entry)
    return tasks


def format_scrape_result(tasks: list[dict[str, str]]) -> str:
    return f"SCRAPE_RESULT:{json.dumps(tasks)}"


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    tasks: list[dict[str, str]] = []
    session = None
    status = 0
    try:
        if len(arguments) != 1 or arguments[0].startswith("-"):
            print("Usage: python scrape_tasks.py <employee_id>", file=sys.stderr)
            return 2
        session = authenticate_and_open_timesheet(
            arguments[0],
            headless=True,
            approval_timeout=120,
            error_context="Waiting for EasyAuth approval (task list)",
        )
        tasks = scrape_tasks(session.driver, session.wait)
        print(f"Found {len(tasks)} task(s).")
    except Exception as error:
        status = 1
        print(f"Error: {error}", file=sys.stderr)
        error_logger.write_report(
            "Fetching task list",
            exc=error,
            driver=session.driver if session else None,
        )
        notify(
            "SilentSheet",
            "Couldn't load the task list right now. A diagnostic report was saved to the logs folder.",
        )
    finally:
        if session is not None:
            session.close()
        print(format_scrape_result(tasks))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
