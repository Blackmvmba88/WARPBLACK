from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .capabilities import CapabilityError, CapabilityRegistry
from .contracts import IntentEnvelope
from .desktop import capture_screen, focused_window, frontmost_application, list_windows


ACTION_PROTOCOL = "warpblack-action-v1"


class ActionError(RuntimeError):
    pass


SUPPORTED_ACTIONS = {
    "desktop.frontmost",
    "desktop.windows",
    "desktop.focused_window",
    "desktop.capture",
    "files.read",
    "git.status",
    "blender.object.translate_restore",
    "blender.object.translate_restore_certify",
}


def _reject_unknown_args(action: str, args: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = set(args) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ActionError(f"unsupported args for {action}: {names}")


def _string_arg(args: Mapping[str, Any], name: str, default: str | None = None) -> str:
    value = args.get(name, default)
    if not isinstance(value, str) or not value.strip():
        raise ActionError(f"{name} must be a non-empty string")
    return value.strip()


def _project_arg(args: Mapping[str, Any]) -> str | None:
    value = args.get("project")
    if value is None:
        return None
    if not isinstance(value, str):
        raise ActionError("project must be a string")
    return value


def dispatch_action(
    action: str,
    args: Mapping[str, Any] | None = None,
    *,
    workspace_root: str | Path,
    approved: bool = False,
    request_id: str | None = None,
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
        # Remote jobs intentionally use WARPBLACK's managed temporary output.
        # A remote caller cannot choose an arbitrary filesystem path.
        _reject_unknown_args(action, values, set())
        return capture_screen().to_dict()

    registry = CapabilityRegistry(workspace_root)

    if action in {"files.read", "git.status"}:
        _reject_unknown_args(action, values, {"target", "project"})
        intent = IntentEnvelope.from_payload(
            {
                "intent": action,
                "target": _string_arg(values, "target", "."),
                "project": _project_arg(values),
                "request_id": request_id,
                "constraints": {},
            }
        )
        try:
            try:
        return registry.execute(intent).to_dict()
    except CapabilityError as exc:
        raise ActionError(str(exc)) from exc
        except CapabilityError as exc:
            raise ActionError(str(exc)) from exc

    _reject_unknown_args(
        action,
        values,
        {"target", "project", "object", "delta", "timeout_s"},
    )
    if not approved:
        raise ActionError(f"{action} requires the separate remote approval label")

    target = _string_arg(values, "target")
    object_name = _string_arg(values, "object")
    delta = values.get("delta")
    timeout_s = values.get("timeout_s", 120.0)
    intent = IntentEnvelope.from_payload(
        {
            "intent": action,
            "target": target,
            "project": _project_arg(values),
            "request_id": request_id,
            "constraints": {
                "object": object_name,
                "delta": delta,
                "timeout_s": timeout_s,
                "approved": True,
            },
        }
    )
    return registry.execute(intent).to_dict()
