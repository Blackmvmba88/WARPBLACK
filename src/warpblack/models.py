from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class CommandRequest:
    argv: tuple[str, ...]
    cwd: Path
    timeout_s: float = 60.0
    approved: bool = False

    @classmethod
    def from_parts(
        cls,
        argv: Sequence[str],
        cwd: str | Path,
        *,
        timeout_s: float = 60.0,
        approved: bool = False,
    ) -> "CommandRequest":
        if not argv:
            raise ValueError("argv must not be empty")
        return cls(tuple(argv), Path(cwd), timeout_s, approved)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    risk: str


@dataclass(frozen=True)
class ExecutionResult:
    argv: tuple[str, ...]
    cwd: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    policy_reason: str

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["argv"] = list(self.argv)
        return data
