from __future__ import annotations

from pathlib import Path

from .blender import BlenderError, translate_restore
from .contracts import Capability, ExecutionPlan, IntentEnvelope, ResultEnvelope
from .executor import TerminalExecutor
from .models import CommandRequest


MAX_READ_BYTES = 256 * 1024


class CapabilityError(RuntimeError):
    pass


class CapabilityRegistry:
    """Map structured intents to a deliberately small set of bridge capabilities."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        executor: TerminalExecutor | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.executor = executor or TerminalExecutor(
            self.workspace_root,
            source="capability",
        )
        self._capabilities = {
            "files.read": Capability(
                name="files.read",
                description="Read one UTF-8 text file confined to the workspace",
                risk="low",
                mutates=False,
                requires_approval=False,
            ),
            "git.status": Capability(
                name="git.status",
                description="Read git branch and working-tree status inside the workspace",
                risk="low",
                mutates=False,
                requires_approval=False,
            ),
            "blender.object.translate_restore": Capability(
                name="blender.object.translate_restore",
                description="Move one Blender object by a bounded delta, verify it, then restore it without saving",
                risk="elevated",
                mutates=False,
                requires_approval=True,
            ),
        }

    def describe(self) -> tuple[Capability, ...]:
        return tuple(self._capabilities[name] for name in sorted(self._capabilities))

    def plan(self, intent: IntentEnvelope) -> ExecutionPlan:
        capability = self._capabilities.get(intent.intent)
        if capability is None:
            raise CapabilityError(f"unknown intent: {intent.intent}")

        if capability.name == "files.read":
            steps = (
                "resolve target inside configured workspace",
                "verify target is a bounded regular file",
                "read through the audited read-only executor",
                "return content and execution evidence",
            )
        elif capability.name == "git.status":
            steps = (
                "resolve repository target inside configured workspace",
                "run git status --short --branch through the safety policy",
                "return branch and working-tree evidence",
            )
        else:
            steps = (
                "resolve .blend target inside configured workspace",
                "validate explicit approval, object name, and bounded XYZ delta",
                "open Blender in background with fixed generated transaction code",
                "record before and after locations",
                "restore the exact original location and verify restoration",
                "return structured evidence without saving the .blend file",
            )

        return ExecutionPlan(
            request_id=intent.request_id,
            intent=intent.intent,
            capability=capability.name,
            steps=steps,
            risk=capability.risk,
            mutates=capability.mutates,
            requires_approval=capability.requires_approval,
        )

    def execute(self, intent: IntentEnvelope) -> ResultEnvelope:
        plan = self.plan(intent)
        if intent.intent == "files.read":
            return self._read_file(intent, plan)
        if intent.intent == "git.status":
            return self._git_status(intent, plan)
        if intent.intent == "blender.object.translate_restore":
            return self._blender_translate_restore(intent, plan)
        raise CapabilityError(f"unimplemented intent: {intent.intent}")

    def _resolve_target(self, raw: str) -> Path:
        if raw.startswith("~"):
            raise CapabilityError("home expansion is not allowed")

        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate

        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as exc:
            raise CapabilityError(f"target does not exist: {raw}") from exc

        try:
            resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise CapabilityError("target escapes configured workspace") from exc
        return resolved

    def _read_file(
        self,
        intent: IntentEnvelope,
        plan: ExecutionPlan,
    ) -> ResultEnvelope:
        target = self._resolve_target(intent.target)
        if not target.is_file():
            raise CapabilityError("files.read target must be a regular file")
        size = target.stat().st_size
        if size > MAX_READ_BYTES:
            raise CapabilityError(
                f"files.read target exceeds {MAX_READ_BYTES} byte limit"
            )

        relative = target.relative_to(self.workspace_root)
        result = self.executor.execute(
            CommandRequest.from_parts(
                ["cat", "--", str(relative)],
                self.workspace_root,
                timeout_s=30.0,
                approved=False,
                request_id=intent.request_id,
            )
        )
        if result.exit_code != 0 or result.timed_out:
            return ResultEnvelope(
                request_id=intent.request_id,
                status="error",
                capability=intent.intent,
                project=intent.project,
                changed=False,
                summary="file read failed",
                evidence=result.to_dict(),
                plan=plan,
            )

        return ResultEnvelope(
            request_id=intent.request_id,
            status="success",
            capability=intent.intent,
            project=intent.project,
            changed=False,
            summary=f"read {relative}",
            evidence={
                "path": str(relative),
                "bytes": size,
                "encoding": "utf-8",
                "content": result.stdout,
                "execution": result.to_dict(),
            },
            plan=plan,
        )

    def _blender_translate_restore(
        self,
        intent: IntentEnvelope,
        plan: ExecutionPlan,
    ) -> ResultEnvelope:
        target = self._resolve_target(intent.target)
        if not target.is_file() or target.suffix.lower() != ".blend":
            raise CapabilityError("blender target must be an existing .blend file")

        object_name = intent.constraints.get("object")
        delta = intent.constraints.get("delta")
        approved = intent.constraints.get("approved") is True
        timeout_raw = intent.constraints.get("timeout_s", 120.0)
        if isinstance(timeout_raw, bool) or not isinstance(timeout_raw, (int, float)):
            raise CapabilityError("timeout_s must be a number")

        try:
            evidence = translate_restore(
                target,
                object_name=object_name if isinstance(object_name, str) else "",
                delta=delta,
                approved=approved,
                timeout_s=float(timeout_raw),
            ).to_dict()
        except BlenderError as exc:
            raise CapabilityError(str(exc)) from exc

        return ResultEnvelope(
            request_id=intent.request_id,
            status="success",
            capability=intent.intent,
            project=intent.project,
            changed=False,
            summary=f"verified and restored Blender object {evidence['object']}",
            evidence=evidence,
            plan=plan,
        )

    def _git_status(
        self,
        intent: IntentEnvelope,
        plan: ExecutionPlan,
    ) -> ResultEnvelope:
        target = self._resolve_target(intent.target)
        if not target.is_dir():
            raise CapabilityError("git.status target must be a directory")

        result = self.executor.execute(
            CommandRequest.from_parts(
                ["git", "status", "--short", "--branch"],
                target,
                timeout_s=30.0,
                approved=False,
                request_id=intent.request_id,
            )
        )
        evidence = result.to_dict()
        if result.exit_code != 0 or result.timed_out:
            return ResultEnvelope(
                request_id=intent.request_id,
                status="error",
                capability=intent.intent,
                project=intent.project,
                changed=False,
                summary="git status failed",
                evidence=evidence,
                plan=plan,
            )

        lines = result.stdout.splitlines()
        branch_line = lines[0] if lines and lines[0].startswith("##") else ""
        worktree_lines = lines[1:] if branch_line else lines
        dirty = any(line.strip() for line in worktree_lines)
        evidence["branch"] = branch_line[2:].strip() if branch_line else ""
        evidence["worktree_dirty"] = dirty

        return ResultEnvelope(
            request_id=intent.request_id,
            status="success",
            capability=intent.intent,
            project=intent.project,
            changed=False,
            summary="working tree has changes" if dirty else "working tree clean",
            evidence=evidence,
            plan=plan,
        )
