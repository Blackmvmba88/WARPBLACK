"""Fail-closed, replay-safe read-only Git canary for the modular runtime.

Observer/planner supply a TaskEnvelopeV1. Only the existing typed git.status
capability may execute. This module never accepts an argv or approval from a task.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .actions import ActionError, dispatch_action
from .audit import AuditLedger
from .executor import TerminalExecutor
from .project_registry import DEFAULT_PROJECTS_FILE, ProjectRegistry
from .task_envelope import TaskEnvelopeV1


DEFAULT_STATE_DIR = "~/.warpblack/modular-canary"


def _json_bytes(value: object) -> bytes:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return encoded.encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    """Exclusive + durable write: result and claim records are immutable."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(_json_bytes(payload) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_record(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            record = json.load(handle)
        return record if isinstance(record, dict) else None
    except (FileNotFoundError, OSError, UnicodeError, ValueError):
        return None


def _safe_result(result: dict[str, Any], request_id: str) -> tuple[str, str, bool] | None:
    """Verify both the typed capability and its audited low-risk execution."""
    if (result.get("request_id") != request_id or result.get("status") != "success"
            or result.get("capability") != "git.status" or result.get("changed") is not False):
        return None
    plan = result.get("plan")
    evidence = result.get("evidence")
    if not isinstance(plan, dict) or not isinstance(evidence, dict):
        return None
    if (plan.get("capability") != "git.status" or plan.get("mutates") is not False
            or plan.get("requires_approval") is not False):
        return None
    if (evidence.get("request_id") != request_id or evidence.get("exit_code") != 0
            or evidence.get("timed_out") is not False or evidence.get("policy_risk") != "low"):
        return None
    stdout, branch, dirty = (evidence.get("stdout"), evidence.get("branch"),
                             evidence.get("worktree_dirty"))
    if not isinstance(stdout, str) or not isinstance(branch, str) or not isinstance(dirty, bool):
        return None
    return _sha256(stdout.encode("utf-8")), branch, dirty


def run_git_status_canary(
    task: TaskEnvelopeV1,
    *,
    workspace_root: str | Path,
    projects_file: str | Path = DEFAULT_PROJECTS_FILE,
    state_dir: str | Path = DEFAULT_STATE_DIR,
    executor: TerminalExecutor | None = None,
) -> dict[str, Any]:
    """Run one registered-project Git status twice and certify matching read-backs.

    An existing claim with no result represents an unknown interrupted outcome:
    never retry it automatically, even though the current capability is read-only.
    """
    # Re-validate even if callers constructed the frozen dataclass directly.
    task = TaskEnvelopeV1.parse(asdict(task))
    if task.state != "PROPOSED" or task.risk != "read_only":
        raise ValueError("canary requires a proposed read-only task")
    if task.intent != "git.status" or task.approval_ref is not None:
        raise ValueError("canary accepts only git.status with no approval reference")

    root = Path(workspace_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("workspace root must be a directory")
    entry = ProjectRegistry(projects_file).get(task.workspace_id)
    if entry.status != "active":
        raise ValueError("registered project is not active")
    project_path = Path(entry.path).resolve(strict=True)
    try:
        project_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("registered project escapes configured workspace") from exc
    if not project_path.is_dir():
        raise ValueError("registered project must be a directory")

    state = Path(state_dir).expanduser().resolve()
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    token = _sha256(task.request_id.encode("utf-8"))
    claim_path = state / f"{token}.claim.json"
    result_path = state / f"{token}.result.json"
    fingerprint = _sha256(_json_bytes(asdict(task)))
    claim = {"request_id": task.request_id, "envelope_sha256": fingerprint}
    try:
        _write_once(claim_path, claim)
    except FileExistsError:
        existing = _read_record(claim_path)
        if existing != claim:
            raise ValueError("request_id has been claimed by another or incomplete envelope")
        previous = _read_record(result_path)
        if previous is None:
            return {"request_id": task.request_id, "task_id": task.task_id,
                    "state": "NEEDS_REVIEW", "verified": False, "replayed": True,
                    "reason": "previous execution has unknown outcome; not replayed"}
        return {**previous, "replayed": True}

    running = task.transition("APPROVED").transition("RUNNING")
    runner = executor or TerminalExecutor(
        root, audit_ledger=AuditLedger(state / "terminal-audit.jsonl"),
        source="modular-canary",
    )
    readings: list[tuple[str, str, bool] | None] = []
    blocked = False
    for phase in ("observe", "readback"):
        child_id = f"{task.request_id}:{phase}"
        try:
            response = dispatch_action(
                "git.status", {"target": str(project_path)}, workspace_root=root,
                approved=False, request_id=child_id, executor=runner,
            )
        except ActionError:
            blocked = True
            break
        reading = _safe_result(response, child_id)
        readings.append(reading)
        if reading is None:
            break

    verified = len(readings) == 2 and readings[0] is not None and readings[0] == readings[1]
    evidence_sha256 = _sha256(_json_bytes(readings)) if readings else None
    if blocked:
        final_state = running.transition("BLOCKED").state
    elif verified:
        final_state = running.transition("VERIFIED", evidence_ref=evidence_sha256).transition(
            "DONE", evidence_ref=evidence_sha256
        ).state
    else:
        final_state = running.transition("NEEDS_REVIEW").state
    result: dict[str, Any] = {
        "request_id": task.request_id,
        "task_id": task.task_id,
        "state": final_state,
        "verified": verified,
        "replayed": False,
        "evidence_sha256": evidence_sha256,
        "attempted_reads": len(readings) + int(blocked),
    }
    if verified:
        assert readings[0] is not None
        result["branch"] = readings[0][1]
        result["worktree_dirty"] = readings[0][2]
    _write_once(result_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the read-only modular git.status canary")
    parser.add_argument("--task-file", required=True, help="Path to TaskEnvelopeV1 JSON")
    parser.add_argument("--workspace", required=True, help="Allowed workspace root")
    parser.add_argument("--projects-file", default=DEFAULT_PROJECTS_FILE)
    parser.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    args = parser.parse_args()
    with open(args.task_file, encoding="utf-8") as handle:
        task = TaskEnvelopeV1.parse(json.load(handle))
    result = run_git_status_canary(
        task, workspace_root=args.workspace, projects_file=args.projects_file,
        state_dir=args.state_dir,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
