from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config_manager import load_config, main, update_task, write_config


class ConfigManagerTests(unittest.TestCase):
    def test_round_trip_escapes_strings_and_writes_without_bom(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            write_config(path, "user #1", 'Quote " and slash \\ café', "Non Billable")
            self.assertFalse(path.read_bytes().startswith(b"\xef\xbb\xbf"))
            config = load_config(path)
            self.assertEqual(config["employee"]["EMPLOYEE_ID"], "user #1")
            self.assertEqual(
                config["timesheet"]["task_name"], 'Quote " and slash \\ café'
            )

    def test_update_preserves_comments_and_unrelated_values(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                '[employee]\nEMPLOYEE_ID = "abc"\n\n[timesheet]\ntask_name = "Old"\ncharge_type = "Billable"\n\n[extra]\nenabled = true\n',
                encoding="utf-8",
            )
            update_task(path, "New # Task", "Night Shift")
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(parsed["extra"]["enabled"])
            self.assertEqual(parsed["timesheet"]["task_name"], "New # Task")

    def test_read_command_emits_summary_json(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            write_config(path, "12345678", "Development", "Billable")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--config", str(path), "read"]), 0)
            self.assertEqual(
                json.loads(output.getvalue()),
                {
                    "employee_id": "12345678",
                    "task_name": "Development",
                    "charge_type": "Billable",
                },
            )


if __name__ == "__main__":
    unittest.main()
