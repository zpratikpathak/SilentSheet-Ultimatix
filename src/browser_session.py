"""Shared Chromium launch, EasyAuth, and timesheet navigation workflow."""

from __future__ import annotations

import logging
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import error_logger
from notification import dismiss, notify
from timesheet_common import (
    NAVIGATION_RETRIES,
    PORTAL_URL,
    TIMESHEET_LOAD_RETRIES,
    TIMESHEET_URL,
    WAIT_TIMEOUT,
)

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None

TRANSIENT_NAVIGATION_MARKERS = (
    "net::ERR_CONNECTION_RESET",
    "net::ERR_INTERNET_DISCONNECTED",
    "net::ERR_NAME_NOT_RESOLVED",
    "net::ERR_CONNECTION_REFUSED",
    "net::ERR_CONNECTION_TIMED_OUT",
    "net::ERR_NETWORK_CHANGED",
)
TRANSIENT_PAGE_MARKERS = (
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


class EasyAuthUnavailableError(Exception):
    """Raised when the EasyAuth option is unavailable."""


class AuthenticationCancelledError(Exception):
    """Raised when a caller asks to stop while approval is pending."""


class TimesheetLoadError(Exception):
    """Raised when the timesheet remains on a transient error page."""


@dataclass
class BrowserSession:
    driver: object
    wait: WebDriverWait
    browser_name: str
    approved_toast: object | None = None

    def close(self) -> None:
        self.driver.quit()


def configure_browser_options(options, headless: bool):
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
    else:
        options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option(
        "excludeSwitches", ["enable-automation", "enable-logging"]
    )
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--log-level=3")
    return options


def launch_browser(headless: bool, logger: logging.Logger | None = None):
    try:
        options = configure_browser_options(ChromeOptions(), headless)
        service = ChromeService(log_output=subprocess.DEVNULL)
        return webdriver.Chrome(service=service, options=options), "Chrome"
    except Exception as chrome_error:
        first_line = (
            str(chrome_error).strip().splitlines()[0]
            if str(chrome_error)
            else type(chrome_error).__name__
        )
        if logger:
            logger.error(
                "Chrome failed to launch, falling back to Edge: %s", chrome_error
            )
        print(
            f"Chrome failed to launch ({type(chrome_error).__name__}: {first_line}). "
            "Falling back to Microsoft Edge..."
        )
        options = configure_browser_options(EdgeOptions(), headless)
        service = EdgeService(log_output=subprocess.DEVNULL)
        return webdriver.Edge(service=service, options=options), "Edge"


def is_transient_navigation_error(error: Exception) -> bool:
    return any(marker in str(error) for marker in TRANSIENT_NAVIGATION_MARKERS)


def is_transient_page(driver) -> bool:
    haystack = f"{driver.title}\n{driver.page_source[:3000]}".lower()
    return any(marker in haystack for marker in TRANSIENT_PAGE_MARKERS)


def is_dark_mode_enabled() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
    except OSError:
        return False


def create_auth_number_image(auth_number: str) -> Path:
    image_path = Path(tempfile.gettempdir()) / f"silentsheet_easyauth_{auth_number}.png"
    size = 512
    dark = is_dark_mode_enabled()
    image = Image.new("RGB", (size, size), "#000000" if dark else "#FFFFFF")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        [22, 22, size - 22, size - 22],
        radius=42,
        fill="#1E1E1E" if dark else "#F5F7FA",
        outline="#3A3A3A" if dark else "#D5DBE3",
        width=4,
    )
    text = " ".join(str(auth_number))
    font = ImageFont.load_default()
    for font_size in range(300, 60, -8):
        loaded_font = None
        for candidate in (
            Path("C:/Windows/Fonts/seguisb.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
            Path("C:/Windows/Fonts/tahomabd.ttf"),
        ):
            if candidate.exists():
                loaded_font = ImageFont.truetype(str(candidate), font_size)
                break
        if loaded_font is None:
            break
        left, top, right, bottom = draw.textbbox((0, 0), text, font=loaded_font)
        if right - left <= size * 0.78 and bottom - top <= size * 0.50:
            font = loaded_font
            break
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(
        ((size - (right - left)) // 2 - left, (size - (bottom - top)) // 2 - top),
        text,
        fill="#F4F4F4" if dark else "#111827",
        font=font,
    )
    image.save(image_path)
    return image_path


def _mask_automation(driver, logger: logging.Logger | None) -> None:
    try:
        user_agent = driver.execute_script("return navigator.userAgent")
        driver.execute_cdp_cmd(
            "Network.setUserAgentOverride",
            {"userAgent": user_agent.replace("HeadlessChrome", "Chrome")},
        )
    except Exception as error:
        if logger:
            logger.error("Could not override user-agent: %s", error)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        },
    )


def _navigate_with_retries(driver, url: str, sleep: Callable[[float], None]) -> None:
    for attempt in range(1, NAVIGATION_RETRIES + 1):
        try:
            driver.get(url)
            return
        except Exception as error:
            if attempt == NAVIGATION_RETRIES or not is_transient_navigation_error(
                error
            ):
                raise
            wait_seconds = 5 * attempt
            print(
                f"Connection error (attempt {attempt}/{NAVIGATION_RETRIES}). Retrying in {wait_seconds}s..."
            )
            sleep(wait_seconds)


def _find_login_input(driver, sleep: Callable[[float], None]):
    for attempt in range(1, 4):
        try:
            return WebDriverWait(driver, WAIT_TIMEOUT).until(
                EC.presence_of_element_located((By.ID, "form1"))
            )
        except TimeoutException:
            if attempt == 3:
                error_logger.write_report("Loading login page", driver=driver)
                raise
            print(
                f"Page failed to load (attempt {attempt}/3): title='{driver.title}'. Refreshing..."
            )
            driver.refresh()
            sleep(3)
    raise AssertionError("unreachable")


def authenticate_and_open_timesheet(
    employee_id: str,
    *,
    headless: bool,
    approval_timeout: int,
    logger: logging.Logger | None = None,
    error_context: str = "Waiting for EasyAuth approval",
    notification_action: tuple[str, str] | None = None,
    stop_requested: Callable[[], bool] | None = None,
    show_approved_toast: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> BrowserSession:
    """Authenticate through EasyAuth and return a session on the timesheet page."""
    driver, browser_name = launch_browser(headless, logger)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    toast = None
    try:
        print(f"Using browser: {browser_name}")
        _mask_automation(driver, logger)
        print(f"Opening {PORTAL_URL} ...")
        _navigate_with_retries(driver, PORTAL_URL, sleep)
        print("Waiting for login page...")
        print(f"Current URL after navigation: {driver.current_url}")
        username_input = _find_login_input(driver, sleep)
        username_input.clear()
        username_input.send_keys(employee_id)
        wait.until(EC.element_to_be_clickable((By.ID, "proceed-button"))).click()
        try:
            wait.until(EC.element_to_be_clickable((By.ID, "easyAuth-btn"))).click()
        except TimeoutException as error:
            raise EasyAuthUnavailableError(
                "EasyAuth button not found on the login page."
            ) from error

        def digits_have_text(active_driver):
            element = active_driver.find_element(By.CSS_SELECTOR, "#number .digits")
            return element if element.text.strip() else False

        auth_number = wait.until(digits_have_text).text.strip()
        print(f"\n{'=' * 40}\n  EasyAuth Number: {auth_number}\n{'=' * 40}\n")
        try:
            auth_image = create_auth_number_image(auth_number)
        except Exception as image_error:
            auth_image = None
            if logger:
                logger.error("Could not create EasyAuth image: %s", image_error)
        action_label, action_launch = notification_action or (None, None)
        toast = notify(
            f"EasyAuth: {auth_number}",
            "Tap this number on your Authenticator app to approve.",
            image_path=auth_image,
            action_label=action_label,
            action_launch=action_launch,
        )
        auth_start_url = driver.current_url
        started = time.time()
        last_notification = started
        while time.time() - started < approval_timeout:
            if stop_requested and stop_requested():
                raise AuthenticationCancelledError()
            if driver.current_url != auth_start_url:
                break
            if time.time() - last_notification >= 25:
                toast = notify(
                    f"EasyAuth: {auth_number}",
                    "Tap this number on your Authenticator app to approve.",
                    image_path=auth_image,
                    action_label=action_label,
                    action_launch=action_launch,
                )
                last_notification = time.time()
            sleep(1)
        else:
            raise TimeoutError("EasyAuth request timed out waiting for approval.")

        timeout_elements = driver.find_elements(By.ID, "timeout")
        if timeout_elements and timeout_elements[0].is_displayed():
            raise TimeoutError("EasyAuth request timed out.")
        dismiss(toast)
        toast = None
        sleep(5)
        approved_toast = None
        if show_approved_toast:
            approved_toast = notify(
                "EasyAuth Approved",
                "Authentication successful! Filling timesheet...",
                duration="short",
            )

        for attempt in range(1, TIMESHEET_LOAD_RETRIES + 1):
            print(
                f"Opening timesheet at {TIMESHEET_URL} (attempt {attempt}/{TIMESHEET_LOAD_RETRIES}) ..."
            )
            try:
                driver.get(TIMESHEET_URL)
            except Exception as error:
                print(f"Timesheet navigation error: {str(error).splitlines()[0]}")
            sleep(3)
            if not is_transient_page(driver):
                return BrowserSession(driver, wait, browser_name, approved_toast)
            if attempt < TIMESHEET_LOAD_RETRIES:
                sleep(5 * attempt)
        error_logger.write_report("Loading timesheet page", driver=driver)
        raise TimesheetLoadError("Timesheet failed to load after several attempts.")
    except Exception:
        if toast is not None:
            dismiss(toast)
        error_logger.write_report(error_context, driver=driver)
        driver.quit()
        raise
