from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path
import platform
import subprocess
import tempfile
from typing import Sequence


class DesktopError(RuntimeError):
    pass


@dataclass(frozen=True)
class DesktopResult:
    ok: bool
    action: str
    data: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _require_macos() -> None:
    if platform.system() != "Darwin":
        raise DesktopError("BM-DESKTOP-001 currently supports macOS only")


def _run_osascript(lines: Sequence[str], *, timeout_s: float = 10.0) -> str:
    _require_macos()
    argv: list[str] = ["osascript"]
    for line in lines:
        argv.extend(["-e", line])
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DesktopError("desktop action timed out") from exc
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "osascript failed").strip()
        raise DesktopError(message)
    return completed.stdout.strip()


def frontmost_application() -> DesktopResult:
    raw = _run_osascript([
        'tell application "System Events"',
        'set p to first application process whose frontmost is true',
        'return name of p',
        'end tell',
    ])
    return DesktopResult(True, "frontmost", {"application": raw})


def list_windows() -> DesktopResult:
    raw = _run_osascript([
        'tell application "System Events"',
        'set output to {}',
        'repeat with p in (application processes whose background only is false)',
        'set appName to name of p',
        'repeat with w in windows of p',
        'try',
        'set end of output to appName & tab & (name of w as text)',
        'end try',
        'end repeat',
        'end repeat',
        'return output as string',
        'end tell',
    ])
    windows: list[dict[str, str]] = []
    if raw:
        for row in raw.replace(", ", "\n").splitlines():
            if "\t" in row:
                app, title = row.split("\t", 1)
                windows.append({"application": app, "title": title})
    return DesktopResult(True, "windows", {"windows": windows})


def activate_application(name: str, *, approved: bool = False) -> DesktopResult:
    if not approved:
        raise DesktopError("desktop mutation requires explicit approval")
    safe = json.dumps(name)
    _run_osascript([f"tell application {safe} to activate"])
    return DesktopResult(True, "activate", {"application": name})


def keystroke(keys: str, *, modifiers: Sequence[str] = (), approved: bool = False) -> DesktopResult:
    if not approved:
        raise DesktopError("desktop mutation requires explicit approval")

    modifier_map = {
        "command": "command down",
        "shift": "shift down",
        "option": "option down",
        "control": "control down",
    }
    normalized: list[str] = []
    for modifier in modifiers:
        key = modifier.strip().lower()
        if key not in modifier_map:
            raise DesktopError(f"unsupported modifier: {modifier}")
        normalized.append(modifier_map[key])

    safe_keys = json.dumps(keys)
    if normalized:
        using = "{" + ", ".join(normalized) + "}"
        command = f"keystroke {safe_keys} using {using}"
    else:
        command = f"keystroke {safe_keys}"

    _run_osascript([
        'tell application "System Events"',
        command,
        'end tell',
    ])
    return DesktopResult(
        True,
        "keystroke",
        {"keys": keys, "modifiers": [item.strip().lower() for item in modifiers]},
    )


def click_at(x: int, y: int, *, approved: bool = False) -> DesktopResult:
    if not approved:
        raise DesktopError("desktop mutation requires explicit approval")
    if x < 0 or y < 0:
        raise DesktopError("click coordinates must be non-negative")
    _run_osascript([
        'tell application "System Events"',
        f'click at {{{int(x)}, {int(y)}}}',
        'end tell',
    ])
    return DesktopResult(True, "click", {"x": int(x), "y": int(y)})


def capture_screen(output: str | Path | None = None) -> DesktopResult:
    _require_macos()
    if output is None:
        target = Path(tempfile.gettempdir()) / "warpblack-desktop.png"
    else:
        target = Path(output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    completed = subprocess.run(
        ["screencapture", "-x", str(target)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "screencapture failed").strip()
        raise DesktopError(message)
    return DesktopResult(True, "capture", {"path": str(target)})
