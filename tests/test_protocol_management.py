"""Isolated entry-point checks: no configuration, dependencies, or real launch."""
import ast
import builtins
from datetime import date, timedelta
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class ProtocolManagementTests(unittest.TestCase):
    def test_dispatch_without_dependencies_or_config(self):
        original_import = builtins.__import__

        def isolated_import(name, *args, **kwargs):
            if name.split('.')[0] in {'selenium', 'pratikpathak', 'config_manager', 'browser_session', 'notification'}:
                raise AssertionError(f'Runtime import during maintenance: {name}')
            return original_import(name, *args, **kwargs)

        for action, command in [('update', 'update'), ('choosetask', 'choose-task')]:
            with self.subTest(action=action), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                script = root / 'fill_timesheet.py'
                shutil.copyfile(ROOT / script.name, script)
                with patch.object(sys, 'argv', [str(script), f'silentsheet:{action}']), \
                     patch.object(sys, 'executable', str(root / '.venv' / 'Scripts' / 'pythonw.exe')), \
                     patch.object(sys, '_base_executable', str(root / 'base' / 'pythonw.exe')), \
                     patch.object(subprocess, 'CREATE_NEW_CONSOLE', 16, create=True), \
                     patch.object(subprocess, 'Popen') as launch, \
                     patch('builtins.__import__', side_effect=isolated_import):
                    with self.assertRaises(SystemExit) as exit_result:
                        runpy.run_path(str(script), run_name='__main__')
                self.assertEqual(exit_result.exception.code, 0)
                interpreter = root / 'base' if action == 'update' else root / '.venv' / 'Scripts'
                launch.assert_called_once_with(
                    [str(interpreter / 'python.exe'), str(root / 'manage.py'), command],
                    cwd=str(root), creationflags=16)
                self.assertEqual(list(root.iterdir()), [script])

    def test_management_lock_refuses_startup_before_side_effects(self):
        original_import = builtins.__import__

        def isolated_import(name, *args, **kwargs):
            if name.split('.')[0] in {'selenium', 'pratikpathak', 'config_manager', 'browser_session', 'notification'}:
                raise AssertionError(f'Runtime import while locked: {name}')
            return original_import(name, *args, **kwargs)

        for args in [[], ['--visible'], ['silentsheet:update'], ['silentsheet:choosetask'],
                     [f'silentsheet:markdone-{date.today()}']]:
            with self.subTest(args=args), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                script = root / 'fill_timesheet.py'
                shutil.copyfile(ROOT / script.name, script)
                lock = root / '.silentsheet-management.lock'
                lock.write_text('123', encoding='ascii')
                with patch.object(sys, 'argv', [str(script), *args]), \
                     patch.object(subprocess, 'Popen') as launch, \
                     patch('builtins.__import__', side_effect=isolated_import):
                    with self.assertRaisesRegex(SystemExit, 'maintenance in progress'):
                        runpy.run_path(str(script), run_name='__main__')
                launch.assert_not_called()
                self.assertEqual(set(root.iterdir()), {script, lock})
                self.assertEqual(lock.read_text(encoding='ascii'), '123')

    def test_markdone_dates_unchanged(self):
        tree = ast.parse((ROOT / 'fill_timesheet.py').read_text(encoding='utf-8'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_handle_mark_done')
        for value, valid in [(str(date.today()), True), (str(date.today() - timedelta(days=1)), False), ('bad', False), (None, False)]:
            with self.subTest(value=value):
                scope = dict(date=date, notify=Mock(), mark_done_today=Mock(), mark_notified_today=Mock())
                exec(compile(ast.Module(body=[function], type_ignores=[]), '<markdone>', 'exec'), scope)
                scope['_handle_mark_done'](value)
                self.assertEqual(scope['mark_done_today'].call_count, int(valid))
                self.assertEqual(scope['mark_notified_today'].call_count, int(valid))
                scope['notify'].assert_called_once()


if __name__ == '__main__':
    unittest.main()