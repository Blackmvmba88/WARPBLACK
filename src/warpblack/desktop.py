from __future__ import annotations

import json
import platform
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path


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


def _run_osascript(
    lines: Sequence[str], *, timeout_s: float = 10.0, language: str = "AppleScript"
) -> str:
    _require_macos()
    argv: list[str] = ["osascript", "-l", language]
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


def _desktop_json(script: str) -> dict[str, object]:
    raw = _run_osascript([script], language="JavaScript")
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DesktopError("invalid desktop JSON response") from exc
    if not isinstance(result, dict):
        raise DesktopError("invalid desktop response object")
    return result


def list_windows() -> DesktopResult:
    # JSON preserves commas, tabs, newlines and Unicode in application/window names.
    data = _desktop_json("""
        const se = Application('System Events');
        const windows = [];
        const errors = [];
        for (const p of se.applicationProcesses.whose({backgroundOnly: false})()) {
            const application = p.name();
            try {
                for (const w of p.windows()) {
                    windows.push({application: application, title: w.name()});
                }
            } catch (e) {
                errors.push({application: application, error: String(e)});
            }
        }
        JSON.stringify({windows: windows, errors: errors});
    """)
    return DesktopResult(not bool(data.get("errors")), "windows", data)


def focused_window() -> DesktopResult:
    # Native process references remain distinct when several Blender instances run.
    raw = _run_osascript(["""
use framework "Foundation"
use scripting additions
set appName to missing value
set windowTitle to missing value
set atFront to false
tell application "System Events"
    set ps to application processes whose frontmost is true
    if (count ps) > 0 then
        set p to item 1 of ps
        set appName to name of p
        set atFront to frontmost of p
        if (count windows of p) > 0 then
            set w to value of attribute "AXFocusedWindow" of p
            if w is not missing value then set windowTitle to name of w
        end if
    end if
end tell
set payload to current application's NSMutableDictionary's dictionary()
set nullValue to current application's NSNull's |null|()
if appName is missing value then set appName to nullValue
if windowTitle is missing value then set windowTitle to nullValue
payload's setObject:appName forKey:"application"
payload's setObject:windowTitle forKey:"title"
payload's setObject:atFront forKey:"frontmost"
set encoded to current application's NSJSONSerialization's dataWithJSONObject:payload options:0 |error|:(missing value)
return (current application's NSString's alloc()'s initWithData:encoded encoding:4) as text
    """])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DesktopError("invalid focused-window JSON response") from exc
    if not isinstance(data, dict):
        raise DesktopError("invalid focused-window response object")
    return DesktopResult(True, "focused-window", data)


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
