"""Timesheet automation script using Selenium to log in via EasyAuth.

Designed to run on Windows startup. Tracks completion per day so it only
runs once. Shows a Windows toast notification with the EasyAuth number.
"""

import socket
import sys
import tempfile
import time
import tomllib
from datetime import date
from pathlib import Path

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
from winotify import Notification

import pratikpathak
pratikpathak.main()

TIMESHEET_URL = "https://timesheet.ultimatix.net/timesheet/"
WAIT_TIMEOUT = 30  # seconds to wait for elements

# File that stores the date of the last successful fill
SCRIPT_DIR = Path(__file__).resolve().parent
DONE_FILE = SCRIPT_DIR / ".timesheet_done"
CONFIG_FILE = SCRIPT_DIR / "config.toml"
APP_ICON_FILE = SCRIPT_DIR / "favicon.ico"

# Load config
with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
    _config = tomllib.loads(f.read())
EMPLOYEE_ID = _config["employee"]["EMPLOYEE_ID"]
TASK_NAME = _config.get("timesheet", {}).get("task_name", "Development")
CHARGE_TYPE = _config.get("timesheet", {}).get("charge_type", "Billable")


def already_done_today() -> bool:
    """Return True if the timesheet was already filled today."""
    if DONE_FILE.exists():
        stored = DONE_FILE.read_text().strip()
        if stored == str(date.today()):
            return True
    return False


def mark_done_today() -> None:
    """Write today's date to the done file."""
    DONE_FILE.write_text(str(date.today()))


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
    image = Image.new("RGB", (size, size), "#000000" if is_dark_mode_enabled() else "#FFFFFF")
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


def notify(title: str, message: str, image_path: Path | None = None) -> None:
    """Show a Windows toast notification."""
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
        duration="long",
        icon=icon,
    )
    toast.show()


def main() -> None:
    headless = "--headless" in sys.argv

    # Skip if already filled today
    if already_done_today():
        print("Timesheet already filled today. Exiting.")
        notify("Timesheet", "Already filled for today. No action needed.")
        return

    # Wait for internet connectivity (ethernet may not be plugged in yet)
    print("Waiting for internet...")
    if not wait_for_internet():
        notify("Timesheet - Error", "No internet after 10 minutes. Aborting.")
        return
    print("Internet available.")

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
        # Step 1: Open the timesheet URL
        print(f"Opening {TIMESHEET_URL} ...")
        driver.get(TIMESHEET_URL)

        # Step 2: Wait for redirect to login page and find the username input
        print("Waiting for login page...")
        username_input = wait.until(
            EC.presence_of_element_located((By.ID, "form1"))
        )

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
                print(f"Warning: Could not create EasyAuth image: {image_error}")

        notify(
            f"EasyAuth: {auth_number}",
            "Tap this number on your Authenticator app to approve.",
            image_path=auth_image_path,
        )

        # Wait for the user to approve on their device and the page to proceed
        print("Waiting for authentication to complete...")
        wait_for_auth = WebDriverWait(driver, 120)  # 2 minutes to approve
        wait_for_auth.until(EC.url_changes(driver.current_url))
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
            for prefix, section in (("effortAssign", "Assigned"), ("effortUnassign", "Unassigned")):
                xpath = (
                    f"//tr[.//span[contains(@class, 'taskNameFont') and "
                    f"contains(normalize-space(text()), '{TASK_NAME}')]]"
                    f"/td[{column_idx}]//input[contains(@id, '{prefix}')]"
                )
                for el in d.find_elements(By.XPATH, xpath):
                    if el.is_displayed():
                        print(f"Found '{TASK_NAME}' in {section} Task section, charge type '{CHARGE_TYPE}'")
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
                raise Exception(f"No effort input found for task '{TASK_NAME}' with charge type '{CHARGE_TYPE}'")

        # Check current value before filling
        current_value = effort_input.get_attribute("value").strip()
        if current_value == "9":
            print("Effort already set to 9 hours. Skipping.")
            mark_done_today()
            notify("Timesheet", "Already had 9 hours. Marked as done.")
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
            print("Timesheet submitted!")
            mark_done_today()
            notify("Timesheet", "Filled 9 hours and submitted successfully!")

        time.sleep(3)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        notify("Timesheet - Error", str(e))
        if not headless:
            input("Press Enter to close the browser...")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
