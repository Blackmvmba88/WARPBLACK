from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .models import CommandRequest, ExecutionResult


class AuditLedger:
    """Append-only JSONL ledger that avoids storing raw stdout/stderr or full argv."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    def record_result(
        self,
        request: CommandRequest,
        result: ExecutionResult,
        *,
        source: str,
        actor: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "event": "execution_result",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request.request_id,
            "source": source,
            "actor": actor,
            "program": Path(request.argv[0]).name,
            "argv_sha256": self._hash_json(list(request.argv)),
            "cwd_sha256": self._hash_text(str(request.cwd.resolve())),
            "approved": request.approved,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "timed_out": result.timed_out,
            "policy_reason": result.policy_reason,
            "policy_risk": result.policy_risk,
            "stdout_sha256": self._hash_text(result.stdout),
            "stderr_sha256": self._hash_text(result.stderr),
        }
        self._append(payload)

    def record_denied(
        self,
        request: CommandRequest,
        *,
        reason: str,
        source: str,
        actor: str | None = None,
    ) -> None:
        self._append(
            {
                "event": "execution_denied",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "request_id": request.request_id,
                "source": source,
                "actor": actor,
                "program": Path(request.argv[0]).name,
                "argv_sha256": self._hash_json(list(request.argv)),
                "cwd_sha256": self._hash_text(str(request.cwd.resolve())),
                "approved": request.approved,
                "reason": reason,
            }
        )

    def _append(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        line = json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n"
        fd = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise

    @staticmethod
    def _hash_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()

    @staticmethod
    def _hash_json(value: object) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return AuditLedger._hash_text(encoded)
