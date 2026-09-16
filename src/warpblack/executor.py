from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time

from .models import CommandRequest, ExecutionResult
from .policy import require


class TerminalExecutor:
    def __init__(self, workspace_root: str | Path):
        self.workspace_root = Path(workspace_root).resolve()

    def execute(self, request: CommandRequest) -> ExecutionResult:
        decision = require(request, self.workspace_root)
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
            duration_ms = int((time.monotonic() - started) * 1000)
            return ExecutionResult(
                argv=request.argv,
                cwd=str(request.cwd.resolve()),
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_ms=duration_ms,
                timed_out=False,
                policy_reason=decision.reason,
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return ExecutionResult(
                argv=request.argv,
                cwd=str(request.cwd.resolve()),
                exit_code=None,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                timed_out=True,
                policy_reason=decision.reason,
            )
