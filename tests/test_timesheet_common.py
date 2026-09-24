from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from timesheet_common import CHARGE_TYPE_COLUMNS, is_marked, mark, read_daily_state


class DailyStateTests(unittest.TestCase):
    def test_state_is_keyed_by_date_and_preserves_other_keys(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            mark(path, "last_filled", date(2026, 9, 21))
            mark(path, "last_notified", date(2026, 9, 22))
            self.assertTrue(is_marked(path, "last_filled", date(2026, 9, 21)))
            self.assertFalse(is_marked(path, "last_filled", date(2026, 9, 22)))
            self.assertEqual(read_daily_state(path)["last_notified"], "2026-09-22")

    def test_invalid_state_is_empty(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(read_daily_state(path), {})

    def test_charge_columns_preserve_existing_layout(self):
        self.assertEqual(CHARGE_TYPE_COLUMNS["Billable"], 2)
        self.assertEqual(CHARGE_TYPE_COLUMNS["On Call"], 9)


if __name__ == "__main__":
    unittest.main()
