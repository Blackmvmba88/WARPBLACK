from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence
from uuid import uuid4


@dataclass(frozen=True)
class CommandRequest:
    argv: tuple[str, ...]
    cwd: Path
    timeout_s: float = 60.0
    approved: bool = False
    request_id: str = ""

    @classmethod
    def from_parts(
        cls,
        argv: Sequence[str],
        cwd: str | Path,
        *,
        timeout_s: float = 60.0,
        approved: bool = False,
        request_id: str | None = None,
    ) -> "CommandRequest":
        if not argv:
            raise ValueError("argv must not be empty")
        correlation_id = request_id or uuid4().hex
        if not correlation_id.strip():
            raise ValueError("request_id must not be empty")
        return cls(tuple(argv), Path(cwd), timeout_s, approved, correlation_id)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    risk: str


@dataclass(frozen=True)
class ExecutionResult:
    request_id: str
    argv: tuple[str, ...]
    cwd: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    policy_reason: str
    policy_risk: str

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["argv"] = list(self.argv)
        return data
