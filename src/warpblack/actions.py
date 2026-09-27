from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import blender
from .desktop import (
    DesktopError,
    capture_screen,
    focused_window,
    frontmost_application,
    list_windows,
)


ACTION_PROTOCOL = "warpblack-action-v1"


class ActionError(RuntimeError):
    pass


READ_ONLY_ACTIONS = {
    "desktop.frontmost",
    "desktop.windows",
    "desktop.focused_window",
    "desktop.capture",
    "blender.observe",
}

MUTATING_ACTIONS = {
    "blender.activate",
    "blender.shortcut",
}

SUPPORTED_ACTIONS = READ_ONLY_ACTIONS | MUTATING_ACTIONS


def _reject_unknown_args(action: str, args: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = set(args) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ActionError(f"unsupported args for {action}: {names}")


def dispatch_action(
    action: str,
    args: Mapping[str, Any] | None = None,
    *,
    approved: bool = False,
) -> dict[str, object]:
    if action not in SUPPORTED_ACTIONS:
        raise ActionError(f"unsupported action: {action}")

    values: Mapping[str, Any] = args or {}

    if action == "desktop.frontmost":
        _reject_unknown_args(action, values, set())
        return frontmost_application().to_dict()

    if action == "desktop.windows":
        _reject_unknown_args(action, values, set())
        return list_windows().to_dict()

    if action == "desktop.focused_window":
        _reject_unknown_args(action, values, set())
        return focused_window().to_dict()

    if action == "desktop.capture":
        # Remote typed jobs intentionally choose WARPBLACK's temporary path.
        # Arbitrary caller-supplied filesystem output paths are not accepted.
        _reject_unknown_args(action, values, set())
        return capture_screen().to_dict()

    if action == "blender.observe":
        _reject_unknown_args(action, values, set())
        return blender.observe().to_dict()

    if action == "blender.activate":
        _reject_unknown_args(action, values, set())
        if not approved:
            raise ActionError("blender.activate requires explicit remote approval")
        return blender.activate(approved=True).to_dict()

    if action == "blender.shortcut":
        _reject_unknown_args(action, values, {"name"})
        if not approved:
            raise ActionError("blender.shortcut requires explicit remote approval")
        name = values.get("name")
        if not isinstance(name, str) or name not in blender.SHORTCUTS:
            raise ActionError("blender.shortcut name must be a supported shortcut")
        return blender.shortcut(name, approved=True).to_dict()

    raise ActionError(f"unsupported action: {action}")
