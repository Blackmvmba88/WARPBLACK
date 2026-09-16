from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time

from .audit import AuditLedger
from .models import CommandRequest, ExecutionResult
from .policy import PolicyError, require


class TerminalExecutor:
    def __init__(
        self,
        workspace_root: str | Path,
        *,
        audit_ledger: AuditLedger | None = None,
        source: str = "local",
        actor: str | None = None,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.audit_ledger = audit_ledger
        self.source = source
        self.actor = actor

    def execute(self, request: CommandRequest) -> ExecutionResult:
        try:
            decision = require(request, self.workspace_root)
        except PolicyError as exc:
            if self.audit_ledger is not None:
                self.audit_ledger.record_denied(
                    request,
                    reason=str(exc),
                    source=self.source,
                    actor=self.actor,
                )
            raise

        started = time.monotonic()
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", ""),
        }
        env = {key: value for key, value in env.items() if value}

        try:
            completed = subprocess.run(
                list(request.argv),
                cwd=request.cwd.resolve(),
                env=env,
                capture_output=True,
                text=True,
                timeout=request.timeout_s,
                check=False,
                shell=False,
            )
            result = ExecutionResult(
                request_id=request.request_id,
                argv=request.argv,
                cwd=str(request.cwd.resolve()),
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_ms=int((time.monotonic() - started) * 1000),
                timed_out=False,
                policy_reason=decision.reason,
                policy_risk=decision.risk,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            result = ExecutionResult(
                request_id=request.request_id,
                argv=request.argv,
                cwd=str(request.cwd.resolve()),
                exit_code=None,
                stdout=stdout,
                stderr=stderr,
                duration_ms=int((time.monotonic() - started) * 1000),
                timed_out=True,
                policy_reason=decision.reason,
                policy_risk=decision.risk,
            )

        if self.audit_ledger is not None:
            self.audit_ledger.record_result(
                request,
                result,
                source=self.source,
                actor=self.actor,
            )
        return result
