"""Standalone script to detect available timesheet tasks via EasyAuth login.

Opens a visible Chrome window, authenticates via EasyAuth (with a toast
notification showing the auth number), scrapes the task grid, and prints
a JSON result line to stdout for setup.ps1 to parse.

Usage:
    python scrape_tasks.py <employee_id>
    python scrape_tasks.py --choose
"""

import json
import subprocess
import sys
import time
import tempfile
import tomllib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
from winotify import Notification

try:
    import winreg
except ImportError:
    winreg = None

import error_logger

TIMESHEET_URL = "https://timesheet.ultimatix.net/timesheet/"
WAIT_TIMEOUT = 30
SCRIPT_DIR = Path(__file__).resolve().parent
APP_ICON_FILE = SCRIPT_DIR / "favicon.ico"

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


def is_dark_mode_enabled() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return val == 0
    except OSError:
        return False


def create_auth_number_image(auth_number: str) -> Path:
    image_path = Path(tempfile.gettempdir()) / f"silentsheet_easyauth_{auth_number}.png"
    size = 512
    dark = is_dark_mode_enabled()
    image = Image.new("RGB", (size, size), "#000000" if dark else "#FFFFFF")
    draw = ImageDraw.Draw(image)

    card_color = "#1E1E1E" if dark else "#F5F7FA"
    border_color = "#3A3A3A" if dark else "#D5DBE3"
    text_color = "#F4F4F4" if dark else "#111827"

    draw.rounded_rectangle(
        [22, 22, size - 22, size - 22],
        radius=42,
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
        if (right - left) <= int(size * 0.78) and (bottom - top) <= int(size * 0.50):
            font = loaded_font
            break

    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x = (size - (right - left)) // 2 - left
    y = (size - (bottom - top)) // 2 - top
    draw.text((x, y), text, fill=text_color, font=font)
    image.save(image_path)
    return image_path


def _ico_to_png(ico_path: Path) -> Path:
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


def _update_config(task_name: str, charge_type: str) -> None:
    """Update config.toml with the selected task_name and charge_type."""
    config_file = SCRIPT_DIR / "config.toml"
    with open(config_file, "r", encoding="utf-8-sig") as f:
        config = tomllib.loads(f.read())
    employee_id = config["employee"]["EMPLOYEE_ID"]
    content = (
        "[employee]\n"
        f'EMPLOYEE_ID = "{employee_id}"\n'
        "\n"
        "[timesheet]\n"
        f'task_name = "{task_name}"\n'
        f'charge_type = "{charge_type}"\n'
    )
    config_file.write_text(content, encoding="utf-8")


def _choose_interactive(tasks: list[dict]) -> None:
    """Present a numbered menu for the user to pick a task, update config, and auto-retry."""
    print(f"\n{'=' * 55}")
    print("  Available Tasks on Timesheet")
    print(f"{'=' * 55}\n")
    for i, t in enumerate(tasks, 1):
        print(f"  [{i}] {t['task_name']}  [{t['charge_type']}]")
    print()

    while True:
        try:
            choice = input("  Enter the number of your task: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(tasks):
                break
            print(f"  Please enter a number between 1 and {len(tasks)}.")
        except (ValueError, EOFError):
            print(f"  Please enter a number between 1 and {len(tasks)}.")

    selected = tasks[idx]
    task_name = selected["task_name"]
    charge_type = selected["charge_type"]

    print(f"\n  Selected: {task_name} [{charge_type}]")
    _update_config(task_name, charge_type)
    print("  [+] config.toml updated.\n")

    notify(
        "Timesheet - Config Updated",
        f"Task set to '{task_name}' [{charge_type}]. Retrying...",
    )

    # Auto-retry fill_timesheet.py --headless in the background
    python_exe = Path(sys.executable)
    pythonw_exe = python_exe.parent / "pythonw.exe"
    if not pythonw_exe.exists():
        pythonw_exe = python_exe
    script_path = SCRIPT_DIR / "fill_timesheet.py"
    subprocess.Popen(
        [str(pythonw_exe), str(script_path), "--headless"],
        cwd=str(SCRIPT_DIR),
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
    )
    print("  [+] SilentSheet is retrying in the background.")
    print("      You will be notified when it needs EasyAuth or finishes.\n")


def main() -> None:
    choose_mode = "--choose" in sys.argv

    if choose_mode:
        # Read employee ID from config.toml
        config_file = SCRIPT_DIR / "config.toml"
        if not config_file.exists():
            print("Error: config.toml not found. Run setup.ps1 first.", file=sys.stderr)
            sys.exit(1)
        with open(config_file, "r", encoding="utf-8-sig") as f:
            config = tomllib.loads(f.read())
        employee_id = config["employee"]["EMPLOYEE_ID"]
    elif len(sys.argv) < 2:
        print("Usage: python scrape_tasks.py <employee_id>", file=sys.stderr)
        print("Usage: python scrape_tasks.py --choose", file=sys.stderr)
        print("SCRAPE_RESULT:[]")
        sys.exit(1)
    else:
        employee_id = sys.argv[1]

    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    try:
        # Step 1: Open the timesheet URL
        print(f"Opening {TIMESHEET_URL} ...")
        max_retries = 5
        for attempt in range(1, max_retries + 1):
            try:
                driver.get(TIMESHEET_URL)
                break
            except Exception as nav_err:
                err_msg = str(nav_err)
                if attempt < max_retries and any(
                    code in err_msg
                    for code in (
                        "net::ERR_CONNECTION_RESET",
                        "net::ERR_INTERNET_DISCONNECTED",
                        "net::ERR_NAME_NOT_RESOLVED",
                        "net::ERR_CONNECTION_REFUSED",
                        "net::ERR_CONNECTION_TIMED_OUT",
                        "net::ERR_NETWORK_CHANGED",
                    )
                ):
                    wait_secs = 5 * attempt
                    print(
                        f"Connection error (attempt {attempt}/{max_retries}). Retrying in {wait_secs}s..."
                    )
                    time.sleep(wait_secs)
                else:
                    raise

        # Step 2: Wait for login page
        print("Waiting for login page...")
        login_attempts = 3
        username_input = None
        for login_attempt in range(1, login_attempts + 1):
            try:
                username_input = WebDriverWait(driver, WAIT_TIMEOUT).until(
                    EC.presence_of_element_located((By.ID, "form1"))
                )
                break
            except TimeoutException:
                if login_attempt < login_attempts:
                    print(
                        f"Page failed to load (attempt {login_attempt}/{login_attempts}). Refreshing..."
                    )
                    driver.refresh()
                    time.sleep(3)
                else:
                    raise

        # Step 3: Enter employee ID and proceed
        print(f"Entering employee ID: {employee_id}")
        username_input.clear()
        username_input.send_keys(employee_id)

        proceed_button = wait.until(
            EC.element_to_be_clickable((By.ID, "proceed-button"))
        )
        proceed_button.click()

        # Step 4: Click EasyAuth and get auth number
        print("Waiting for EasyAuth button...")
        easyauth_button = wait.until(
            EC.element_to_be_clickable((By.ID, "easyAuth-btn"))
        )
        easyauth_button.click()

        print("Waiting for authentication number...")

        def digits_have_text(d):
            el = d.find_element(By.CSS_SELECTOR, "#number .digits")
            text = el.text.strip()
            return el if text else False

        digits_element = wait.until(digits_have_text)
        auth_number = digits_element.text.strip()

        print(f"\n{'=' * 50}")
        print(f"  EasyAuth Number: {auth_number}")
        print(f"  Approve this on your Authenticator app")
        print(f"{'=' * 50}\n")

        # Show toast notification with auth number
        auth_image = None
        try:
            auth_image = create_auth_number_image(auth_number)
        except Exception:
            pass
        notify(
            f"EasyAuth: {auth_number}",
            "Tap this number on your Authenticator app to approve.",
            image_path=auth_image,
        )

        # Step 5: Wait for auth redirect (2 min timeout for manual approval)
        print("Waiting for authentication to complete...")
        auth_start_url = driver.current_url
        auth_timeout = 120
        auth_start = time.time()
        last_notify_time = auth_start
        while time.time() - auth_start < auth_timeout:
            if driver.current_url != auth_start_url:
                break
            # Re-show notification every 25 seconds
            if time.time() - last_notify_time >= 25:
                notify(
                    f"EasyAuth: {auth_number}",
                    "Tap this number on your Authenticator app to approve.",
                    image_path=auth_image,
                )
                last_notify_time = time.time()
            time.sleep(1)
        else:
            print("EasyAuth timed out.", file=sys.stderr)
            error_logger.write_report(
                "Waiting for EasyAuth approval (task list)", driver=driver
            )
            if not choose_mode:
                print("SCRAPE_RESULT:[]")
            return

        # Check for timeout error page
        try:
            timeout_div = driver.find_elements(By.ID, "timeout")
            if timeout_div and timeout_div[0].is_displayed():
                print("EasyAuth timed out on server side.", file=sys.stderr)
                error_logger.write_report(
                    "Waiting for EasyAuth approval (task list)", driver=driver
                )
                if not choose_mode:
                    print("SCRAPE_RESULT:[]")
                return
        except Exception:
            pass

        print("Authentication successful!")

        # Step 6: Scrape available tasks
        print("Waiting for timesheet page to load...")
        wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "span.taskNameFont"))
        )
        time.sleep(2)  # let Angular finish rendering

        tasks = []
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
                for charge_type, col_idx in CHARGE_TYPE_COLUMNS.items():
                    inputs = row.find_elements(
                        By.XPATH,
                        f"td[{col_idx}]//input[contains(@id, '{prefix}')]",
                    )
                    for inp in inputs:
                        if inp.is_displayed():
                            entry = {"task_name": task_name, "charge_type": charge_type}
                            if entry not in tasks:
                                tasks.append(entry)

        print(f"\nFound {len(tasks)} task(s).")

        if choose_mode:
            if tasks:
                _choose_interactive(tasks)
            else:
                print("\n  No tasks found on the timesheet. Cannot update config.")
                notify("SilentSheet", "No tasks found on the timesheet page.")
        else:
            print(f"SCRAPE_RESULT:{json.dumps(tasks)}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if not choose_mode:
            print("SCRAPE_RESULT:[]")
        else:
            error_logger.write_report(
                "Fetching task list", exc=e, driver=driver
            )
            notify(
                "SilentSheet",
                "Couldn't load the task list right now. "
                "A diagnostic report was saved to the logs folder.",
            )
    finally:
        driver.quit()

    if choose_mode:
        input("Press Enter to close...")


if __name__ == "__main__":
    main()
