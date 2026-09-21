from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Sequence
from uuid import uuid4

from .executor import TerminalExecutor
from .models import CommandRequest, ExecutionResult
from .readme_absorb import ReadmeAbsorber


CONSTRUCT_TRIGGERS = ("construyelo", "construye lo")
MAX_PATCH_BYTES = 512 * 1024
MAX_CHECKS = 8


def _normalized_text(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value)
    asciiish = "".join(ch for ch in folded if not unicodedata.combining(ch))
    lowered = asciiish.casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", lowered).split())


def has_construct_trigger(message: str) -> bool:
    normalized = _normalized_text(message)
    return any(trigger in normalized for trigger in CONSTRUCT_TRIGGERS)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_patch_path(raw: str) -> bool:
    if raw == "/dev/null":
        return True
    value = raw
    if value.startswith(("a/", "b/")):
        value = value[2:]
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        return False
    if not path.parts:
        return False
    return path.parts[0] not in {".git", ".warpblack"}


def _patch_paths(patch: str) -> list[str]:
    paths: list[str] = []
    for line in patch.splitlines():
        if not line.startswith(("--- ", "+++ ")):
            continue
        raw = line[4:].split("\t", 1)[0].strip()
        if raw == "/dev/null":
            continue
        if not _safe_patch_path(raw):
            raise ValueError(f"patch path is not allowed: {raw}")
        value = raw[2:] if raw.startswith(("a/", "b/")) else raw
        if value not in paths:
            paths.append(value)
    if not paths:
        raise ValueError("patch does not contain file paths")
    return paths


def _validate_checks(checks: Sequence[Sequence[str]]) -> list[list[str]]:
    if len(checks) > MAX_CHECKS:
        raise ValueError(f"at most {MAX_CHECKS} checks are allowed")
    normalized: list[list[str]] = []
    for argv in checks:
        command = list(argv)
        if not command or not all(isinstance(item, str) and item.strip() for item in command):
            raise ValueError("each check must be a non-empty argv list of non-empty strings")
        normalized.append(command)
    return normalized


@dataclass(frozen=True)
class ConstructResult:
    task_id: str
    status: str
    objective: str
    patch_sha256: str
    context_sha256: str
    changed_paths: tuple[str, ...]
    manifest_file: str
    patch_file: str
    apply_check: ExecutionResult
    apply_result: ExecutionResult | None
    checks: tuple[ExecutionResult, ...]
    diff_stat: ExecutionResult | None

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.status == "done",
            "task_id": self.task_id,
            "status": self.status,
            "objective": self.objective,
            "patch_sha256": self.patch_sha256,
            "context_sha256": self.context_sha256,
            "changed_paths": list(self.changed_paths),
            "manifest_file": self.manifest_file,
            "patch_file": self.patch_file,
            "apply_check": self.apply_check.to_dict(),
            "apply_result": self.apply_result.to_dict() if self.apply_result else None,
            "checks": [item.to_dict() for item in self.checks],
            "diff_stat": self.diff_stat.to_dict() if self.diff_stat else None,
        }


class PatchConstructor:
    """Apply an AI-produced patch through WARPBLACK's policy/execution boundary."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        executor: TerminalExecutor | None = None,
        absorber: ReadmeAbsorber | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.executor = executor or TerminalExecutor(self.workspace_root, source="construct")
        self.absorber = absorber or ReadmeAbsorber(self.workspace_root)

    def _execute(
        self,
        argv: Sequence[str],
        *,
        timeout_s: float,
        request_id: str,
        approved: bool,
    ) -> ExecutionResult:
        return self.executor.execute(
            CommandRequest.from_parts(
                argv,
                self.workspace_root,
                timeout_s=timeout_s,
                approved=approved,
                request_id=request_id,
            )
        )

    def _context_text(self, objective: str) -> str:
        state = self.absorber.load()
        confirmed = state["confirmed"]
        derived = state["derived"]
        proposed = state["proposed"]
        assert isinstance(confirmed, list)
        assert isinstance(derived, list)
        assert isinstance(proposed, list)

        def bullets(items: list[str]) -> str:
            return "\n".join(f"- {item}" for item in items) if items else "- none"

        return (
            f"# Construct Context\n\n"
            f"## Objective\n\n{objective}\n\n"
            f"## Confirmed\n\n{bullets(confirmed)}\n\n"
            f"## Derived\n\n{bullets(derived)}\n\n"
            f"## Proposed (unconfirmed)\n\n{bullets(proposed)}\n"
        )

    def construct(
        self,
        *,
        message: str,
        objective: str,
        patch: str,
        checks: Sequence[Sequence[str]] = (),
        timeout_s: float = 120.0,
        task_id: str | None = None,
    ) -> ConstructResult:
        if not has_construct_trigger(message):
            raise ValueError("construct requires the explicit 'constrúyelo' trigger")
        objective = objective.strip()
        if not objective:
            raise ValueError("objective must not be empty")
        if not patch.strip():
            raise ValueError("patch must not be empty")
        if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
            raise ValueError("patch exceeds maximum size")
        if timeout_s <= 0 or timeout_s > 900:
            raise ValueError("timeout must be between 0 and 900 seconds")

        changed_paths = tuple(_patch_paths(patch))
        normalized_checks = _validate_checks(checks)
        task = task_id or uuid4().hex
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", task):
            raise ValueError("task_id contains unsupported characters")

        task_dir = self.workspace_root / ".warpblack" / "tasks" / task
        task_dir.mkdir(parents=True, exist_ok=False)
        patch_path = task_dir / "change.patch"
        context_path = task_dir / "CONTEXT.md"
        manifest_path = task_dir / "task.json"

        context = self._context_text(objective)
        patch_path.write_text(patch, encoding="utf-8")
        context_path.write_text(context, encoding="utf-8")

        manifest = {
            "protocol": "warpblack-construct-v1",
            "task_id": task,
            "objective": objective,
            "patch_sha256": _sha256_text(patch),
            "context_sha256": _sha256_text(context),
            "changed_paths": list(changed_paths),
            "checks": normalized_checks,
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        patch_rel = str(patch_path.relative_to(self.workspace_root))
        apply_check = self._execute(
            ["git", "apply", "--check", patch_rel],
            timeout_s=timeout_s,
            request_id=f"{task}:apply-check",
            approved=True,
        )
        if apply_check.exit_code != 0 or apply_check.timed_out:
            return ConstructResult(
                task_id=task,
                status="rejected",
                objective=objective,
                patch_sha256=manifest["patch_sha256"],
                context_sha256=manifest["context_sha256"],
                changed_paths=changed_paths,
                manifest_file=str(manifest_path),
                patch_file=str(patch_path),
                apply_check=apply_check,
                apply_result=None,
                checks=(),
                diff_stat=None,
            )

        apply_result = self._execute(
            ["git", "apply", patch_rel],
            timeout_s=timeout_s,
            request_id=f"{task}:apply",
            approved=True,
        )
        if apply_result.exit_code != 0 or apply_result.timed_out:
            return ConstructResult(
                task_id=task,
                status="failed-apply",
                objective=objective,
                patch_sha256=manifest["patch_sha256"],
                context_sha256=manifest["context_sha256"],
                changed_paths=changed_paths,
                manifest_file=str(manifest_path),
                patch_file=str(patch_path),
                apply_check=apply_check,
                apply_result=apply_result,
                checks=(),
                diff_stat=None,
            )

        check_results: list[ExecutionResult] = []
        status = "done"
        for index, argv in enumerate(normalized_checks, start=1):
            result = self._execute(
                argv,
                timeout_s=timeout_s,
                request_id=f"{task}:check-{index}",
                approved=True,
            )
            check_results.append(result)
            if result.exit_code != 0 or result.timed_out:
                status = "needs-review"
                break

        diff_stat = self._execute(
            ["git", "diff", "--stat"],
            timeout_s=min(timeout_s, 60.0),
            request_id=f"{task}:diff-stat",
            approved=False,
        )
        return ConstructResult(
            task_id=task,
            status=status,
            objective=objective,
            patch_sha256=manifest["patch_sha256"],
            context_sha256=manifest["context_sha256"],
            changed_paths=changed_paths,
            manifest_file=str(manifest_path),
            patch_file=str(patch_path),
            apply_check=apply_check,
            apply_result=apply_result,
            checks=tuple(check_results),
            diff_stat=diff_stat,
        )
