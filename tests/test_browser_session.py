from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import browser_session


class FakeOptions:
    def __init__(self):
        self.arguments = []
        self.experimental = {}

    def add_argument(self, value):
        self.arguments.append(value)

    def add_experimental_option(self, key, value):
        self.experimental[key] = value


class BrowserSessionTests(unittest.TestCase):
    def test_options_use_headless_or_visible_mode(self):
        headless = browser_session.configure_browser_options(FakeOptions(), True)
        visible = browser_session.configure_browser_options(FakeOptions(), False)
        self.assertIn("--headless=new", headless.arguments)
        self.assertIn("--start-maximized", visible.arguments)
        self.assertNotIn("--headless=new", visible.arguments)

    @patch.object(browser_session, "EdgeService", return_value=object())
    @patch.object(browser_session, "ChromeService", return_value=object())
    @patch.object(browser_session, "EdgeOptions", FakeOptions)
    @patch.object(browser_session, "ChromeOptions", FakeOptions)
    @patch.object(browser_session.webdriver, "Edge", return_value="edge-driver")
    @patch.object(
        browser_session.webdriver, "Chrome", side_effect=RuntimeError("missing")
    )
    def test_launch_falls_back_to_edge(
        self, chrome, edge, chrome_service, edge_service
    ):
        self.assertEqual(browser_session.launch_browser(True), ("edge-driver", "Edge"))
        edge.assert_called_once()

    def test_transient_page_detection(self):
        self.assertTrue(
            browser_session.is_transient_page(
                SimpleNamespace(title="503", page_source="")
            )
        )
        self.assertFalse(
            browser_session.is_transient_page(
                SimpleNamespace(title="Timesheet", page_source="task grid")
            )
        )

    def test_navigation_retries_only_transient_errors(self):
        driver = MagicMock()
        driver.get.side_effect = [RuntimeError("net::ERR_NETWORK_CHANGED"), None]
        sleep = MagicMock()
        browser_session._navigate_with_retries(driver, "https://example.test", sleep)
        self.assertEqual(driver.get.call_count, 2)
        sleep.assert_called_once_with(5)


if __name__ == "__main__":
    unittest.main()
