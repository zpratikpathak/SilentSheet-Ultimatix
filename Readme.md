# SilentSheet

Automates daily timesheet entry on Ultimatix. Logs in via EasyAuth, fills 9 hours, and submits — all hands-free on Windows startup.

## Features

- Opens the Ultimatix timesheet portal in Chrome
- Enters your Employee ID and clicks through to EasyAuth login
- Shows a **Windows toast notification** with the EasyAuth number to approve on your phone
- Finds your assigned task dynamically (based on configuration) and fills 9 hours, then clicks Submit
- Skips if 9 hours are already filled
- Tracks completion per day (`.timesheet_done` file) — won't re-trigger on restarts
- Runs silently on Windows startup via a VBS launcher

## Requirements

- Windows 10/11
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Google Chrome installed

## Setup

The easiest way to set up the project is to use the provided PowerShell interactive setup script. This script checks prerequisites, sets up the Python environment (using `uv` or `pip`), generates your configuration file, and optionally enables the Windows startup auto-fill task.

```powershell
# Run the interactive setup script
.\setup.ps1
```

## Usage

### Run manually

```powershell
# If using uv
uv run python fill_timesheet.py

# If using standard python env
.\.venv\Scripts\python.exe fill_timesheet.py
```

### Add to / Remove from Windows Startup

You can set this up via the `.\setup.ps1` prompt, or manually:
```bash
uv run python setup_startup.py install
uv run python setup_startup.py uninstall
```

The script will run automatically on every Windows login. If the timesheet is already filled for the day, it exits immediately with a notification.

## How It Works

1. On startup, checks `.timesheet_done` — if today's date is recorded, shows a "already done" notification and exits.
2. Opens `https://timesheet.ultimatix.net/timesheet/` in Chrome.
3. Enters your Employee ID (read from `config.toml`) and clicks **Proceed**.
4. Clicks **EasyAuth** and displays the auth number via a Windows toast notification.
5. Waits up to 2 minutes for mobile approval.
6. After login, finds the task based on the `task_name` and `charge_type` specified in `config.toml`.
7. Checks the effort input for the target task:
   - If already `9`, marks the day as done and exits.
   - Otherwise, fills `9`, clicks **Submit**, and marks the day as done.

## Project Structure

```
Timesheet/
├── fill_timesheet.py      # Main automation script
├── setup_startup.py       # Install/uninstall from Windows Startup
├── setup.ps1              # Interactive PowerShell setup script
├── config.toml            # User configuration (Employee ID, Task Name, etc.)
├── example.config.toml    # Template for config.toml
├── launch_silentsheet.vbs # Silent VBS launcher (auto-generated)
├── .timesheet_done        # Tracks last filled date (auto-generated)
├── pyproject.toml         # Project config & dependencies
└── README.md
```

## Configuration

Your credentials and timesheet preferences are stored in `config.toml`. The `setup.ps1` script will generate this for you, but you can edit it manually at any time:

```toml
[employee]
EMPLOYEE_ID = "12345678"

[timesheet]
task_name = "Development"
charge_type = "Billable"
```
