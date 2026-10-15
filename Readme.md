# SilentSheet

Windows Ultimatix timesheet automation: EasyAuth approval, configured task, 9 hours, submit, then refresh and verify. Daily state prevents repeat submissions after successful verification. Review your task and hours before enabling automation.

## Requirements

- Windows 10/11, Python >=3.12, Chrome or Edge.
- Ultimatix access and EasyAuth approval on your phone.
- Network access for login, version checks, and downloads. Bundled wheels can satisfy setup dependencies; they do not make browser automation offline.

## Install

Run from an **empty folder** where SilentSheet should live:

```powershell
mkdir "$HOME\SilentSheet"
cd "$HOME\SilentSheet"
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/zpratikpathak/SilentSheet-Ultimatix/home/install.ps1 | iex"
```

This executes code from the repository's mutable `home` branch. Review the script first if you do not already trust that source. HTTPS and archive path checks are not a signed-release guarantee.

Bootstrap verifies Python >=3.12, offers Python 3.12 through winget only after explicit consent, validates archive paths, extracts into the empty destination, then runs `manage.py setup`. It refuses linked destinations and archive links, traversal, duplicate paths, and excessive expanded size. Extraction/setup failures retain files for inspection; rerun setup rather than bootstrap in that nonempty folder.

For an existing checkout or extracted release:

```powershell
py -3.12 manage.py setup
```

Substitute an installed Python >=3.12 version or its full executable path for `py -3.12` throughout. Setup creates/reuses `.venv`, tries bundled wheels before online dependencies (uv if available, then pip), checks Chrome/Edge, configures Employee ID and task, and installs autorun. Missing browser installation requires consent. Task lookup supports manual configuration fallback. Setup does not submit a timesheet or open GitHub.

## Run and configure

```powershell
.\.venv\Scripts\python.exe fill_timesheet.py
.\.venv\Scripts\python.exe fill_timesheet.py --visible
py -3.12 manage.py configure
py -3.12 manage.py choose-task
py -3.12 manage.py setup --silent
```

`configure` writes configuration without launching automation. `choose-task` fetches tasks, saves selection, and retries automation in the background; working environment/configuration required. Arrow keys/Enter select in Windows consoles; redirected input uses numbered choices. `--silent` setup requires complete configuration and still installs dependencies and autorun; it is not a dry run. `choose-task --silent` is rejected.

`config.toml` example (see `example.config.toml`):

```toml
[employee]
EMPLOYEE_ID = "12345678"

[timesheet]
task_name = "Development"
charge_type = "Billable"
```

## Autorun

```powershell
py -3.12 src\setup_startup.py install-startup
py -3.12 src\setup_startup.py install-logon
py -3.12 src\setup_startup.py uninstall-all
```

Startup folder runs at user sign-in, not machine boot before login. Scheduled task runs at logon/unlock. Setup preserves a detected existing mode; otherwise prompts. Removal checks ownership and can refuse legacy/mismatched registrations. Inspect those manually rather than deleting unrelated entries.

## Maintenance and migration limits

`manage.py update` is **stopped-application maintenance**, not an unattended live updater. It downloads from `home`, but still requires manual autorun removal first. Protocol/AUMID registrations do not block maintenance and need not be removed for updates. Run with base Python, not this installation's `.venv`. Git checkouts and linked paths are refused. `requirements.txt` must match byte-for-byte; parsed `project.dependencies` and `project.requires-python` in `pyproject.toml` must match. Version-only changes are allowed; updates do not rebuild or change `.venv`. New unreviewed Python modules can also be refused.

The notification's Update action opens management with `sys._base_executable` (mapping `pythonw.exe` to console `python.exe`) before loading configuration/Selenium. Choose Task keeps the current venv interpreter, also using console `python.exe`. Update does **not** remove autorun or stop running automation; those checks still apply. No automatic process killing or full dependency-changing migration is provided.

For archive installations, prepare maintenance as follows:

1. Back up `config.toml`, `runtime`, and logs. Close SilentSheet and its browsers, including any app scripts launched through external Python. Identify and close Windows Script Host processes before maintenance.
2. Remove autorun using `uninstall-all` above. If ownership checks fail, inspect the Startup shortcut and `SilentSheet` scheduled task before manually removing them.
3. Open a fresh terminal without the project venv activated. Use an explicitly selected base interpreter:

```powershell
py -3.12 manage.py update
```

Process checks ignore verified external Python executables, so unrelated external Python does not block maintenance. They cannot identify app scripts running under external Python: stopping those remains your responsibility. Interpreters inside the installation, Windows Script Host processes, and inaccessible interpreter/script-host candidates still block maintenance. Do not treat refusal as proof of a running SilentSheet process, or elevate merely to bypass checks.

Successful update prints a backup path and preserves environment/user state. Re-enable autorun afterward. Failure attempts rollback and reports backup/rollback errors; recovery is not guaranteed after OS/storage failure. App startup refuses while `.silentsheet-management.lock` exists, before runtime dependencies, configuration, directories, or protocol dispatch. This startup check does not stop existing processes or eliminate launch races; offline maintenance remains required. A crash can leave the lock; investigate before removing it.

For dependency-changing releases or legacy migration, use fresh setup in a separate empty directory. Disable old autorun first, retain backups, copy/review configuration, and optionally retain daily state to avoid a duplicate submission. Do not copy the old `.venv`. Verify the new setup before manually removing the old directory. Git checkout users should use their Git workflow instead of archive maintenance.

## Uninstall

Complete the same stopped-application, autorun-removal, and base-interpreter steps first. Protocol/AUMID removal is not a prerequisite:

```powershell
py -3.12 manage.py uninstall
py -3.12 manage.py uninstall --purge
```

Choose one command. Default removes explicitly owned application files, retaining config, logs, runtime, `.venv`, and unowned files. `--purge` additionally deletes only `config.toml` after confirmation; `--yes` skips that confirmation. Neither command recursively removes the installation directory. Backups can contain configuration; protect them accordingly. No promise of complete automatic cleanup or legacy in-place migration.

Optional explicit registry cleanup after uninstall: inspect these per-user keys and delete them only if they belong to the removed installation. Shared names may belong to another SilentSheet installation. Management does not remove them automatically.

```powershell
reg query HKCU\Software\Classes\silentsheet /s
reg query HKCU\Software\Classes\AppUserModelId\SilentSheet /s
```

After confirming ownership:

```powershell
reg delete HKCU\Software\Classes\silentsheet /f
reg delete HKCU\Software\Classes\AppUserModelId\SilentSheet /f
```

Machine-wide registrations also do not block maintenance; ask their owner/administrator to handle any uninstall cleanup.

## Runtime and troubleshooting

- Waits for connectivity, checks release version, skips already-completed dates, requests EasyAuth, fills/submits and verifies hours.
- “Mark as Done” marks today's completion/notification state without submitting. Previous-day or invalid notification dates are ignored.
- Missing task notification opens `manage.py choose-task`; scraper emits one `SCRAPE_RESULT:<json>` line for management consumption.
- State: `runtime/.silentsheet_state.json`; generated launchers: `runtime/`; diagnostics: `logs/`.
- Reports/screenshots may contain employee or portal information. Review before sharing.
- Browser/login success, scheduled task permissions, and network availability remain machine-dependent. Use `--visible` for diagnosis.

## Files and checks

`install.ps1` only bootstraps. `manage.py` routes setup/configuration/task selection/update/uninstall. `src/setup_workflow.py` owns setup; `src/installation.py` owns conservative maintenance; `src/setup_startup.py` owns autorun. Legacy `setup.ps1`, `uninstall.ps1`, `src/choose_task.ps1`, and `src/task_workflow.ps1` are replaced by these Python commands.

```powershell
py -3.12 -m unittest discover -s tests
```

Isolated protocol tests mock process launch and reject runtime dependency imports; they do not contact Ultimatix, submit hours, or install software.
