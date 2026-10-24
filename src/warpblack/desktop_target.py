"""Fail-closed desktop target resolution (BM-DESKTOP-002).

Resolve the exact PID/title pair before permitting a GUI action. This module
does not activate windows; callers must recheck focus immediately before acting.
"""
from __future__ import annotations

from .desktop import DesktopError, list_windows


def resolve_window(*, pid: int | None = None, title: str | None = None,
                   application: str | None = None) -> dict[str, object]:
    """Return one uniquely identified window or reject ambiguous targets."""
    if pid is None and title is None:
        raise DesktopError("target requires PID or exact window title")
    if pid is not None and (type(pid) is not int or pid <= 0):
        raise DesktopError("target PID must be a positive integer")
    if title is not None and not title.strip():
        raise DesktopError("target title must not be empty")
    windows = list_windows().data["windows"]
    matches = [
        window for window in windows
        if (pid is None or window["pid"] == pid)
        and (title is None or window["title"] == title)
        and (application is None or window["application"] == application)
    ]
    if len(matches) != 1:
        raise DesktopError(
            f"needs-review: target identity {'not found' if not matches else 'ambiguous'}"
        )
    return matches[0]
