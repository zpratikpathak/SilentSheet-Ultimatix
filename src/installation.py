"""Conservative, stdlib-only maintenance of archive installations.

ponytail: offline maintenance only: disable autorun and run base Python with app
stopped; do not launch app or protocol links during maintenance. Management lock
serializes maintenance only, not application launches. Dependency changes require fresh setup in a
separate directory; no live environment is ever changed or deleted here.
"""
from __future__ import annotations

import contextlib
import csv
import ctypes
from ctypes import wintypes
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
import urllib.parse
import zipfile

REPOSITORY = "zpratikpathak/SilentSheet-Ultimatix"
# Explicit legacy ownership, never inferred from arbitrary archive contents.
OWNED = frozenset({
    "fill_timesheet.py", "manage.py", "Readme.md", "requirements.txt",
    "pyproject.toml", "example.config.toml", "install.ps1", "setup.ps1",
    "uninstall.ps1", "favicon.ico",
    *("src/" + name for name in (
        "browser_session.py", "config_manager.py", "error_logger.py",
        "notification.py", "scrape_tasks.py", "setup_startup.py",
        "setup_workflow.py", "timesheet_common.py", "installation.py",
        "choose_task.ps1", "task_workflow.ps1",
    )),
})
REQUIRED = {"fill_timesheet.py", "requirements.txt", "pyproject.toml", "manage.py",
            "src/installation.py", "src/setup_workflow.py", "src/setup_startup.py",
            "src/choose_task.ps1", "src/task_workflow.ps1"}
LIMIT = 256 * 1024 * 1024


def _root(root: Path) -> Path:
    root = Path(root).absolute()
    for path in (root, *root.parents):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise RuntimeError(f"Linked installation path refused: {path}")
        if (path / ".git").exists():
            raise RuntimeError("Git checkout refused; use Git maintenance instead")
    if not root.is_dir() or not (root / "fill_timesheet.py").is_file():
        raise RuntimeError("Not a SilentSheet installation")
    return root.resolve()


def _plain(path: Path, root: Path) -> None:
    for item in (path, *path.parents):
        if item == root:
            break
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise RuntimeError(f"Linked path refused: {item}")
    if path.exists() and not path.is_file():
        raise RuntimeError(f"Expected regular file: {path}")


@contextlib.contextmanager
def _lock(root: Path):
    # Exclusive creation: a crash leaves a fail-closed lock, never auto-stolen.
    path = root / ".silentsheet-management.lock"
    with path.open("x", encoding="ascii") as stream:
        stream.write(str(os.getpid()))
        stream.flush()
        try:
            yield
        finally:
            stream.close()
            path.unlink()


def _idle(root: Path) -> None:
    """Refuse rather than kill processes or guess ownership of registrations."""
    if os.name != "nt":
        raise RuntimeError("Maintenance supports Windows only")
    if Path(sys.prefix).resolve() == (root / ".venv").resolve():
        raise RuntimeError("Run manage.py using base Python outside installation .venv")
    startup = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/launch_silentsheet.vbs"
    if startup.exists():
        raise RuntimeError("Remove SilentSheet Startup registration before maintenance")
    result = subprocess.run(
        ["schtasks.exe", "/query", "/fo", "CSV", "/nh"],
        check=True, capture_output=True, text=True, timeout=30,
    )
    if any(row and row[0].strip("\\").casefold() == "silentsheet"
           for row in csv.reader(io.StringIO(result.stdout))):
        raise RuntimeError("Remove SilentSheet scheduled task before maintenance")
    _no_python_processes(root)


def _no_python_processes(root: Path) -> None:
    result = subprocess.run(
        ["tasklist.exe", "/fo", "csv", "/nh"],
        check=True, capture_output=True, text=True, timeout=30,
    )
    candidates = []
    for row in csv.reader(io.StringIO(result.stdout)):
        if row and row[0].casefold() in {"python.exe", "pythonw.exe", "wscript.exe", "cscript.exe"}:
            candidates.append((int(row[1]), row[0].casefold()))
    # ponytail: executable ownership only; external Python running app scripts
    # requires operator-enforced offline mode. Add command-line inspection for live maintenance.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    for pid, image in candidates:
        if pid in (0, os.getpid()):
            continue
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            # Only inaccessible interpreter candidates fail closed.
            raise RuntimeError(f"Cannot verify process {pid}; maintenance refused")
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                raise RuntimeError(f"Cannot verify process {pid}; maintenance refused")
            executable = Path(buffer.value).resolve()
            if executable.is_relative_to(root) or image in ("wscript.exe", "cscript.exe"):
                raise RuntimeError(f"Close interpreter/script process {pid} before maintenance")
        finally:
            kernel.CloseHandle(handle)


def _download(url: str, limit: int = LIMIT) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "SilentSheet-maintenance"})
    with urllib.request.urlopen(request, timeout=60) as response:
        final = urllib.parse.urlsplit(response.url)
        if final.scheme != "https" or final.hostname not in {"api.github.com", "codeload.github.com"}:
            raise RuntimeError("Untrusted download redirect")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("Download exceeds safety limit")
    return data


def _archive() -> bytes:
    info = json.loads(_download(f"https://api.github.com/repos/{REPOSITORY}/commits/home", 1024 * 1024))
    commit = info.get("sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("Invalid GitHub commit")
    return _download(f"https://codeload.github.com/{REPOSITORY}/zip/{commit}")


def _extract(data: bytes, stage: Path) -> set[str]:
    selected = set()
    seen = set()
    wrapper = None
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > 20000:
            raise RuntimeError("Archive contains too many entries")
        for entry in archive.infolist():
            raw = entry.orig_filename
            parts = raw.rstrip("/").split("/")
            if (not raw or "\\" in raw or any(
                p in ("", ".", "..") or p.endswith((" ", ".")) or
                any(ord(c) < 32 or c in ':<>"|?*' for c in p) or
                p.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
                for p in parts
            )):
                raise RuntimeError(f"Unsafe archive path: {raw!r}")
            mode = entry.external_attr >> 16
            if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise RuntimeError("Archive links/special files refused")
            key = "/".join(parts).casefold()
            if key in seen:
                raise RuntimeError("Duplicate archive path")
            seen.add(key)
            wrapper = wrapper or parts[0]
            if parts[0] != wrapper:
                raise RuntimeError("Archive must have one root directory")
            total += entry.file_size
            if total > LIMIT:
                raise RuntimeError("Expanded archive exceeds safety limit")
            relative = str(PurePosixPath(*parts[1:]))
            if relative.startswith("src/") and relative.endswith(".py") and relative not in OWNED:
                raise RuntimeError(f"Unreviewed application module: {relative}")
            if relative not in OWNED or entry.is_dir():
                continue
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, destination.open("xb") as target:
                shutil.copyfileobj(source, target)
            selected.add(relative)
    if not REQUIRED <= selected:
        raise RuntimeError("Archive missing required application files")
    for name in selected:
        if name.endswith(".py"):
            compile((stage / name).read_bytes(), name, "exec")
        elif name.endswith(".toml"):
            tomllib.loads((stage / name).read_text(encoding="utf-8"))
    return selected


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(target.read_bytes()).digest():
        raise RuntimeError(f"Backup/copy verification failed: {source}")


def _replace(root: Path, stage: Path, incoming: set[str], remove: set[str]) -> Path:
    names = incoming | remove
    for name in names:
        _plain(root / name, root)
    backup = Path(tempfile.mkdtemp(prefix="silentsheet-backup-"))
    existing = {name for name in names if (root / name).exists()}
    # Full verified snapshot before first mutation. Environment untouched.
    for name in existing:
        _copy(root / name, backup / name)
    (backup / "manifest.json").write_text(json.dumps({"root": str(root), "existing": sorted(existing), "incoming": sorted(incoming)}), encoding="utf-8")
    changed = []
    created_dirs = set()
    try:
        for name in sorted(names):
            target = root / name
            if not target.parent.exists():
                created_dirs.add(target.parent)
            changed.append(name)
            if name in incoming:
                _copy(stage / name, target)
            else:
                target.unlink(missing_ok=True)
    except BaseException as error:
        failures = []
        for name in reversed(changed):
            try:
                if name in existing:
                    _copy(backup / name, root / name)
                else:
                    (root / name).unlink(missing_ok=True)
            except (OSError, RuntimeError) as restore_error:
                failures.append(str(restore_error))
        for directory in created_dirs:
            try:
                directory.rmdir()
            except OSError:
                pass
        raise RuntimeError(f"Maintenance failed: {error}; backup: {backup}; rollback errors: {failures}") from error
    return backup


def update(root: Path, silent: bool = False) -> int:
    root = _root(root)
    with _lock(root):
        _idle(root)
        with tempfile.TemporaryDirectory(prefix="silentsheet-stage-") as directory:
            stage = Path(directory)
            incoming = _extract(_archive(), stage)
            for name in ("requirements.txt", "pyproject.toml"):
                _plain(root / name, root)
                if not (root / name).is_file():
                    raise RuntimeError("Dependency metadata missing; use fresh setup in separate directory")
            with (root / "pyproject.toml").open("rb") as stream:
                current = tomllib.load(stream)["project"]
            with (stage / "pyproject.toml").open("rb") as stream:
                proposed = tomllib.load(stream)["project"]
            if ((root / "requirements.txt").read_bytes() != (stage / "requirements.txt").read_bytes()
                    or any(current.get(key) != proposed.get(key)
                           for key in ("requires-python", "dependencies"))):
                raise RuntimeError("Dependency metadata changed; use fresh setup in separate directory")
            # ponytail: explicit legacy ownership only; new modules require review
            # and an OWNED allowlist update, not trust in downloaded file names.
            _idle(root)
            backup = _replace(root, stage, incoming, set(OWNED) - incoming)
    print(f"Updated application files. Backup: {backup}. Environment and user state unchanged.")
    return 0


def uninstall(root: Path, purge: bool = False, yes: bool = False) -> int:
    root = _root(root)
    with _lock(root):
        _idle(root)
        remove = {name for name in OWNED if (root / name).exists()}
        if purge:
            # Unknown log/runtime contents are user state, never recursively erased.
            print(f"Purge deletes only: {root / 'config.toml'}. Logs/runtime/environment remain.")
            if not yes and input("Delete config.toml? Type DELETE: ") != "DELETE":
                raise RuntimeError("Purge cancelled")
            remove.add("config.toml")
        backup = _replace(root, root, set(), remove)
    print(f"Removed owned application files. Backup: {backup}. Logs/runtime/.venv retained.")
    return 0