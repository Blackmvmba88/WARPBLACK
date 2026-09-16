from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
from typing import Any

from .audit import AuditLedger
from .executor import TerminalExecutor
from .models import CommandRequest
from .policy import PolicyError


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
                    "capabilities": ["execute", "audit-correlation"],
                    "contract": "READ→PLAN→EXECUTE→READ BACK→COMPARE→CERTIFY",
                },
            )
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/execute":
            self._json(404, {"ok": False, "error": "not found"})
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"ok": False, "error": "invalid content length"})
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._json(413, {"ok": False, "error": "request body size rejected"})
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
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
