"""
Timesheet automation script using Selenium to log in via EasyAuth.

Designed to run on Windows startup. Tracks completion per day so it only
runs once. Shows a Windows toast notification with the EasyAuth number.
"""

import json
import logging
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
from datetime import date
from pathlib import Path
from urllib.request import urlopen

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None

from PIL import Image, ImageDraw, ImageFont
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

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
from notification import notify, set_default_icon, dismiss, dismiss_all  # noqa: E402

PROTOCOL_NAME = "silentsheet"


def _is_protocol_launch() -> bool:
    """Check if the script was launched via the silentsheet: URL protocol."""
    return len(sys.argv) > 1 and sys.argv[1].startswith(f"{PROTOCOL_NAME}:")


# Defer heavy side effects so lightweight flags like --mark-done-today stay fast.
if "--mark-done-today" not in sys.argv and not _is_protocol_launch():
    pratikpathak.main()

TIMESHEET_URL = "https://timesheet.ultimatix.net/timesheet/"
PORTAL_URL = "https://www.ultimatix.net/uxportal/uxportalhome.html/Megamenu"
WAIT_TIMEOUT = 30  # seconds to wait for elements

STATE_FILE = RUNTIME_DIR / ".silentsheet_state.json"
CONFIG_FILE = SCRIPT_DIR / "config.toml"
APP_ICON_FILE = SCRIPT_DIR / "favicon.ico"
set_default_icon(APP_ICON_FILE)

# Load config
with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
    _config = tomllib.loads(f.read())
EMPLOYEE_ID = _config["employee"]["EMPLOYEE_ID"]
TASK_NAME = _config.get("timesheet", {}).get("task_name", "Development")
CHARGE_TYPE = _config.get("timesheet", {}).get("charge_type", "Billable")

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


def _load_state() -> dict:
    """Load persisted state from the JSON file."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_state(state: dict) -> None:
    """Write state dict to the JSON file."""
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def already_done_today() -> bool:
    """Return True if the timesheet was already filled today."""
    return _load_state().get("last_filled") == str(date.today())


def already_notified_today() -> bool:
    """Return True if the 'already filled' notification was shown today."""
    return _load_state().get("last_notified") == str(date.today())


def mark_done_today() -> None:
    """Record today as the last successful fill date."""
    state = _load_state()
    state["last_filled"] = str(date.today())
    _save_state(state)


def mark_notified_today() -> None:
    """Record that the 'already filled' notification was shown today."""
    state = _load_state()
    state["last_notified"] = str(date.today())
    _save_state(state)


NETWORK_TIMEOUT = 600  # max seconds to wait for internet (10 minutes)


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


def is_dark_mode_enabled() -> bool:
    """Return True if Windows apps theme is set to dark mode."""
    if winreg is None:
        return False

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            apps_use_light_theme, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return apps_use_light_theme == 0
    except OSError:
        return False


def create_auth_number_image(auth_number: str) -> Path:
    """Create an EasyAuth number icon that adapts to light/dark Windows theme."""
    image_path = Path(tempfile.gettempdir()) / f"silentsheet_easyauth_{auth_number}.png"
    size = 512
    image = Image.new(
        "RGB", (size, size), "#000000" if is_dark_mode_enabled() else "#FFFFFF"
    )
    draw = ImageDraw.Draw(image)

    if is_dark_mode_enabled():
        card_color = "#1E1E1E"
        border_color = "#3A3A3A"
        text_color = "#F4F4F4"
    else:
        card_color = "#F5F7FA"
        border_color = "#D5DBE3"
        text_color = "#111827"

    margin = 22
    corner_radius = 42
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=corner_radius,
        fill=card_color,
        outline=border_color,
        width=4,
    )

    text = " ".join(str(auth_number))
    font_candidates = [
        Path("C:/Windows/Fonts/seguisb.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/tahomabd.ttf"),
    ]

    font = ImageFont.load_default()
    for font_size in range(300, 60, -8):
        loaded_font = None
        for candidate in font_candidates:
            if candidate.exists():
                loaded_font = ImageFont.truetype(str(candidate), font_size)
                break
        if loaded_font is None:
            break

        left, top, right, bottom = draw.textbbox((0, 0), text, font=loaded_font)
        text_width = right - left
        text_height = bottom - top
        if text_width <= int(size * 0.78) and text_height <= int(size * 0.50):
            font = loaded_font
            break

    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    text_width = right - left
    text_height = bottom - top
    x = (size - text_width) // 2 - left
    y = (size - text_height) // 2 - top

    draw.text((x, y), text, fill=text_color, font=font)
    image.save(image_path)
    return image_path


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


def _mark_done_vbs() -> Path:
    """Return the path to a VBS script that marks today as done (created on demand)."""
    vbs_path = RUNTIME_DIR / "silentsheet_markdone.vbs"
    python_exe = Path(sys.executable)
    pythonw_exe = python_exe.parent / "pythonw.exe"
    if not pythonw_exe.exists():
        pythonw_exe = python_exe
    script_path = SCRIPT_DIR / "fill_timesheet.py"
    today_str = str(date.today())
    vbs_content = (
        'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.CurrentDirectory = "{SCRIPT_DIR}"\n'
        f'WshShell.Run chr(34) & "{pythonw_exe}" & chr(34) & " " & chr(34) & "{script_path}" & chr(34) & " --mark-done-today {today_str}", 0, False\n'
    )
    vbs_path.write_text(vbs_content)
    return vbs_path


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


def main() -> None:
    # Handle protocol-launched mark-done requests (silentsheet:markdone-YYYY-MM-DD)
    if _is_protocol_launch():
        action = sys.argv[1].split(":", 1)[1]
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

    # Invoked by the "Mark as Done" toast button (legacy VBS path).
    if "--mark-done-today" in sys.argv:
        idx = sys.argv.index("--mark-done-today")
        mark_date = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        _handle_mark_done(mark_date)
        return

    headless = "--head" not in sys.argv

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

    # Set up Chrome browser
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
    else:
        chrome_options.add_argument("--start-maximized")

    # Hide automation indicators to avoid bot detection
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=chrome_options)

    # Override the user-agent so headless Chrome does not expose "HeadlessChrome",
    # which Ultimatix detects and rejects with a "network fluctuations" error
    # right after EasyAuth approval. Derive it from the real UA to stay in sync
    # with the installed Chrome version.
    try:
        real_ua = driver.execute_script("return navigator.userAgent")
        clean_ua = real_ua.replace("HeadlessChrome", "Chrome")
        driver.execute_cdp_cmd(
            "Network.setUserAgentOverride", {"userAgent": clean_ua}
        )
    except Exception as ua_err:
        logger.error("Could not override user-agent: %s", ua_err)

    # Remove navigator.webdriver flag
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )
    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    try:
        # Step 1: Open the Ultimatix portal home (retry on transient network
        # errors). Authenticating against the portal first, then navigating to
        # the timesheet, mirrors normal user behaviour and avoids the
        # post-EasyAuth "network fluctuations" rejection.
        print(f"Opening {PORTAL_URL} ...")
        max_retries = 5
        for attempt in range(1, max_retries + 1):
            try:
                driver.get(PORTAL_URL)
                break
            except Exception as nav_err:
                err_msg = str(nav_err)
                if attempt < max_retries and (
                    "net::ERR_CONNECTION_RESET" in err_msg
                    or "net::ERR_INTERNET_DISCONNECTED" in err_msg
                    or "net::ERR_NAME_NOT_RESOLVED" in err_msg
                    or "net::ERR_CONNECTION_REFUSED" in err_msg
                    or "net::ERR_CONNECTION_TIMED_OUT" in err_msg
                    or "net::ERR_NETWORK_CHANGED" in err_msg
                ):
                    wait_secs = 5 * attempt
                    print(
                        f"Connection error (attempt {attempt}/{max_retries}): "
                        f"{err_msg.splitlines()[0]}. Retrying in {wait_secs}s..."
                    )
                    time.sleep(wait_secs)
                else:
                    raise

        # Step 2: Wait for redirect to login page and find the username input
        # The auth redirect chain (SiteMinder → SAML → Ultimatix) can be slow,
        # especially right after boot. The server may also return an error page
        # on the first load that resolves after a refresh.
        print("Waiting for login page...")
        print(f"Current URL after navigation: {driver.current_url}")
        username_input = None
        login_attempts = 3
        for login_attempt in range(1, login_attempts + 1):
            try:
                login_wait = WebDriverWait(driver, WAIT_TIMEOUT)
                username_input = login_wait.until(
                    EC.presence_of_element_located((By.ID, "form1"))
                )
                break
            except TimeoutException:
                page_title = driver.title.lower()
                page_source_snippet = driver.page_source[:2000].lower()
                is_error_page = any(
                    marker in page_title or marker in page_source_snippet
                    for marker in (
                        "not working",
                        "error",
                        "502",
                        "503",
                        "504",
                        "bad gateway",
                        "service unavailable",
                        "this site can",
                        "err_",
                        "timed out",
                    )
                )
                if is_error_page and login_attempt < login_attempts:
                    print(
                        f"Page failed to load (attempt {login_attempt}/{login_attempts}): "
                        f"title='{driver.title}'. Refreshing..."
                    )
                    driver.refresh()
                    time.sleep(3)
                    continue
                # Final attempt failed — capture a diagnostic report and re-raise
                # so the outer except clause can show a friendly toast.
                logger.error(
                    "Timed out waiting for #form1. URL=%s, title=%s",
                    driver.current_url,
                    driver.title,
                )
                error_logger.write_report("Loading login page", driver=driver)
                raise

        # Step 3: Type the employee ID
        print(f"Entering employee ID: {EMPLOYEE_ID}")
        username_input.clear()
        username_input.send_keys(EMPLOYEE_ID)

        # Step 4: Click the Proceed button
        print("Clicking Proceed...")
        proceed_button = wait.until(
            EC.element_to_be_clickable((By.ID, "proceed-button"))
        )
        proceed_button.click()

        # Step 5: Wait for redirect and click EasyAuth button
        print("Waiting for EasyAuth button...")
        easyauth_button = wait.until(
            EC.element_to_be_clickable((By.ID, "easyAuth-btn"))
        )
        easyauth_button.click()

        # Step 6: Get the authentication number (wait until digits text is non-empty)
        print("Waiting for authentication number...")

        def digits_have_text(driver):
            el = driver.find_element(By.CSS_SELECTOR, "#number .digits")
            text = el.text.strip()
            return el if text else False

        digits_element = wait.until(digits_have_text)
        auth_number = digits_element.text.strip()
        print(f"\n{'=' * 40}")
        print(f"  EasyAuth Number: {auth_number}")
        print(f"{'=' * 40}\n")

        # Use app icon when available, otherwise fall back to EasyAuth number image.
        auth_image_path = None
        if not APP_ICON_FILE.exists():
            try:
                auth_image_path = create_auth_number_image(auth_number)
            except Exception as image_error:
                logger.error("Could not create EasyAuth image: %s", image_error)
                print(f"Warning: Could not create EasyAuth image: {image_error}")

        _register_protocol()
        mark_done_launch = f"{PROTOCOL_NAME}:markdone-{date.today()}"

        easyauth_toast = notify(
            f"EasyAuth: {auth_number}",
            "Tap this number on your Authenticator app to approve.",
            image_path=auth_image_path,
            action_label="Mark as Done",
            action_launch=mark_done_launch,
        )

        # Wait for the user to approve on their device and the page to proceed
        print("Waiting for authentication to complete...")
        auth_start_url = driver.current_url
        auth_timeout = 65  # seconds to approve
        auth_start = time.time()
        last_notify_time = auth_start  # track when we last showed the notification
        while time.time() - auth_start < auth_timeout:
            if already_done_today():
                dismiss(easyauth_toast)
                print("Marked as done via notification button. Exiting.")
                return
            if driver.current_url != auth_start_url:
                break
            # Re-show the notification every 25 seconds if still waiting
            if time.time() - last_notify_time >= 25:
                easyauth_toast = notify(
                    f"EasyAuth: {auth_number}",
                    "Tap this number on your Authenticator app to approve.",
                    image_path=auth_image_path,
                    action_label="Mark as Done",
                    action_launch=mark_done_launch,
                )
                last_notify_time = time.time()
            time.sleep(1)
        else:
            dismiss(easyauth_toast)
            raise TimeoutError("EasyAuth request timed out waiting for approval.")

        # Give the post-approval SAML redirect chain time to settle before
        # inspecting the page or navigating onward.
        time.sleep(5)

        # Check if we landed on the timeout error page
        try:
            timeout_div = driver.find_elements(By.ID, "timeout")
            if timeout_div and timeout_div[0].is_displayed():
                dismiss(easyauth_toast)
                raise TimeoutError("EasyAuth request timed out.")
        except Exception as e:
            if isinstance(e, TimeoutError):
                raise
            pass

        dismiss(easyauth_toast)
        approved_toast = notify(
            "EasyAuth Approved",
            "Authentication successful! Filling timesheet...",
            duration="short",
        )
        print("Authentication successful! Redirected to:", driver.current_url)

        # Now that the portal session is established, navigate to the timesheet.
        # The timesheet backend occasionally returns a transient error page
        # (WebLogic bridge failure, ERR_NETWORK_CHANGED, etc.) instead of the
        # actual app. Detect those and retry rather than mistaking them for a
        # missing task.
        def is_timesheet_error_page() -> bool:
            haystack = f"{driver.title}\n{driver.page_source[:3000]}".lower()
            markers = (
                "weblogic bridge message",
                "failure of web server bridge",
                "no backend server available",
                "your connection was interrupted",
                "a network change was detected",
                "err_network_changed",
                "err_connection",
                "err_timed_out",
                "err_empty_response",
                "502",
                "503",
                "504",
                "bad gateway",
                "service unavailable",
                "gateway time-out",
            )
            return any(marker in haystack for marker in markers)

        timesheet_load_retries = 5
        for ts_attempt in range(1, timesheet_load_retries + 1):
            print(
                f"Opening timesheet at {TIMESHEET_URL} "
                f"(attempt {ts_attempt}/{timesheet_load_retries}) ..."
            )
            try:
                driver.get(TIMESHEET_URL)
            except Exception as nav_err:
                print(f"Timesheet navigation error: {str(nav_err).splitlines()[0]}")
            time.sleep(3)

            if not is_timesheet_error_page():
                break

            print("Timesheet returned a transient error page.")
            if ts_attempt < timesheet_load_retries:
                dismiss(approved_toast)
                approved_toast = notify(
                    "Timesheet",
                    "The timesheet didn't load properly. Trying again...",
                    duration="short",
                )
                time.sleep(5 * ts_attempt)
            else:
                logger.error(
                    "Timesheet failed to load after %d attempts. URL=%s, title=%s",
                    timesheet_load_retries,
                    driver.current_url,
                    driver.title,
                )
                error_logger.write_report("Loading timesheet page", driver=driver)
                dismiss(approved_toast)
                notify(
                    "SilentSheet",
                    "The timesheet page wouldn't load after several tries. "
                    "Please try again later.",
                    duration="short",
                )
                driver.quit()
                return

        # Step 7: Wait for the timesheet page to load and fill effort hours
        print("Waiting for timesheet page to load...")

        column_idx = {
            "Billable": 2,
            "Non Billable": 3,
            "Over Time": 4,
            "Weekend Overtime": 5,
            "Morning Shift": 6,
            "Night Shift": 7,
            "Evening Shift": 8,
            "On Call": 9,
        }.get(CHARGE_TYPE, 2)

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
            if is_timesheet_error_page():
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
                driver.quit()
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
            driver.quit()
            return

        # Check current value before filling
        current_value = effort_input.get_attribute("value").strip()
        if current_value == "9":
            print("Effort already set to 9 hours. Skipping.")
            mark_done_today()
            mark_notified_today()
            dismiss(approved_toast)
            notify(
                "Timesheet", "Already had 9 hours. Marked as done.", duration="short"
            )
        else:
            print(f"Current effort: '{current_value}'. Filling 9 hours...")
            effort_input.clear()
            effort_input.send_keys("9")
            # Click elsewhere to trigger ng-blur so Angular picks up the change
            driver.find_element(By.ID, "tsMainBody").click()
            time.sleep(1)

            # Step 8: Click Submit
            print("Clicking Submit...")
            submit_button = wait.until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "input.buttonClass[value='Submit']")
                )
            )
            submit_button.click()
            print("Timesheet submitted! Verifying...")
            time.sleep(3)

            driver.refresh()
            verified_input = wait.until(find_task_effort_input)
            verified_value = verified_input.get_attribute("value").strip()
            dismiss(approved_toast)
            if verified_value == "9":
                print("Verification passed: 9 hours confirmed.")
                mark_done_today()
                mark_notified_today()
                notify("Timesheet", "Filled 9 hours successfully!", duration="short")
            else:
                logger.error(
                    "Verification failed: expected '9', got '%s'", verified_value
                )
                print(f"Verification failed: expected '9', got '{verified_value}'")
                error_logger.write_report(
                    "Verifying timesheet hours",
                    driver=driver,
                    extra={"expected": "9", "found": verified_value},
                )
                notify(
                    "SilentSheet",
                    "Saved the timesheet, but the hours don't look right. "
                    "Please open it to double-check.",
                    duration="short",
                )

        time.sleep(3)

    except Exception as e:
        logger.exception("Timesheet automation failed")
        print(f"Error: {e}", file=sys.stderr)

        if isinstance(e, TimeoutError) and "timed out" in str(e).lower():
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
                    f'WshShell.Run chr(34) & "{python_exe}" & chr(34) & " " & chr(34) & "{script_path}" & chr(34) & " --headless", 0, False\n'
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
        driver.quit()


if __name__ == "__main__":
    main()
