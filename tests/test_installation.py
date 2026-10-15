"""Maintenance tests use temporary trees; no registry/process/install operations."""
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
import zipfile

from src import installation as app
from src import setup_startup as startup


PROJECT = '[project]\nversion = "1.0"\nrequires-python = ">=3.12"\ndependencies = []\n'

def archive(extra=None, omit=()):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as output:
        for name in app.REQUIRED:
            if name not in omit:
                output.writestr("project/" + name, PROJECT if name == "pyproject.toml" else "old")
        for name, value in (extra or {}).items():
            entry = zipfile.ZipInfo("placeholder")
            entry.filename = name
            output.writestr(entry, value)
    return data.getvalue()


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "app"
        self.root.mkdir()
        for name in app.REQUIRED:
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text(PROJECT if name == "pyproject.toml" else "old")
        self.stage = Path(self.temp.name) / "stage"
        self.stage.mkdir()
        self.backup = Path(self.temp.name) / "backup"
        self.backup.mkdir()
        mkdtemp = tempfile.mkdtemp
        self.mock_backup = patch.object(
            app.tempfile, "mkdtemp",
            side_effect=lambda *args, **kwargs: str(self.backup)
            if kwargs.get("prefix") == "silentsheet-backup-" else mkdtemp(*args, **kwargs),
        )
        self.mock_backup.start()
        self.addCleanup(self.mock_backup.stop)

    def test_extraction_preserves_state(self):
        selected = app._extract(archive({"project/config.toml": "bad", "project/logs/a": "bad"}), self.stage)
        self.assertEqual(selected, app.REQUIRED)
        self.assertFalse((self.stage / "config.toml").exists())

    def test_unsafe_paths(self):
        for name in ("project/../escape", "/absolute", "project/C:bad", "project/a\\b", "project/NUL.txt", "project/a."):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                app._extract(archive({name: "bad"}), self.stage / str(len(name)))

    def test_symlink_refused(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as output:
            entry = zipfile.ZipInfo("project/link")
            entry.external_attr = 0o120777 << 16
            output.writestr(entry, "target")
        with self.assertRaises(RuntimeError):
            app._extract(data.getvalue(), self.stage)

    def test_git_checkout_refused(self):
        (self.root / ".git").write_text("gitdir: elsewhere")
        with self.assertRaises(RuntimeError):
            app.update(self.root)

    def test_lock_excludes_concurrent_operation(self):
        with app._lock(self.root):
            with self.assertRaises(FileExistsError):
                with app._lock(self.root):
                    self.fail("Second lock acquired")
        self.assertFalse((self.root / ".silentsheet-management.lock").exists())

    def test_backup_failure_does_not_mutate(self):
        (self.stage / "fill_timesheet.py").write_text("new")
        with patch.object(app, "_copy", side_effect=OSError("backup failed")):
            with self.assertRaises(OSError):
                app._replace(self.root, self.stage, {"fill_timesheet.py"}, set())
        self.assertEqual((self.root / "fill_timesheet.py").read_text(), "old")

    def test_rollback_new_and_existing_files(self):
        for name in ("example.config.toml", "fill_timesheet.py", "manage.py"):
            (self.stage / name).write_text("new")
        original = app._copy

        def fail(source, target):
            if source == self.stage / "manage.py":
                target.write_text("partial")
                raise OSError("locked")
            original(source, target)

        with patch.object(app, "_copy", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "backup:"):
                app._replace(self.root, self.stage, {"example.config.toml", "fill_timesheet.py", "manage.py"}, set())
        self.assertEqual((self.root / "fill_timesheet.py").read_text(), "old")
        self.assertEqual((self.root / "manage.py").read_text(), "old")
        self.assertFalse((self.root / "example.config.toml").exists())

    def test_dependency_change_refused_environment_untouched(self):
        (self.root / ".venv").mkdir()
        marker = self.root / ".venv/marker"
        marker.write_text("healthy")
        (self.root / "requirements.txt").write_text("different")
        with patch.object(app, "_idle"), patch.object(app, "_archive", return_value=archive()):
            with self.assertRaisesRegex(RuntimeError, "Dependency metadata changed"):
                app.update(self.root, silent=True)
        self.assertEqual(marker.read_text(), "healthy")
        self.assertEqual((self.root / "fill_timesheet.py").read_text(), "old")

    def test_uninstall_preserves_unknown_and_state(self):
        (self.root / "favicon.ico").write_bytes(b"icon")
        for name in ("config.toml", "custom.py", "log.txt"):
            (self.root / name).write_text("keep")
        with patch.object(app, "_idle"):
            app.uninstall(self.root)
        for name in ("config.toml", "custom.py", "log.txt"):
            self.assertEqual((self.root / name).read_text(), "keep")
        self.assertFalse((self.root / "fill_timesheet.py").exists())
        self.assertFalse((self.root / "favicon.ico").exists())
        self.assertEqual((self.backup / "favicon.ico").read_bytes(), b"icon")

    def test_version_update_and_icon_succeed(self):
        proposed = PROJECT.replace('"1.0"', '"2.0"') + 'description = "new"\n'
        data = archive({"project/pyproject.toml": proposed, "project/favicon.ico": b"icon"},
                       omit={"pyproject.toml"})
        with patch.object(app, "_idle"), patch.object(app, "_archive", return_value=data):
            self.assertEqual(app.update(self.root), 0)
        self.assertEqual((self.root / "pyproject.toml").read_text(), proposed)
        self.assertEqual((self.root / "favicon.ico").read_bytes(), b"icon")
        self.assertEqual((self.backup / "pyproject.toml").read_text(), PROJECT)

    def test_dependency_fields_refused_before_mutation(self):
        for proposed in (PROJECT.replace(">=3.12", ">=3.13"),
                         PROJECT.replace("[]", '["selenium"]')):
            data = archive({"project/pyproject.toml": proposed}, omit={"pyproject.toml"})
            with self.subTest(proposed=proposed), patch.object(app, "_idle"), \
                    patch.object(app, "_archive", return_value=data), patch.object(app, "_replace") as replace:
                with self.assertRaisesRegex(RuntimeError, "Dependency metadata changed"):
                    app.update(self.root)
                replace.assert_not_called()

    def test_invalid_source_metadata_and_legacy_archive_refused(self):
        cases = [
            (archive({"project/manage.py": "def broken("}, omit={"manage.py"}), SyntaxError),
            (archive({"project/pyproject.toml": "[bad"}, omit={"pyproject.toml"}), ValueError),
            (archive({"project/example.config.toml": "[bad"}), ValueError),
            *((archive(omit={name}), RuntimeError) for name in app.REQUIRED),
        ]
        for data, error in cases:
            with self.subTest(error=error), patch.object(app, "_idle"), \
                    patch.object(app, "_archive", return_value=data), patch.object(app, "_replace") as replace:
                with self.assertRaises(error):
                    app.update(self.root)
                replace.assert_not_called()
                self.assertEqual((self.root / "manage.py").read_text(), "old")

    def test_process_filter_and_ownership(self):
        outside = Path(self.temp.name) / "other/python.exe"
        cases = [
            ("protected.exe", outside, False, False),
            ("python.exe", outside, True, False),
            ("pythonw.exe", outside, True, False),
            ("python.exe", self.root / ".venv/Scripts/python.exe", True, True),
            ("python.exe", outside, False, True),
            ("wscript.exe", outside, True, True),
            ("cscript.exe", outside, True, True),
        ]
        for image, executable, accessible, refuses in cases:
            kernel = Mock()
            kernel.OpenProcess.return_value = 123 if accessible else 0

            def query(handle, flags, buffer, size):
                buffer.value = str(executable)
                return True

            kernel.QueryFullProcessImageNameW.side_effect = query
            with self.subTest(image=image, executable=executable, accessible=accessible), \
                    patch.object(app.subprocess, "run", return_value=Mock(stdout=f'"{image}","1234"\n')) as run, \
                    patch.object(app.os, "getpid", return_value=9999), \
                    patch.object(app.ctypes, "WinDLL", return_value=kernel, create=True):
                if refuses:
                    with self.assertRaises(RuntimeError):
                        app._no_python_processes(self.root)
                else:
                    app._no_python_processes(self.root)
                run.assert_called_once_with(["tasklist.exe", "/fo", "csv", "/nh"],
                                            check=True, capture_output=True, text=True, timeout=30)
                self.assertEqual(kernel.OpenProcess.call_count, int(image != "protected.exe"))
                self.assertEqual(kernel.CloseHandle.call_count, int(image != "protected.exe" and accessible))

    def test_process_query_failure_closes_handle(self):
        kernel = Mock()
        kernel.QueryFullProcessImageNameW.return_value = False
        with patch.object(app.subprocess, "run", return_value=Mock(stdout='"python.exe","1234"\n')), \
                patch.object(app.os, "getpid", return_value=9999), \
                patch.object(app.ctypes, "WinDLL", return_value=kernel, create=True):
            with self.assertRaisesRegex(RuntimeError, "Cannot verify process"):
                app._no_python_processes(self.root)
        kernel.CloseHandle.assert_called_once()

    def test_idle_ignores_registry_but_checks_autorun(self):
        registry = Mock()
        with patch.object(app.os, "name", "nt"), \
                patch.dict(app.os.environ, {"APPDATA": str(self.stage)}), \
                patch.object(app.sys, "prefix", str(self.stage)), \
                patch.dict("sys.modules", {"winreg": registry}), \
                patch.object(app.subprocess, "run", return_value=Mock(stdout="")) as run, \
                patch.object(app, "_no_python_processes") as processes:
            app._idle(self.root)
            registry.OpenKey.assert_not_called()
            processes.assert_called_once_with(self.root)
            run.return_value.stdout = '"\\SilentSheet","N/A","Ready"\n'
            with self.assertRaisesRegex(RuntimeError, "scheduled task"):
                app._idle(self.root)

    def test_purge_cancelled(self):
        with patch.object(app, "_idle"), patch("builtins.input", return_value="no"):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                app.uninstall(self.root, purge=True)
        self.assertTrue((self.root / "fill_timesheet.py").exists())

    def test_xml_escaping(self):
        with patch.object(startup, "PROJECT_DIR", Path("C:/A&B")), patch.object(startup, "_get_current_user", return_value="A&B"):
            task = ET.fromstring(startup.generate_task_xml())
        self.assertIn("A&B", "".join(task.itertext()))

    def test_scheduler_failure_propagates_and_temp_removed(self):
        from subprocess import CompletedProcess
        paths = []

        def failure(command, **kwargs):
            paths.append(Path(command[command.index("/xml") + 1]))
            return CompletedProcess(command, 1, "", "denied")

        with patch.object(startup, "_owned_task", return_value=False), patch.object(startup, "RUNTIME_DIR", self.stage), patch.object(startup, "TASK_VBS_DEST", self.stage / "launcher.vbs"), patch.object(startup.subprocess, "run", side_effect=failure):
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError, "denied"):
                    startup.install_logon()
        self.assertNotEqual(paths[0], paths[1])
        self.assertTrue(all(not path.exists() for path in paths))


if __name__ == "__main__":
    unittest.main()