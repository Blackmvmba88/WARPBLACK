from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path
import platform
import subprocess
import tempfile
from typing import Sequence

from .executor import TerminalExecutor
from .models import CommandRequest


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
        raise DesktopError("BM-DESKTOP currently supports macOS only")


def _run_command(
    argv: Sequence[str],
    *,
    timeout_s: float,
    failure_message: str,
    executor: TerminalExecutor | None = None,
    request_id: str | None = None,
) -> str:
    if executor is not None:
        result = executor.execute(
            CommandRequest.from_parts(
                argv,
                executor.workspace_root,
                timeout_s=timeout_s,
                # The typed desktop capability fixes the executable and arguments.
                # Approval here is capability-internal so TerminalExecutor applies
                # policy and writes the audit record without exposing shell input.
                approved=True,
                request_id=request_id,
            )
        )
        if result.timed_out:
            raise DesktopError("desktop action timed out")
        if result.exit_code != 0:
            message = (result.stderr or result.stdout or failure_message).strip()
            raise DesktopError(message)
        return result.stdout.strip()

    try:
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DesktopError("desktop action timed out") from exc
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or failure_message).strip()
        raise DesktopError(message)
    return completed.stdout.strip()


def _run_osascript(
    lines: Sequence[str],
    *,
    timeout_s: float = 10.0,
    executor: TerminalExecutor | None = None,
    request_id: str | None = None,
) -> str:
    _require_macos()
    argv: list[str] = ["osascript"]
    for line in lines:
        argv.extend(["-e", line])
    return _run_command(
        argv,
        timeout_s=timeout_s,
        failure_message="osascript failed",
        executor=executor,
        request_id=request_id,
    )


def _parse_window_row(raw: str) -> dict[str, object]:
    parts = raw.split("\t", 3)
    if len(parts) != 4:
        raise DesktopError("invalid window identity returned by System Events")
    application, pid_raw, frontmost_raw, title = parts
    try:
        pid = int(pid_raw)
    except ValueError as exc:
        raise DesktopError("invalid process id returned by System Events") from exc
    return {
        "application": application,
        "pid": pid,
        "frontmost": frontmost_raw.strip().lower() == "true",
        "title": title,
    }


def frontmost_application(
    *,
    executor: TerminalExecutor | None = None,
    request_id: str | None = None,
) -> DesktopResult:
    identity = focused_window(executor=executor, request_id=request_id).data
    return DesktopResult(
        True,
        "frontmost",
        {
            "application": identity["application"],
            "pid": identity["pid"],
            "title": identity["title"],
        },
    )


def focused_window(
    *,
    executor: TerminalExecutor | None = None,
    request_id: str | None = None,
) -> DesktopResult:
    raw = _run_osascript([
        'tell application "System Events"',
        'set matches to application processes whose frontmost is true',
        'if (count of matches) is not 1 then error "ambiguous frontmost application"',
        'set p to item 1 of matches',
        'set appName to name of p',
        'set appPid to unix id of p',
        'set windowTitle to ""',
        'if (count of windows of p) > 0 then set windowTitle to name of front window of p as text',
        'return appName & tab & (appPid as text) & tab & "true" & tab & windowTitle',
        'end tell',
    ], executor=executor, request_id=request_id)
    return DesktopResult(True, "focused-window", _parse_window_row(raw))


def list_windows(
    *,
    executor: TerminalExecutor | None = None,
    request_id: str | None = None,
) -> DesktopResult:
    raw = _run_osascript([
        'tell application "System Events"',
        'set output to {}',
        'repeat with p in (application processes whose background only is false)',
        'set appName to name of p',
        'set appPid to unix id of p',
        'set appFrontmost to frontmost of p',
        'repeat with w in windows of p',
        'try',
        'set end of output to appName & tab & (appPid as text) & tab & (appFrontmost as text) & tab & (name of w as text)',
        'end try',
        'end repeat',
        'end repeat',
        'set previousDelimiters to AppleScript\'s text item delimiters',
        'set AppleScript\'s text item delimiters to linefeed',
        'set payload to output as text',
        'set AppleScript\'s text item delimiters to previousDelimiters',
        'return payload',
        'end tell',
    ], executor=executor, request_id=request_id)
    windows: list[dict[str, object]] = []
    if raw:
        windows = [_parse_window_row(row) for row in raw.splitlines() if row.strip()]
    return DesktopResult(True, "windows", {"windows": windows, "errors": []})


def _assert_focused_window(
    *,
    expected_pid: int | None = None,
    expected_title: str | None = None,
    executor: TerminalExecutor | None = None,
    request_id: str | None = None,
) -> dict[str, object]:
    current = focused_window(executor=executor, request_id=request_id).data
    if expected_pid is not None and current["pid"] != expected_pid:
        raise DesktopError(
            f"focused window PID mismatch: expected {expected_pid}, got {current['pid']}"
        )
    if expected_title is not None and current["title"] != expected_title:
        raise DesktopError(
            f"focused window title mismatch: expected {expected_title!r}, got {current['title']!r}"
        )
    return current


def activate_application(name: str, *, approved: bool = False) -> DesktopResult:
    if not approved:
        raise DesktopError("desktop mutation requires explicit approval")
    safe = json.dumps(name)
    _run_osascript([f"tell application {safe} to activate"])
    current = focused_window().data
    return DesktopResult(
        True,
        "activate",
        {"application": name, "focused": current},
    )


def keystroke(
    keys: str,
    *,
    modifiers: Sequence[str] = (),
    approved: bool = False,
    expected_pid: int | None = None,
    expected_title: str | None = None,
) -> DesktopResult:
    if not approved:
        raise DesktopError("desktop mutation requires explicit approval")

    focused = _assert_focused_window(
        expected_pid=expected_pid,
        expected_title=expected_title,
    )

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
        {
            "keys": keys,
            "modifiers": [item.strip().lower() for item in modifiers],
            "target": focused,
        },
    )


def click_at(
    x: int,
    y: int,
    *,
    approved: bool = False,
    expected_pid: int | None = None,
    expected_title: str | None = None,
) -> DesktopResult:
    if not approved:
        raise DesktopError("desktop mutation requires explicit approval")
    if x < 0 or y < 0:
        raise DesktopError("click coordinates must be non-negative")

    focused = _assert_focused_window(
        expected_pid=expected_pid,
        expected_title=expected_title,
    )
    _run_osascript([
        'tell application "System Events"',
        f'click at {{{int(x)}, {int(y)}}}',
        'end tell',
    ])
    return DesktopResult(
        True,
        "click",
        {"x": int(x), "y": int(y), "target": focused},
    )


def capture_screen(
    output: str | Path | None = None,
    *,
    expected_pid: int | None = None,
    expected_title: str | None = None,
    executor: TerminalExecutor | None = None,
    request_id: str | None = None,
) -> DesktopResult:
    _require_macos()
    focused = _assert_focused_window(
        expected_pid=expected_pid,
        expected_title=expected_title,
        executor=executor,
        request_id=request_id,
    )
    if output is None:
        target = Path(tempfile.gettempdir()) / "warpblack-desktop.png"
    else:
        target = Path(output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    _run_command(
        ["screencapture", "-x", str(target)],
        timeout_s=15.0,
        failure_message="screencapture failed",
        executor=executor,
        request_id=request_id,
    )
    return DesktopResult(
        True,
        "capture",
        {"path": str(target), "target": focused},
    )
