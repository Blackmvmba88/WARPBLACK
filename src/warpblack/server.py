from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
import threading
from typing import Any

from .audit import AuditLedger
from .construct import PatchConstructor
from .executor import TerminalExecutor
from .models import CommandRequest
from .policy import PolicyError
from .readme_absorb import ReadmeAbsorber


MAX_BODY_BYTES = 64 * 1024


@dataclass(frozen=True)
class BridgeConfig:
    workspace_root: Path
    token: str
    host: str = "127.0.0.1"
    port: int = 8765
    audit_log: Path | None = None

    def __post_init__(self) -> None:
        if self.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("WARPBLACK bridge only binds to loopback addresses")
        if len(self.token) < 24:
            raise ValueError("WARPBLACK token must be at least 24 characters")
        if not (0 <= self.port <= 65535):
            raise ValueError("port must be between 0 and 65535")


class WarpHTTPServer(ThreadingHTTPServer):
    def __init__(self, config: BridgeConfig):
        self.config = config
        ledger = AuditLedger(config.audit_log) if config.audit_log is not None else None
        self.executor = TerminalExecutor(
            config.workspace_root,
            audit_ledger=ledger,
            source="http",
        )
        self.readme_absorber = ReadmeAbsorber(config.workspace_root)
        self.constructor = PatchConstructor(
            config.workspace_root,
            executor=self.executor,
            absorber=self.readme_absorber,
        )
        self.readme_lock = threading.Lock()
        self.construct_lock = threading.Lock()
        super().__init__((config.host, config.port), WarpRequestHandler)


class WarpRequestHandler(BaseHTTPRequestHandler):
    server: WarpHTTPServer

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not header.startswith(prefix):
            return False
        return hmac.compare_digest(header[len(prefix) :], self.server.config.token)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/v1/health":
            self._json(
                200,
                {
                    "ok": True,
                    "service": "warpblack",
                    "protocol": "v1",
                    "bind": "loopback-only",
                },
            )
            return
        if self.path == "/v1/capabilities":
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            self._json(
                200,
                {
                    "ok": True,
                    "capabilities": ["execute", "audit-correlation", "readme-absorb", "construct-patch"],
                    "contract": "READ→PLAN→EXECUTE→READ BACK→COMPARE→CERTIFY",
                },
            )
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/v1/execute", "/v1/readme/absorb", "/v1/construct"}:
            self._json(404, {"ok": False, "error": "not found"})
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return

        try:
            max_bytes = MAX_BODY_BYTES if self.path != "/v1/construct" else 768 * 1024
            payload = self._read_json_body(max_bytes=max_bytes)
            if self.path == "/v1/readme/absorb":
                body = self._absorb_readme(payload)
                self._json(200, body)
                return
            if self.path == "/v1/construct":
                body = self._construct(payload)
                self._json(200, body)
                return
            request = self._request_from_payload(payload)
            result = self.server.executor.execute(request)
        except (TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return
        except PolicyError as exc:
            self._json(403, {"ok": False, "error": str(exc)})
            return
        except (FileNotFoundError, PermissionError, OSError) as exc:
            self._json(422, {"ok": False, "error": str(exc)})
            return

        body = result.to_dict()
        body["ok"] = result.exit_code == 0 and not result.timed_out
        self._json(200 if body["ok"] else 409, body)

    def _read_json_body(self, *, max_bytes: int = MAX_BODY_BYTES) -> object:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid content length") from exc
        if length <= 0 or length > max_bytes:
            raise ValueError("request body size rejected")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _absorb_readme(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise TypeError("request body must be a JSON object")
        message = payload.get("message")
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        project_name = payload.get("project_name")
        if project_name is not None and not isinstance(project_name, str):
            raise TypeError("project_name must be a string")

        classified: dict[str, list[str]] = {}
        for key in ("confirmed", "derived", "proposed"):
            value = payload.get(key, [])
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise TypeError(f"{key} must be a list of strings")
            classified[key] = value

        with self.server.readme_lock:
            result = self.server.readme_absorber.ingest(
                message=message,
                project_name=project_name,
                confirmed=classified["confirmed"],
                derived=classified["derived"],
                proposed=classified["proposed"],
            )
        return result.to_dict()

    def _construct(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise TypeError("request body must be a JSON object")
        message = payload.get("message")
        objective = payload.get("objective")
        patch = payload.get("patch")
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        if not isinstance(objective, str):
            raise TypeError("objective must be a string")
        if not isinstance(patch, str):
            raise TypeError("patch must be a string")

        raw_checks = payload.get("checks", [])
        if not isinstance(raw_checks, list):
            raise TypeError("checks must be a list of argv lists")
        checks: list[list[str]] = []
        for item in raw_checks:
            if not isinstance(item, list) or not all(isinstance(arg, str) for arg in item):
                raise TypeError("each check must be a list of strings")
            checks.append(item)

        timeout_s = payload.get("timeout_s", 120.0)
        if not isinstance(timeout_s, (int, float)):
            raise TypeError("timeout_s must be numeric")
        task_id = payload.get("task_id")
        if task_id is not None and not isinstance(task_id, str):
            raise TypeError("task_id must be a string")

        with self.server.construct_lock:
            result = self.server.constructor.construct(
                message=message,
                objective=objective,
                patch=patch,
                checks=checks,
                timeout_s=float(timeout_s),
                task_id=task_id,
            )
        return result.to_dict()

    def _request_from_payload(self, payload: object) -> CommandRequest:
        if not isinstance(payload, dict):
            raise TypeError("request body must be a JSON object")
        argv = payload.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
            raise TypeError("argv must be a non-empty list of strings")
        cwd_value = payload.get("cwd", ".")
        if not isinstance(cwd_value, str):
            raise TypeError("cwd must be a string")
        timeout_s = payload.get("timeout_s", 60.0)
        if not isinstance(timeout_s, (int, float)):
            raise TypeError("timeout_s must be numeric")
        approved = payload.get("approved", False)
        if not isinstance(approved, bool):
            raise TypeError("approved must be boolean")
        request_id = payload.get("request_id")
        if request_id is not None and not isinstance(request_id, str):
            raise TypeError("request_id must be a string")

        root = self.server.config.workspace_root.resolve()
        cwd = Path(cwd_value)
        if not cwd.is_absolute():
            cwd = root / cwd
        return CommandRequest.from_parts(
            argv,
            cwd,
            timeout_s=float(timeout_s),
            approved=approved,
            request_id=request_id,
        )


def serve(config: BridgeConfig) -> None:
    with WarpHTTPServer(config) as server:
        server.serve_forever(poll_interval=0.25)
