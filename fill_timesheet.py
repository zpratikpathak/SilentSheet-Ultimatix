"""
Timesheet automation script using Selenium to log in via EasyAuth.

Designed to run on Windows startup. Tracks completion per day so it only
runs once. Shows a Windows toast notification with the EasyAuth number.
"""

import argparse
import logging
import socket
import subprocess
import sys
import time
import tomllib
from datetime import date
from pathlib import Path
from urllib.request import urlopen

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

import pratikpathak

# Helper modules live in src/. Make them importable without forcing the user
# to set PYTHONPATH or invoke the script as a package.
SCRIPT_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = SCRIPT_DIR / "runtime"
RUNTIME_DIR.mkdir(exist_ok=True)
LOGS_DIR = SCRIPT_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
sys.path.insert(0, str(SCRIPT_DIR / "src"))

import error_logger  # noqa: E402
from browser_session import (  # noqa: E402
    AuthenticationCancelledError,
    EasyAuthUnavailableError,
    TimesheetLoadError,
    authenticate_and_open_timesheet,
    is_transient_page,
)
from config_manager import load_config  # noqa: E402
from notification import notify, set_default_icon, dismiss  # noqa: E402
from timesheet_common import (  # noqa: E402
    CHARGE_TYPE_COLUMNS,
    DEFAULT_CHARGE_TYPE,
    DEFAULT_EFFORT,
    DEFAULT_TASK_NAME,
    NETWORK_TIMEOUT,
    is_marked,
    mark,
)

PROTOCOL_NAME = "silentsheet"

STATE_FILE = RUNTIME_DIR / ".silentsheet_state.json"
CONFIG_FILE = SCRIPT_DIR / "config.toml"
APP_ICON_FILE = SCRIPT_DIR / "favicon.ico"
set_default_icon(APP_ICON_FILE)

# Load config
_config = load_config(CONFIG_FILE)
EMPLOYEE_ID = _config["employee"]["EMPLOYEE_ID"]
TASK_NAME = _config.get("timesheet", {}).get("task_name", DEFAULT_TASK_NAME)
CHARGE_TYPE = _config.get("timesheet", {}).get("charge_type", DEFAULT_CHARGE_TYPE)

# Version check against GitHub
PYPROJECT_FILE = SCRIPT_DIR / "pyproject.toml"
with open(PYPROJECT_FILE, "rb") as _pf:
    LOCAL_VERSION = tomllib.load(_pf)["project"]["version"]
GITHUB_PYPROJECT_URL = (
    "https://raw.githubusercontent.com/"
    "zpratikpathak/SilentSheet-Ultimatix/home/pyproject.toml"
)

LOG_FILE = LOGS_DIR / "silentsheet.log"
logger = logging.getLogger("silentsheet")
logger.setLevel(logging.ERROR)
_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
_file_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
)
logger.addHandler(_file_handler)


def check_for_update() -> None:
    """Fetch the remote pyproject.toml from GitHub and notify if a newer version exists."""
    last_err = None
    for attempt in range(1, 4):
        try:
            with urlopen(GITHUB_PYPROJECT_URL, timeout=10) as resp:
                remote_config = tomllib.loads(resp.read().decode())
            remote_version = remote_config["project"]["version"]
            if remote_version != LOCAL_VERSION:
                _register_protocol()
                notify(
                    "SilentSheet Update Available",
                    f"v{LOCAL_VERSION} → v{remote_version}. "
                    "Click 'Update Now' to install.",
                    launch=f"{PROTOCOL_NAME}:update",
                    action_label="Update Now",
                    action_launch=f"{PROTOCOL_NAME}:update",
                    duration="long",
                )
                print(f"Update available: v{LOCAL_VERSION} -> v{remote_version}")
                time.sleep(25)
            return
        except Exception as e:
            last_err = e
            if attempt < 3:
                print(
                    f"Version check attempt {attempt}/3 failed: {e}. Retrying in {5 * attempt}s..."
                )
                time.sleep(5 * attempt)
    logger.error("Version check failed: %s", last_err)
    print(f"Version check skipped: {last_err}")


def already_done_today() -> bool:
    """Return True if the timesheet was already filled today."""
    return is_marked(STATE_FILE, "last_filled")


def already_notified_today() -> bool:
    """Return True if the 'already filled' notification was shown today."""
    return is_marked(STATE_FILE, "last_notified")


def mark_done_today() -> None:
    """Record today as the last successful fill date."""
    mark(STATE_FILE, "last_filled")


def mark_notified_today() -> None:
    """Record that the 'already filled' notification was shown today."""
    mark(STATE_FILE, "last_notified")


def wait_for_internet() -> bool:
    """Block until internet is available, or timeout."""
    interval = 5
    elapsed = 0
    while elapsed < NETWORK_TIMEOUT:
        try:
            socket.create_connection(("dns.google", 443), timeout=3).close()
            return True
        except OSError:
            time.sleep(interval)
            elapsed += interval
    return False


def _register_protocol() -> None:
    """Register the silentsheet: URL protocol so toast action buttons work.

    Windows toast notifications use activationType="protocol". The file:///
    scheme is silently blocked for script files (.vbs/.bat/.ps1) on
    Windows 10/11. A custom registered protocol avoids this restriction.
    """
    if winreg is None:
        return
    python_exe = Path(sys.executable)
    pythonw_exe = python_exe.parent / "pythonw.exe"
    if not pythonw_exe.exists():
        pythonw_exe = python_exe
    script_path = SCRIPT_DIR / "fill_timesheet.py"
    command = f'"{pythonw_exe}" "{script_path}" "%1"'
    try:
        reg = winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER)
        key_path = f"SOFTWARE\\Classes\\{PROTOCOL_NAME}"
        key = winreg.CreateKey(reg, key_path)
        with key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f"URL:{PROTOCOL_NAME}")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
            subkey = winreg.CreateKey(key, r"shell\open\command")
            with subkey:
                winreg.SetValueEx(subkey, "", 0, winreg.REG_SZ, command)
    except OSError:
        pass


def _handle_mark_done(mark_date: str | None) -> None:
    """Validate the date and mark today as done, or show an expiry notice."""
    if mark_date != str(date.today()):
        notify(
            "Timesheet",
            "This notification has expired. It was from a previous day.",
            duration="short",
        )
        print(f"Stale mark-done request (date={mark_date}). Ignoring.")
        return
    mark_done_today()
    mark_notified_today()
    notify("Timesheet", "Marked as done for today. Won't run again.", duration="short")
    print("Marked today as done via notification button.")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fill today's Ultimatix timesheet")
    parser.add_argument("action", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument(
        "--visible", action="store_true", help="show the browser window"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    # Handle protocol-launched mark-done requests (silentsheet:markdone-YYYY-MM-DD)
    if args.action and args.action.startswith(f"{PROTOCOL_NAME}:"):
        action = args.action.split(":", 1)[1]
        if action.startswith("markdone-"):
            _handle_mark_done(action[len("markdone-") :])
        elif action == "choosetask":
            # Launch the PowerShell task picker in a visible console window so
            # the user gets arrow-key navigation. -ExecutionPolicy Bypass
            # ensures it runs even if the user has the default Restricted
            # CurrentUser policy.
            choose_ps1 = SCRIPT_DIR / "src" / "choose_task.ps1"
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(choose_ps1),
                ],
                cwd=str(SCRIPT_DIR),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        elif action == "update":
            setup_ps1 = SCRIPT_DIR / "setup.ps1"
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(setup_ps1),
                    "-Update",
                    "-Silent",
                ],
                cwd=str(SCRIPT_DIR),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        return

    if args.action:
        raise SystemExit(f"Unknown action: {args.action}")

    pratikpathak.main()
    headless = not args.visible

    # Wait for internet connectivity (ethernet may not be plugged in yet)
    print("Waiting for internet...")
    if not wait_for_internet():
        error_logger.write_report("Waiting for internet")
        notify(
            "SilentSheet",
            "Couldn't connect to the internet. SilentSheet will try again on the next login.",
            duration="short",
        )
        return
    print("Internet available.")
    time.sleep(5)  # brief pause to ensure stable connection

    check_for_update()

    # Skip if already filled today
    if already_done_today():
        print("Timesheet already filled today. Exiting.")
        if not already_notified_today():
            notify("Timesheet", "Already filled for today. No action needed.")
            mark_notified_today()
        return

    session = None
    driver = None
    approved_toast = None
    try:
        _register_protocol()
        mark_done_launch = f"{PROTOCOL_NAME}:markdone-{date.today()}"
        session = authenticate_and_open_timesheet(
            EMPLOYEE_ID,
            headless=headless,
            approval_timeout=65,
            logger=logger,
            notification_action=("Mark as Done", mark_done_launch),
            stop_requested=already_done_today,
            show_approved_toast=True,
        )
        driver = session.driver
        wait = session.wait
        approved_toast = session.approved_toast

        # Step 7: Wait for the timesheet page to load and fill effort hours
        print("Waiting for timesheet page to load...")

        column_idx = CHARGE_TYPE_COLUMNS.get(
            CHARGE_TYPE, CHARGE_TYPE_COLUMNS[DEFAULT_CHARGE_TYPE]
        )

        # Search both Assigned and Unassigned task sections for the
        # configured task name and charge type column.
        def find_task_effort_input(d):
            for prefix, section in (
                ("effortAssign", "Assigned"),
                ("effortUnassign", "Unassigned"),
            ):
                xpath = (
                    f"//tr[.//span[contains(@class, 'taskNameFont') and "
                    f"contains(normalize-space(text()), '{TASK_NAME}')]]"
                    f"/td[{column_idx}]//input[contains(@id, '{prefix}')]"
                )
                for el in d.find_elements(By.XPATH, xpath):
                    if el.is_displayed():
                        print(
                            f"Found '{TASK_NAME}' in {section} Task section, charge type '{CHARGE_TYPE}'"
                        )
                        return el
            return False

        try:
            effort_input = wait.until(find_task_effort_input)
        except Exception:
            # If a transient error page rendered after our initial check, treat
            # it as a load failure rather than a missing task.
            if is_transient_page(driver):
                logger.error(
                    "Timesheet error page detected while looking for task. URL=%s, title=%s",
                    driver.current_url,
                    driver.title,
                )
                error_logger.write_report("Loading timesheet page", driver=driver)
                dismiss(approved_toast)
                notify(
                    "SilentSheet",
                    "The timesheet didn't load properly. Please try again later.",
                    duration="short",
                )
                return

            # Task not found — notify user and offer interactive task chooser
            print(f"Task '{TASK_NAME}' / '{CHARGE_TYPE}' not found on the timesheet.")
            dismiss(approved_toast)
            _register_protocol()
            choose_launch = f"{PROTOCOL_NAME}:choosetask"
            notify(
                "Timesheet - Task Not Found",
                f"'{TASK_NAME}' [{CHARGE_TYPE}] is not on the timesheet. Click to update the task.",
                launch=choose_launch,
                action_label="Update Task",
                action_launch=choose_launch,
            )
            print("Notification sent. User can click to choose a task.")
            return

        # Check current value before filling
        current_value = effort_input.get_attribute("value").strip()
        if current_value == DEFAULT_EFFORT:
            print(f"Effort already set to {DEFAULT_EFFORT} hours. Skipping.")
            mark_done_today()
            mark_notified_today()
            dismiss(approved_toast)
            notify(
                "Timesheet",
                f"Already had {DEFAULT_EFFORT} hours. Marked as done.",
                duration="short",
            )
        else:
            print(
                f"Current effort: '{current_value}'. Filling {DEFAULT_EFFORT} hours..."
            )
            effort_input.clear()
            effort_input.send_keys(DEFAULT_EFFORT)
            # Click elsewhere to trigger ng-blur so Angular picks up the change.
            # Use JS blur instead of a specific element id, since that id is
            # not guaranteed to be stable across page updates.
            driver.execute_script(
                "if (document.activeElement) document.activeElement.blur();"
            )
            time.sleep(1)

            # Step 8: Click Submit
            print("Clicking Submit...")
            submit_button = wait.until(EC.element_to_be_clickable((By.ID, "submit")))
            submit_button.click()
            print("Timesheet submitted! Verifying...")
            time.sleep(3)

            driver.refresh()
            verified_input = wait.until(find_task_effort_input)
            verified_value = verified_input.get_attribute("value").strip()
            dismiss(approved_toast)
            if verified_value == DEFAULT_EFFORT:
                print(f"Verification passed: {DEFAULT_EFFORT} hours confirmed.")
                mark_done_today()
                mark_notified_today()
                notify(
                    "Timesheet",
                    f"Filled {DEFAULT_EFFORT} hours successfully!",
                    duration="short",
                )
            else:
                logger.error(
                    "Verification failed: expected '%s', got '%s'",
                    DEFAULT_EFFORT,
                    verified_value,
                )
                print(
                    f"Verification failed: expected '{DEFAULT_EFFORT}', got '{verified_value}'"
                )
                error_logger.write_report(
                    "Verifying timesheet hours",
                    driver=driver,
                    extra={"expected": DEFAULT_EFFORT, "found": verified_value},
                )
                notify(
                    "SilentSheet",
                    "Saved the timesheet, but the hours don't look right. "
                    "Please open it to double-check.",
                    duration="short",
                )

        time.sleep(3)

    except AuthenticationCancelledError:
        print("Marked as done via notification button. Exiting.")
    except Exception as e:
        logger.exception("Timesheet automation failed")
        print(f"Error: {e}", file=sys.stderr)

        if isinstance(e, EasyAuthUnavailableError):
            error_logger.write_report("EasyAuth button missing", exc=e, driver=driver)
            notify(
                "SilentSheet",
                "EasyAuth button is missing today. Please fill the timesheet "
                "manually today.",
                duration="short",
            )
        elif isinstance(e, TimesheetLoadError):
            notify(
                "SilentSheet",
                "The timesheet page wouldn't load after several tries. Please try again later.",
                duration="short",
            )
        elif isinstance(e, TimeoutError) and "timed out" in str(e).lower():
            error_logger.write_report("EasyAuth approval", exc=e, driver=driver)

            startup_dir = (
                Path.home()
                / r"AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup"
            )
            startup_vbs = startup_dir / "launch_silentsheet.vbs"
            project_vbs = RUNTIME_DIR / "silentsheet_launcher.vbs"
            retry_vbs = RUNTIME_DIR / "silentsheet_retry.vbs"

            if startup_vbs.exists():
                vbs_to_launch = startup_vbs
            elif project_vbs.exists():
                vbs_to_launch = project_vbs
            else:
                vbs_to_launch = retry_vbs
                python_exe = SCRIPT_DIR / ".venv" / "Scripts" / "pythonw.exe"
                script_path = SCRIPT_DIR / "fill_timesheet.py"
                vbs_content = (
                    'Set WshShell = CreateObject("WScript.Shell")\n'
                    f'WshShell.CurrentDirectory = "{SCRIPT_DIR}"\n'
                    f'WshShell.Run chr(34) & "{python_exe}" & chr(34) & " " & chr(34) & "{script_path}" & chr(34), 0, False\n'
                )
                vbs_to_launch.write_text(vbs_content)

            notify(
                "SilentSheet",
                "EasyAuth request timed out. Click Retry to try again.",
                action_label="Retry",
                action_launch=f"file:///{vbs_to_launch.as_posix()}",
            )
        else:
            error_logger.write_report("Filling timesheet", exc=e, driver=driver)
            notify(
                "SilentSheet",
                "Something went wrong while filling your timesheet. "
                "A diagnostic report was saved to the logs folder.",
                duration="short",
            )

        if not headless:
            input("Press Enter to close the browser...")
    finally:
        if session is not None:
            session.close()


if __name__ == "__main__":
    main()
