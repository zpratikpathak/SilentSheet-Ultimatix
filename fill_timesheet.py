"""Timesheet automation script using Selenium to log in via EasyAuth.

Designed to run on Windows startup. Tracks completion per day so it only
runs once. Shows a Windows toast notification with the EasyAuth number.
"""

import json
import logging
import socket
import sys
import tempfile
import time
import tomllib
from datetime import date, datetime
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
from winotify import Notification

import pratikpathak

pratikpathak.main()

TIMESHEET_URL = "https://timesheet.ultimatix.net/timesheet/"
WAIT_TIMEOUT = 30  # seconds to wait for elements

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / ".silentsheet_state.json"
CONFIG_FILE = SCRIPT_DIR / "config.toml"
APP_ICON_FILE = SCRIPT_DIR / "favicon.ico"

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

LOG_FILE = SCRIPT_DIR / "silentsheet.log"
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
                notify(
                    "SilentSheet Update Available",
                    f"v{LOCAL_VERSION} → v{remote_version}. " "Click to open GitHub.",
                    launch="https://github.com/zpratikpathak/SilentSheet-Ultimatix?tab=readme-ov-file#updating",
                    duration="short",
                )
                print(f"Update available: v{LOCAL_VERSION} -> v{remote_version}")
                time.sleep(7)
            return
        except Exception as e:
            last_err = e
            if attempt < 3:
                print(f"Version check attempt {attempt}/3 failed: {e}. Retrying in {5 * attempt}s...")
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


def _ico_to_png(ico_path: Path) -> Path:
    """Convert an ICO file to PNG so toast notifications render it at full size."""
    png_path = Path(tempfile.gettempdir()) / f"{ico_path.stem}.png"
    if png_path.exists() and png_path.stat().st_mtime >= ico_path.stat().st_mtime:
        return png_path
    img = Image.open(ico_path)
    largest = max(img.info.get("sizes", [(img.width, img.height)]))
    img.size = largest
    img = img.resize(largest, Image.LANCZOS)
    img.save(png_path, format="PNG")
    return png_path


def notify(
    title: str,
    message: str,
    image_path: Path | None = None,
    launch: str | None = None,
    duration: str = "long",
    action_label: str | None = None,
    action_launch: str | None = None,
) -> None:
    """Show a Windows toast notification. If *launch* is set, clicking it opens that URL."""
    if APP_ICON_FILE.exists():
        try:
            icon = str(_ico_to_png(APP_ICON_FILE))
        except Exception:
            icon = str(APP_ICON_FILE.resolve())
    elif image_path:
        icon = str(image_path.resolve())
    else:
        icon = None
    toast = Notification(
        app_id="SilentSheet",
        title=title,
        msg=message,
        duration=duration,
        icon=icon,
        launch=launch or "",
    )
    if action_label and action_launch:
        toast.add_actions(label=action_label, launch=action_launch)
    toast.show()


def main() -> None:
    headless = "--headless" in sys.argv

    # Wait for internet connectivity (ethernet may not be plugged in yet)
    print("Waiting for internet...")
    if not wait_for_internet():
        notify("Timesheet - Error", "No internet after 10 minutes. Aborting.")
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

    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    try:
        # Step 1: Open the timesheet URL (retry on transient network errors)
        print(f"Opening {TIMESHEET_URL} ...")
        max_retries = 5
        for attempt in range(1, max_retries + 1):
            try:
                driver.get(TIMESHEET_URL)
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
                        "not working", "error", "502", "503", "504",
                        "bad gateway", "service unavailable",
                        "this site can", "err_", "timed out",
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
                # Final attempt failed — dump debug info
                debug_url = driver.current_url
                debug_title = driver.title
                print(f"DEBUG: Timed out waiting for #form1")
                print(f"DEBUG: Current URL   = {debug_url}")
                print(f"DEBUG: Page title    = {debug_title}")
                logger.error("Timed out waiting for #form1. URL=%s, title=%s", debug_url, debug_title)

                debug_dir = SCRIPT_DIR / "debug"
                debug_dir.mkdir(exist_ok=True)
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

                screenshot_path = debug_dir / f"screenshot_{timestamp}.png"
                driver.save_screenshot(str(screenshot_path))
                print(f"DEBUG: Screenshot saved to {screenshot_path}")

                page_source_path = debug_dir / f"page_source_{timestamp}.html"
                page_source_path.write_text(driver.page_source, encoding="utf-8")
                print(f"DEBUG: Page source saved to {page_source_path}")
                logger.error("Page source saved to %s", page_source_path)
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

        notify(
            f"EasyAuth: {auth_number}",
            "Tap this number on your Authenticator app to approve.",
            image_path=auth_image_path,
        )

        # Wait for the user to approve on their device and the page to proceed
        print("Waiting for authentication to complete...")
        wait_for_auth = WebDriverWait(driver, 65)  # 65 seconds to approve
        try:
            wait_for_auth.until(EC.url_changes(driver.current_url))
        except TimeoutException:
            raise TimeoutError("EasyAuth request timed out waiting for approval.")

        # Check if we landed on the timeout error page
        try:
            timeout_div = driver.find_elements(By.ID, "timeout")
            if timeout_div and timeout_div[0].is_displayed():
                raise TimeoutError("EasyAuth request timed out.")
        except Exception as e:
            if isinstance(e, TimeoutError):
                raise
            pass

        print("Authentication successful! Redirected to:", driver.current_url)

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
            # Fallback: first visible effort input in either section
            print(f"Task '{TASK_NAME}' / '{CHARGE_TYPE}' not found, trying fallback...")
            effort_input = None
            for fid in ("effortAssign00", "effortUnassign00"):
                matches = driver.find_elements(By.ID, fid)
                if matches and matches[0].is_displayed():
                    effort_input = matches[0]
                    print(f"Using fallback input: {fid}")
                    break
            if effort_input is None:
                raise Exception(
                    f"No effort input found for task '{TASK_NAME}' with charge type '{CHARGE_TYPE}'"
                )

        # Check current value before filling
        current_value = effort_input.get_attribute("value").strip()
        if current_value == "9":
            print("Effort already set to 9 hours. Skipping.")
            mark_done_today()
            mark_notified_today()
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
                notify(
                    "Timesheet - Warning",
                    f"Submitted but verification found '{verified_value}' hours instead of 9. "
                    "Please check manually.",
                )

        time.sleep(3)

    except Exception as e:
        logger.exception("Timesheet automation failed")
        print(f"Error: {e}", file=sys.stderr)
        
        if isinstance(e, TimeoutError) and "timed out" in str(e).lower():
            startup_dir = Path.home() / r"AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup"
            startup_vbs = startup_dir / "launch_silentsheet.vbs"
            project_vbs = SCRIPT_DIR / "silentsheet_launcher.vbs"
            retry_vbs = SCRIPT_DIR / "silentsheet_retry.vbs"

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
                "Timesheet - Timeout",
                "EasyAuth request timed out. Click Retry to try again.",
                action_label="Retry",
                action_launch=f"file:///{vbs_to_launch.as_posix()}",
            )
        else:
            notify("Timesheet - Error", str(e))
            
        if not headless:
            input("Press Enter to close the browser...")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
