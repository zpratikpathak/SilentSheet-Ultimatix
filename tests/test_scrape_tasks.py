from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import scrape_tasks


class ScrapeContractTests(unittest.TestCase):
    def test_missing_employee_still_emits_result(self):
        output = StringIO()
        with redirect_stdout(output), redirect_stderr(StringIO()):
            status = scrape_tasks.main([])
        self.assertEqual(status, 2)
        self.assertEqual(output.getvalue().strip(), "SCRAPE_RESULT:[]")

    @patch.object(scrape_tasks, "notify")
    @patch.object(scrape_tasks.error_logger, "write_report")
    @patch.object(
        scrape_tasks,
        "authenticate_and_open_timesheet",
        side_effect=RuntimeError("launch failed"),
    )
    def test_launch_failure_still_emits_result(self, authenticate, report, notify):
        output = StringIO()
        with redirect_stdout(output), redirect_stderr(StringIO()):
            status = scrape_tasks.main(["123"])
        self.assertEqual(status, 1)
        authenticate.assert_called_once_with(
            "123",
            headless=True,
            approval_timeout=120,
            error_context="Waiting for EasyAuth approval (task list)",
        )
        result_lines = [
            line
            for line in output.getvalue().splitlines()
            if line.startswith("SCRAPE_RESULT:")
        ]
        self.assertEqual(result_lines, ["SCRAPE_RESULT:[]"])

    def test_result_payload_is_json(self):
        tasks = [{"task_name": "Dev", "charge_type": "Billable"}]
        self.assertEqual(
            json.loads(scrape_tasks.format_scrape_result(tasks).split(":", 1)[1]),
            tasks,
        )


if __name__ == "__main__":
    unittest.main()
