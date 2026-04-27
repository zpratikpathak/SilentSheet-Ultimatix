"""Add/remove SilentSheet from Windows Startup folder or Task Scheduler."""

import getpass
import os
import subprocess
import sys
import tempfile
from pathlib import Path

STARTUP_DIR = Path.home() / r"AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup"
PROJECT_DIR = Path(__file__).resolve().parent
SHORTCUT_DEST = STARTUP_DIR / "launch_silentsheet.vbs"
TASK_VBS_DEST = PROJECT_DIR / "silentsheet_launcher.vbs"
SCHED_TASK_NAME = "SilentSheet"


# ---------------------------------------------------------------------------
# Startup folder method (existing)
# ---------------------------------------------------------------------------

def generate_vbs() -> str:
    """Generate VBS content with paths based on the current machine."""
    python_exe = PROJECT_DIR / ".venv" / "Scripts" / "pythonw.exe"
    script_path = PROJECT_DIR / "fill_timesheet.py"
    # Use chr(34) to safely produce double-quote characters inside VBS strings,
    # avoiding fragile nested-quote escaping entirely.
    # Pass --headless so Chrome runs invisibly on startup.
    # Use True (wait for completion) so Task Scheduler keeps the task "running"
    # and its MultipleInstancesPolicy=IgnoreNew can suppress duplicate triggers.
    return (
        'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.CurrentDirectory = "{PROJECT_DIR}"\n'
        f'WshShell.Run chr(34) & "{python_exe}" & chr(34) & " " & chr(34) & "{script_path}" & chr(34) & " --headless", 0, True\n'
    )


def install_startup() -> None:
    if SHORTCUT_DEST.exists():
        print("Already installed in Startup folder.")
        return
    SHORTCUT_DEST.write_text(generate_vbs())
    print(f"Installed: {SHORTCUT_DEST}")
    print("SilentSheet will now automatically fill your timesheet in background.")


def uninstall_startup() -> None:
    if SHORTCUT_DEST.exists():
        SHORTCUT_DEST.unlink()
        print(f"Removed: {SHORTCUT_DEST}")
        print("SilentSheet will no longer run on startup.")


# ---------------------------------------------------------------------------
# Task Scheduler method (logon + session unlock)
# ---------------------------------------------------------------------------

def _get_current_user() -> str:
    """Return DOMAIN\\Username for the current user."""
    domain = os.environ.get("USERDOMAIN", "")
    username = getpass.getuser()
    return f"{domain}\\{username}" if domain else username


def generate_task_xml() -> str:
    """Build a Task Scheduler XML definition with logon and session-unlock triggers.

    The action launches wscript.exe with a VBS wrapper that runs pythonw.exe
    with window style 0 (hidden), preventing any console flash on unlock.
    """
    user_id = _get_current_user()
    wscript = r"C:\Windows\System32\wscript.exe"

    return f"""\
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>SilentSheet - automatic timesheet fill on logon and unlock</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{user_id}</UserId>
    </LogonTrigger>
    <SessionStateChangeTrigger>
      <Enabled>true</Enabled>
      <UserId>{user_id}</UserId>
      <StateChange>SessionUnlock</StateChange>
    </SessionStateChangeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user_id}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{wscript}</Command>
      <Arguments>//B "{TASK_VBS_DEST}"</Arguments>
      <WorkingDirectory>{PROJECT_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""


def install_logon() -> None:
    TASK_VBS_DEST.write_text(generate_vbs())
    xml_content = generate_task_xml()
    tmp_path = Path(tempfile.gettempdir()) / "silentsheet_task.xml"
    try:
        tmp_path.write_text(xml_content, encoding="utf-16")
        result = subprocess.run(
            ["schtasks", "/create", "/tn", SCHED_TASK_NAME, "/xml", str(tmp_path), "/f"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"Scheduled task '{SCHED_TASK_NAME}' created.")
            print("SilentSheet will now automatically fill your timesheet in background.")
        else:
            print(f"Failed to create scheduled task: {result.stderr.strip()}")
    finally:
        tmp_path.unlink(missing_ok=True)


def uninstall_logon() -> None:
    result = subprocess.run(
        ["schtasks", "/delete", "/tn", SCHED_TASK_NAME, "/f"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"Scheduled task '{SCHED_TASK_NAME}' removed.")
    elif "cannot find" not in result.stderr.lower() and "does not exist" not in result.stderr.lower():
        print(f"Failed to remove scheduled task: {result.stderr.strip()}")
    if TASK_VBS_DEST.exists():
        TASK_VBS_DEST.unlink()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

COMMANDS = {
    "install":           lambda: install_startup(),
    "install-startup":   install_startup,
    "install-logon":     install_logon,
    "uninstall-startup": uninstall_startup,
    "uninstall-logon":   uninstall_logon,
    "uninstall":         lambda: (uninstall_startup(), uninstall_logon()),
    "uninstall-all":     lambda: (uninstall_startup(), uninstall_logon()),
}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        cmds = " | ".join(COMMANDS)
        print(f"Usage: python setup_startup.py [{cmds}]")
        sys.exit(1)

    COMMANDS[sys.argv[1]]()
