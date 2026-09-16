from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from warpblack.client import WarpClient


PROTOCOL = "xarvis-warpblack-v1"
EXECUTE_ACTION = "terminal.execute"
HEALTH_ACTION = "terminal.health"
CAPABILITIES_ACTION = "terminal.capabilities"


class XarvisProtocolError(ValueError):
    pass


class XarvisAdapter:
    """Translate a small XarvisCore action envelope into WARPBLACK client calls.

    Elevated approval is deliberately out-of-band. A Xarvis payload cannot grant
    itself approval by setting an ``approved`` field; the trusted caller must pass
    ``approved=True`` to :meth:`handle` after its own operator/policy gate.
    """

    def __init__(self, client: WarpClient):
        self.client = client

    def handle(
        self,
        payload: Mapping[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        protocol = payload.get("protocol")
        if protocol != PROTOCOL:
            raise XarvisProtocolError(f"unsupported protocol: {protocol!r}")

        action = payload.get("action")
        request_id = self._optional_string(payload, "request_id")

        if action == HEALTH_ACTION:
            self._reject_execute_only_fields(payload)
            result = self.client.health()
        elif action == CAPABILITIES_ACTION:
            self._reject_execute_only_fields(payload)
            result = self.client.capabilities()
        elif action == EXECUTE_ACTION:
            result = self._execute(payload, approved=approved, request_id=request_id)
        else:
            raise XarvisProtocolError(f"unsupported action: {action!r}")

        response_request_id = result.get("request_id", request_id)
        return {
            "protocol": PROTOCOL,
            "action": action,
            "ok": bool(result.get("ok", False)),
            "request_id": response_request_id,
            "result": result,
        }

    def _execute(
        self,
        payload: Mapping[str, Any],
        *,
        approved: bool,
        request_id: str | None,
    ) -> dict[str, Any]:
        if "approved" in payload:
            raise XarvisProtocolError(
                "payload approval is forbidden; approval must be supplied out-of-band"
            )

        argv = payload.get("argv")
        if (
            not isinstance(argv, Sequence)
            or isinstance(argv, (str, bytes))
            or not argv
            or any(not isinstance(item, str) or not item for item in argv)
        ):
            raise XarvisProtocolError("argv must be a non-empty array of non-empty strings")

        cwd = payload.get("cwd", ".")
        if not isinstance(cwd, str) or not cwd:
            raise XarvisProtocolError("cwd must be a non-empty string")

        timeout_s = payload.get("timeout_s", 60.0)
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
            raise XarvisProtocolError("timeout_s must be a positive number")
        timeout_value = float(timeout_s)
        if timeout_value <= 0:
            raise XarvisProtocolError("timeout_s must be a positive number")

        return self.client.execute(
            list(argv),
            cwd=cwd,
            timeout_s=timeout_value,
            approved=approved,
            request_id=request_id,
        )

    @staticmethod
    def _optional_string(payload: Mapping[str, Any], key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise XarvisProtocolError(f"{key} must be a non-empty string when present")
        return value

    @staticmethod
    def _reject_execute_only_fields(payload: Mapping[str, Any]) -> None:
        forbidden = {"argv", "cwd", "timeout_s", "approved"}.intersection(payload)
        if forbidden:
            names = ", ".join(sorted(forbidden))
            raise XarvisProtocolError(f"fields not valid for this action: {names}")
