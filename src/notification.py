"""Shared toast notification service using Windows-Toasts.

Provides a unified notify() API for all SilentSheet scripts, with support
for programmatic dismiss — the main reason for migrating away from winotify.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from windows_toasts import (
    InteractableWindowsToaster,
    Toast,
    ToastButton,
    ToastDisplayImage,
    ToastDuration,
    ToastImagePosition,
)
from PIL import Image

__all__ = [
    "notify",
    "dismiss",
    "dismiss_all",
    "set_default_icon",
]

_toaster: InteractableWindowsToaster | None = None
_default_icon: Path | None = None

_DURATION_MAP: dict[str, ToastDuration] = {
    "short": ToastDuration.Short,
    "long": ToastDuration.Long,
}


def _is_aumid_registered(aumid: str) -> bool:
    """Check whether the given AUMID is registered in the Windows registry."""
    try:
        import winreg
        winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            rf"Software\Classes\AppUserModelId\{aumid}",
        ).Close()
        return True
    except Exception:
        return False


_AUMID = "SilentSheet"


def _get_toaster() -> InteractableWindowsToaster:
    """Return (and lazily create) the shared toaster instance."""
    global _toaster
    if _toaster is None:
        aumid = _AUMID if _is_aumid_registered(_AUMID) else None
        _toaster = InteractableWindowsToaster("SilentSheet", notifierAUMID=aumid)
    return _toaster


def set_default_icon(icon_path: Path) -> None:
    """Set the default app icon used for all notifications."""
    global _default_icon
    _default_icon = icon_path


def _ico_to_png(ico_path: Path) -> Path:
    """Convert an ICO file to PNG so toast notifications render it at full size."""
    png_path = Path(tempfile.gettempdir()) / f"{ico_path.stem}.png"
    if png_path.exists() and png_path.stat().st_mtime >= ico_path.stat().st_mtime:
        return png_path
    img = Image.open(ico_path)
    largest = max(img.info.get("sizes", [(img.width, img.height)]))
    img.size = largest
    img = img.resize(largest, Image.LANCZOS)
    img.save(png_path, format="PNG")
    return png_path


def _resolve_icon(icon_path: Path | None) -> Path | None:
    """Resolve an icon path, converting ICO to PNG if needed."""
    if icon_path is None or not icon_path.exists():
        return None
    if icon_path.suffix.lower() == ".ico":
        try:
            return _ico_to_png(icon_path)
        except Exception:
            return icon_path.resolve()
    return icon_path.resolve()


def notify(
    title: str,
    message: str,
    image_path: Path | None = None,
    launch: str | None = None,
    duration: str = "long",
    action_label: str | None = None,
    action_launch: str | None = None,
) -> Toast:
    """Show a Windows toast notification.

    Returns the Toast object so callers can pass it to dismiss() later.
    """
    toaster = _get_toaster()

    toast = Toast(
        text_fields=[title, message],
        duration=_DURATION_MAP.get(duration, ToastDuration.Default),
        launch_action=launch,
    )

    app_logo = _resolve_icon(_default_icon)
    if app_logo is not None:
        toast.AddImage(
            ToastDisplayImage.fromPath(
                str(app_logo), position=ToastImagePosition.AppLogo
            )
        )
    elif image_path is not None:
        resolved = _resolve_icon(image_path)
        if resolved is not None:
            toast.AddImage(
                ToastDisplayImage.fromPath(
                    str(resolved), position=ToastImagePosition.AppLogo
                )
            )

    if action_label and action_launch:
        toast.AddAction(ToastButton(action_label, launch=action_launch))

    toaster.show_toast(toast)
    return toast


def dismiss(toast: Toast) -> None:
    """Remove a specific toast from screen and Action Center."""
    _get_toaster().remove_toast(toast)


def dismiss_all() -> None:
    """Clear all SilentSheet toasts from Action Center."""
    _get_toaster().clear_toasts()
