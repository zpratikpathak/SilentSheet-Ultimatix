"""One-time script to add/remove SilentSheet from Windows Startup."""

import sys
from pathlib import Path

STARTUP_DIR = Path.home() / r"AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup"
PROJECT_DIR = Path(__file__).resolve().parent
SHORTCUT_DEST = STARTUP_DIR / "launch_silentsheet.vbs"


def generate_vbs() -> str:
    """Generate VBS content with paths based on the current machine."""
    python_exe = PROJECT_DIR / ".venv" / "Scripts" / "pythonw.exe"
    script_path = PROJECT_DIR / "fill_timesheet.py"
    # Use chr(34) to safely produce double-quote characters inside VBS strings,
    # avoiding fragile nested-quote escaping entirely.
    # Pass --headless so Chrome runs invisibly on startup.
    return (
        'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.CurrentDirectory = "{PROJECT_DIR}"\n'
        f'WshShell.Run chr(34) & "{python_exe}" & chr(34) & " " & chr(34) & "{script_path}" & chr(34) & " --headless", 0, False\n'
    )


def install() -> None:
    if SHORTCUT_DEST.exists():
        print("Already installed in Startup folder.")
        return
    SHORTCUT_DEST.write_text(generate_vbs())
    print(f"Installed: {SHORTCUT_DEST}")
    print("SilentSheet will now run automatically on next login.")


def uninstall() -> None:
    if SHORTCUT_DEST.exists():
        SHORTCUT_DEST.unlink()
        print(f"Removed: {SHORTCUT_DEST}")
        print("SilentSheet will no longer run on startup.")
    else:
        print("Not currently installed in Startup folder.")

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("install", "uninstall"):
        print("Usage: uv run python setup_startup.py [install|uninstall]")
        sys.exit(1)

    if sys.argv[1] == "install":
        install()
    else:
        uninstall()
