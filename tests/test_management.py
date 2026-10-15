"""Management checks; no installs, browser sessions, or registry writes."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import manage
from src import setup_workflow as workflow
from src.config_manager import write_config


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="management & café ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()

    def test_cli_dispatches_absolute_root_and_cancellation(self):
        with patch.object(workflow, "configure") as action:
            self.assertEqual(manage.main(["configure", "--silent"]), 0)
            action.assert_called_once_with(manage.ROOT, silent=True)
            self.assertTrue(manage.ROOT.is_absolute())
        with patch.object(workflow, "choose_task", side_effect=KeyboardInterrupt), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(manage.main(["choose-task"]), 130)

    def test_silent_never_prompts(self):
        with patch("builtins.input", side_effect=AssertionError("Unexpected input")):
            with self.assertRaises(OSError):
                workflow.configure(self.root, silent=True)
            with self.assertRaises(ValueError):
                workflow.choose_task(self.root, silent=True)
            write_config(self.root / "config.toml", "abc", "Task", "Billable")
            workflow.configure(self.root, silent=True)

    def test_numbered_menu_defaults_and_cancel(self):
        with patch.object(sys.stdin, "isatty", return_value=False), patch("builtins.input", side_effect=["9", "", "q"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(workflow.select_option("Menu", ["A", "B"], 1), 1)
            with self.assertRaises(KeyboardInterrupt):
                workflow.select_option("Menu", ["A"])

    @unittest.skipUnless(sys.platform == "win32", "Windows key input")
    def test_arrow_menu_clamps_and_cancels(self):
        with patch.object(sys.stdin, "isatty", return_value=True), patch.object(sys.stdout, "isatty", return_value=True), patch("msvcrt.getwch", side_effect=["\xe0", "H", "\xe0", "P", "\xe0", "P", "\r", "\x1b"]):
            self.assertEqual(workflow.select_option("Menu", ["A", "B"]), 1)
            with self.assertRaises(KeyboardInterrupt):
                workflow.select_option("Menu", ["A"])

    def test_scraper_validates_protocol_and_uses_absolute_paths(self):
        task = {"task_name": "Task", "charge_type": "Billable"}
        with patch.object(workflow.subprocess, "run", return_value=Mock(stdout="SCRAPE_RESULT:" + json.dumps([task]))) as run:
            self.assertEqual(workflow.scrape_tasks(self.root, "abc"), [task])
            command = run.call_args.args[0]
            self.assertTrue(Path(command[0]).is_absolute())
            self.assertTrue(Path(command[1]).is_absolute())
            self.assertEqual(run.call_args.kwargs["cwd"], self.root)
            self.assertTrue(run.call_args.kwargs["check"])
        for payload in ("missing", "SCRAPE_RESULT:[]", "SCRAPE_RESULT:{}", 'SCRAPE_RESULT:[{"task_name": 4}]', "SCRAPE_RESULT:not-json"):
            with self.subTest(payload=payload), patch.object(workflow.subprocess, "run", return_value=Mock(stdout=payload)):
                with self.assertRaises(ValueError):
                    workflow.scrape_tasks(self.root, "abc")

    def test_scraper_failure_and_cancel_leave_config_unchanged(self):
        path = self.root / "config.toml"
        write_config(path, "abc", "Old", "Billable")
        original = path.read_bytes()
        for error in (subprocess.CalledProcessError(1, "scraper"), subprocess.TimeoutExpired("scraper", 300), KeyboardInterrupt()):
            with patch.object(workflow, "scrape_tasks", side_effect=error), patch.object(workflow.subprocess, "Popen") as launch:
                with self.assertRaises(type(error)):
                    workflow.choose_task(self.root)
                self.assertEqual(path.read_bytes(), original)
                launch.assert_not_called()

    def test_dependencies_offline_then_online_without_recreating_venv(self):
        python = workflow.venv_python(self.root)
        python.parent.mkdir(parents=True)
        python.touch()
        with patch.object(workflow, "validate_python"), patch.object(workflow.shutil, "which", return_value=None), patch.object(workflow, "_run", side_effect=[subprocess.CalledProcessError(1, "pip"), Mock()]) as run:
            workflow.install_dependencies(self.root)
            commands = [call.args[1] for call in run.call_args_list]
            self.assertIn("--no-index", commands[0])
            self.assertNotIn("--no-index", commands[1])
            self.assertEqual(commands[0][:4], [str(python), "-m", "pip", "install"])

    def test_dependencies_uv_failure_uses_offline_pip(self):
        python = workflow.venv_python(self.root)
        python.parent.mkdir(parents=True)
        python.touch()
        with patch.object(workflow, "validate_python"), patch.object(workflow.shutil, "which", return_value="uv.exe"), patch.object(workflow, "_run", side_effect=[subprocess.CalledProcessError(1, "uv"), Mock()]) as run:
            workflow.install_dependencies(self.root)
            self.assertIn("--python", run.call_args_list[0].args[1])
            self.assertIn("--no-index", run.call_args_list[1].args[1])

    def test_dependency_failures_report_both_attempts(self):
        python = workflow.venv_python(self.root)
        python.parent.mkdir(parents=True)
        python.touch()
        with patch.object(workflow, "validate_python"), patch.object(workflow.shutil, "which", return_value=None), patch.object(workflow, "_run", side_effect=subprocess.CalledProcessError(1, "pip")):
            with self.assertRaisesRegex(RuntimeError, "offline and online"):
                workflow.install_dependencies(self.root)

    def test_edge_only_detection(self):
        edge = self.root / "Microsoft/Edge/Application/msedge.exe"
        edge.parent.mkdir(parents=True)
        edge.touch()
        with patch.object(workflow.shutil, "which", return_value=None), patch.dict(workflow.os.environ, {"LOCALAPPDATA": str(self.root)}, clear=True):
            self.assertEqual(workflow.find_browser(), edge)

    def test_broken_venv_not_overwritten(self):
        (self.root / ".venv").mkdir()
        with patch.object(workflow, "_run") as run:
            with self.assertRaisesRegex(RuntimeError, "Incomplete"):
                workflow.install_dependencies(self.root)
            run.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "Windows setup")
    def test_setup_propagates_startup_failure(self):
        from src import setup_startup
        with patch.object(workflow, "install_dependencies"), patch.object(workflow, "ensure_browser"), patch.object(workflow, "register_aumid"), patch.object(workflow, "configure"), patch.object(workflow.subprocess, "run", return_value=Mock(returncode=0)), patch.object(setup_startup, "PROJECT_DIR", self.root), patch.object(setup_startup, "SHORTCUT_DEST", self.root / "missing.vbs"), patch.object(setup_startup, "install_logon", side_effect=RuntimeError("scheduler failed")):
            with self.assertRaisesRegex(RuntimeError, "scheduler failed"):
                workflow.setup(self.root)


if __name__ == "__main__":
    unittest.main()