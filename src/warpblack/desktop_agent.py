from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import tempfile
import time
from typing import Sequence
from uuid import uuid4

from .desktop import (
    DesktopError,
    DesktopResult,
    _assert_focused_window,
    _run_osascript,
    capture_screen,
    click_at,
)


ACTIONABLE_ROLES = {
    "AXButton",
    "AXCheckBox",
    "AXRadioButton",
    "AXMenuButton",
    "AXPopUpButton",
    "AXMenuItem",
    "AXLink",
}


@dataclass(frozen=True)
class UIElement:
    role: str
    name: str
    description: str
    x: int
    y: int
    width: int
    height: int

    @property
    def label(self) -> str:
        return self.name or self.description

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["label"] = self.label
        payload["center"] = list(self.center)
        return payload


def _parse_ui_row(raw: str) -> UIElement:
    parts = raw.split("\t", 6)
    if len(parts) != 7:
        raise DesktopError("invalid UI element row returned by System Events")
    role, name, description, x_raw, y_raw, width_raw, height_raw = parts
    try:
        x = int(float(x_raw))
        y = int(float(y_raw))
        width = int(float(width_raw))
        height = int(float(height_raw))
    except ValueError as exc:
        raise DesktopError("invalid UI element geometry returned by System Events") from exc
    return UIElement(
        role=role,
        name=name,
        description=description,
        x=x,
        y=y,
        width=width,
        height=height,
    )


def inspect_ui(
    *,
    expected_pid: int | None = None,
    expected_title: str | None = None,
) -> DesktopResult:
    focused = _assert_focused_window(
        expected_pid=expected_pid,
        expected_title=expected_title,
    )
    raw = _run_osascript([
        'tell application "System Events"',
        'set matches to application processes whose frontmost is true',
        'if (count of matches) is not 1 then error "ambiguous frontmost application"',
        'set p to item 1 of matches',
        'if (count of windows of p) = 0 then return ""',
        'set output to {}',
        'set elems to entire contents of front window of p',
        'repeat with e in elems',
        'try',
        'set roleName to role of e as text',
        'set elemName to ""',
        'try',
        'set elemName to name of e as text',
        'end try',
        'set elemDescription to ""',
        'try',
        'set elemDescription to description of e as text',
        'end try',
        'set elemPosition to position of e',
        'set elemSize to size of e',
        'set end of output to roleName & tab & elemName & tab & elemDescription & tab & (item 1 of elemPosition as text) & tab & (item 2 of elemPosition as text) & tab & (item 1 of elemSize as text) & tab & (item 2 of elemSize as text)',
        'end try',
        'end repeat',
        'set previousDelimiters to AppleScript\'s text item delimiters',
        'set AppleScript\'s text item delimiters to linefeed',
        'set payload to output as text',
        'set AppleScript\'s text item delimiters to previousDelimiters',
        'return payload',
        'end tell',
    ], timeout_s=20.0)

    elements: list[UIElement] = []
    for row in raw.splitlines():
        if row.strip():
            elements.append(_parse_ui_row(row))

    return DesktopResult(
        True,
        "ui-elements",
        {
            "target": focused,
            "elements": [item.to_dict() for item in elements],
        },
    )


def find_ui_elements(
    label: str,
    *,
    exact: bool = False,
    roles: Sequence[str] = (),
    expected_pid: int | None = None,
    expected_title: str | None = None,
) -> list[UIElement]:
    query = label.strip().casefold()
    if not query:
        raise DesktopError("UI label must not be empty")

    payload = inspect_ui(
        expected_pid=expected_pid,
        expected_title=expected_title,
    ).data
    allowed_roles = {item.strip() for item in roles if item.strip()} or ACTIONABLE_ROLES
    matches: list[UIElement] = []

    for raw in payload["elements"]:
        element = UIElement(
            role=str(raw["role"]),
            name=str(raw["name"]),
            description=str(raw["description"]),
            x=int(raw["x"]),
            y=int(raw["y"]),
            width=int(raw["width"]),
            height=int(raw["height"]),
        )
        if element.role not in allowed_roles:
            continue
        candidates = [element.name.casefold(), element.description.casefold()]
        matched = query in candidates if exact else any(query in value for value in candidates)
        if matched:
            matches.append(element)

    if exact:
        return matches

    exact_matches = [
        item for item in matches
        if query in {item.name.casefold(), item.description.casefold()}
    ]
    return exact_matches or matches


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def click_label(
    label: str,
    *,
    exact: bool = False,
    roles: Sequence[str] = (),
    approved: bool = False,
    verify_change: bool = False,
    settle_s: float = 0.15,
    expected_pid: int | None = None,
    expected_title: str | None = None,
) -> DesktopResult:
    if not approved:
        raise DesktopError("desktop mutation requires explicit approval")
    if settle_s < 0 or settle_s > 5:
        raise DesktopError("settle time must be between 0 and 5 seconds")

    focused = _assert_focused_window(
        expected_pid=expected_pid,
        expected_title=expected_title,
    )
    pid = int(focused["pid"])
    title = str(focused["title"])

    matches = find_ui_elements(
        label,
        exact=exact,
        roles=roles,
        expected_pid=pid,
        expected_title=title,
    )
    if not matches:
        raise DesktopError(f"no actionable UI element matched {label!r}")
    if len(matches) > 1:
        labels = [f"{item.role}:{item.label}" for item in matches[:5]]
        raise DesktopError(
            f"ambiguous UI label {label!r}; matched {len(matches)} elements: {labels}"
        )

    target = matches[0]
    if target.width <= 0 or target.height <= 0:
        raise DesktopError(f"matched UI element has invalid geometry: {target.to_dict()}")

    before_path: Path | None = None
    after_path: Path | None = None
    before_hash: str | None = None
    after_hash: str | None = None

    try:
        if verify_change:
            before_path = Path(tempfile.gettempdir()) / f"warpblack-before-{uuid4().hex}.png"
            capture_screen(before_path, expected_pid=pid, expected_title=title)
            before_hash = _sha256(before_path)

        x, y = target.center
        click_result = click_at(
            x,
            y,
            approved=True,
            expected_pid=pid,
            expected_title=title,
        )

        visual_changed: bool | None = None
        if verify_change:
            time.sleep(settle_s)
            post_focus = _assert_focused_window(expected_pid=pid)
            after_path = Path(tempfile.gettempdir()) / f"warpblack-after-{uuid4().hex}.png"
            capture_screen(after_path, expected_pid=pid)
            after_hash = _sha256(after_path)
            visual_changed = before_hash != after_hash
            if not visual_changed:
                raise DesktopError("semantic click completed but visual verification found no screen change")
        else:
            post_focus = _assert_focused_window(expected_pid=pid)

        return DesktopResult(
            True,
            "click-label",
            {
                "query": label,
                "exact": exact,
                "matched": target.to_dict(),
                "click": click_result.data,
                "post_focus": post_focus,
                "verification": {
                    "enabled": verify_change,
                    "visual_changed": visual_changed,
                    "before_sha256": before_hash,
                    "after_sha256": after_hash,
                },
            },
        )
    finally:
        for path in (before_path, after_path):
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
