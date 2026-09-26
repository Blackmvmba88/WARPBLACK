"""BM-BLENDER-001: focused desktop operations with evidence for visual review."""
from __future__ import annotations

import json
import re
import tempfile
import time
from hashlib import sha256
from pathlib import Path

from .desktop import (
    DesktopError,
    DesktopResult,
    _run_osascript,
    activate_application,
    capture_screen,
    focused_window,
)

# Only reversible viewport toggles in this first milestone. The pointer must be
# over the intended Blender editor; evidence still requires human/vision review.
SHORTCUTS = {"toggle-sidebar": "n", "toggle-toolbar": "t"}


def _require_blender() -> dict[str, object]:
    window = focused_window().data
    if window.get("application") != "Blender" or not window.get("frontmost"):
        raise DesktopError("Blender must be frontmost")
    if not window.get("title"):
        raise DesktopError("Blender has no focused window")
    return window


def _capture(directory: Path, name: str) -> dict[str, str]:
    target = directory / name
    capture_screen(target)
    return {"path": str(target), "sha256": sha256(target.read_bytes()).hexdigest()}


def observe() -> DesktopResult:
    window = _require_blender()
    directory = Path(tempfile.mkdtemp(prefix="warpblack-blender-"))
    capture = _capture(directory, "observe.png")
    _require_blender()
    return DesktopResult(True, "blender-observe", {
        "window": window, "capture": capture,
        "initial_scene": "unverified", "visual_verification": "needs-review",
    })


def activate(*, approved: bool = False) -> DesktopResult:
    activate_application("Blender", approved=approved)
    # Activation can return before the window becomes frontmost.
    for _ in range(20):
        try:
            return DesktopResult(True, "blender-activate", {"window": _require_blender()})
        except DesktopError:
            time.sleep(0.1)
    raise DesktopError("Blender did not acquire a focused window after activation")


def shortcut(name: str, *, approved: bool = False) -> DesktopResult:
    if not approved:
        raise DesktopError("desktop mutation requires explicit approval")
    if name not in SHORTCUTS:
        raise DesktopError(f"unsupported Blender shortcut: {name}")
    window = _require_blender()
    title = str(window["title"])
    if not re.search(r" - Blender \d", title):
        raise DesktopError("Blender main editor window required; close dialogs first")
    directory = Path(tempfile.mkdtemp(prefix="warpblack-blender-"))
    before = _capture(directory, "before.png")
    # Check focus again inside the same script that sends the key.
    _run_osascript([f"""
        const se = Application('System Events');
        const p = se.applicationProcesses.whose({{frontmost: true}})()[0];
        if (!p || p.name() !== 'Blender') throw Error('Blender lost focus');
        const w = p.attributes.byName('AXFocusedWindow').value();
        if (!w || w.name() !== {json.dumps(title)}) throw Error('Blender window changed');
        se.keystroke({json.dumps(SHORTCUTS[name])});
    """], language="JavaScript")
    time.sleep(0.3)
    _require_blender()
    after = _capture(directory, "after.png")
    _require_blender()
    return DesktopResult(True, "blender-shortcut", {
        "shortcut": name, "window": window, "before": before, "after": after,
        "capture_bytes_changed": before["sha256"] != after["sha256"],
        "visual_verification": "needs-review",
    })
