"""BM-CORE-001: policy-bound readback, durable evidence, and replay protection."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from warpblack import runtime_canary
from warpblack.project_registry import ProjectRegistry
from warpblack.task_envelope import TaskEnvelopeV1


def task(workspace_id: str, **changes: object) -> TaskEnvelopeV1:
    payload = {
        "schema_version": 1,
        "request_id": "bm-core-canary-001",
        "task_id": "BM-CORE-001",
        "source": "observer",
        "workspace_id": workspace_id,
        "intent": "git.status",
        "state": "PROPOSED",
        "risk": "read_only",
        "approval_ref": None,
        "expected": ["two matching git status reads"],
    }
    payload.update(changes)
    return TaskEnvelopeV1.parse(payload)


@pytest.fixture
def setup_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project = workspace / "ProjectA"
    project.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    (project / "marker.txt").write_text("a file only in the worktree", encoding="utf-8")
    projects_file = tmp_path / "projects.json"
    entry = ProjectRegistry(projects_file).add(project)
    return {
        "task": task(entry.id), "workspace_root": workspace,
        "projects_file": projects_file, "state_dir": tmp_path / "ledger",
    }


def test_real_git_status_readback_is_certified_and_replayed_without_execution(
    setup_workspace: dict, monkeypatch: pytest.MonkeyPatch,
):
    report = runtime_canary.run_git_status_canary(**setup_workspace)
    assert report["state"] == "DONE"
    assert report["verified"] is True
    assert report["attempted_reads"] == 2
    assert report["worktree_dirty"] is True
    assert len(report["evidence_sha256"]) == 64

    audit = setup_workspace["state_dir"] / "terminal-audit.jsonl"
    audit_rows = [json.loads(line) for line in audit.read_text().splitlines()]
    assert len(audit_rows) == 2
    assert all(row["policy_risk"] == "low" for row in audit_rows)
    assert not any("marker.txt" in file.read_text() for file in
                   setup_workspace["state_dir"].glob("*.result.json"))

    def must_not_run(*args, **kwargs):
        raise AssertionError("duplicate request must not execute again")

    monkeypatch.setattr(runtime_canary, "dispatch_action", must_not_run)
    cached = runtime_canary.run_git_status_canary(**setup_workspace)
    assert cached["verified"] is True
    assert cached["replayed"] is True


@pytest.mark.parametrize("changes", [
    {"risk": "mutation"},
    {"intent": "desktop.click"},
    {"state": "APPROVED"},
    {"approval_ref": "approval-from-payload"},
])
def test_not_read_only_is_rejected_before_claim(setup_workspace: dict, changes: dict):
    setup_workspace["task"] = task(setup_workspace["task"].workspace_id, **changes)
    with pytest.raises(ValueError):
        runtime_canary.run_git_status_canary(**setup_workspace)
    if setup_workspace["state_dir"].exists():
        assert not list(setup_workspace["state_dir"].glob("*.claim.json"))


def test_outside_registered_workspace_cannot_execute(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    projects = tmp_path / "projects.json"
    entry = ProjectRegistry(projects).add(outside)
    with pytest.raises(ValueError, match="escapes"):
        runtime_canary.run_git_status_canary(
            task(entry.id), workspace_root=workspace, projects_file=projects,
            state_dir=tmp_path / "ledger",
        )


def _fake_response(request_id: str, stdout: str) -> dict:
    return {
        "request_id": request_id, "status": "success", "capability": "git.status",
        "changed": False,
        "plan": {"capability": "git.status", "mutates": False, "requires_approval": False},
        "evidence": {
            "request_id": request_id, "exit_code": 0, "timed_out": False,
            "policy_risk": "low", "stdout": stdout,
            "branch": "main", "worktree_dirty": "??" in stdout,
        },
    }


def test_changed_readback_needs_review(setup_workspace: dict, monkeypatch: pytest.MonkeyPatch):
    count = 0

    def changed(action, args, *, workspace_root, approved, request_id, executor):
        nonlocal count
        assert action == "git.status"
        assert approved is False
        count += 1
        return _fake_response(request_id, "## main\n" if count == 1 else "## main\n?? new-file\n")

    monkeypatch.setattr(runtime_canary, "dispatch_action", changed)
    report = runtime_canary.run_git_status_canary(**setup_workspace)
    assert count == 2
    assert report["state"] == "NEEDS_REVIEW"
    assert report["verified"] is False


def test_interrupted_unknown_execution_is_not_retried(
    setup_workspace: dict, monkeypatch: pytest.MonkeyPatch,
):
    calls = 0

    def crash(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("simulated process loss")

    monkeypatch.setattr(runtime_canary, "dispatch_action", crash)
    with pytest.raises(RuntimeError, match="process loss"):
        runtime_canary.run_git_status_canary(**setup_workspace)
    report = runtime_canary.run_git_status_canary(**setup_workspace)
    assert calls == 1
    assert report["state"] == "NEEDS_REVIEW"
    assert report["replayed"] is True
    assert report["verified"] is False


def test_same_request_id_with_changed_task_is_rejected(setup_workspace: dict):
    initial = runtime_canary.run_git_status_canary(**setup_workspace)
    assert initial["verified"]
    setup_workspace["task"] = task(
        setup_workspace["task"].workspace_id, expected=["different evidence"]
    )
    with pytest.raises(ValueError, match="claimed"):
        runtime_canary.run_git_status_canary(**setup_workspace)


def test_spoofed_policy_evidence_does_not_certify(
    setup_workspace: dict, monkeypatch: pytest.MonkeyPatch,
):
    def spoof(action, args, *, workspace_root, approved, request_id, executor):
        result = _fake_response(request_id, "## main\n")
        result["evidence"]["policy_risk"] = "elevated"
        return result

    monkeypatch.setattr(runtime_canary, "dispatch_action", spoof)
    report = runtime_canary.run_git_status_canary(**setup_workspace)
    assert report["state"] == "NEEDS_REVIEW"
    assert report["attempted_reads"] == 1
    assert not report["verified"]


def test_policy_denial_is_blocked_and_never_certified(
    setup_workspace: dict, monkeypatch: pytest.MonkeyPatch,
):
    def deny(*args, **kwargs):
        raise runtime_canary.PolicyError("policy denied")

    monkeypatch.setattr(runtime_canary, "dispatch_action", deny)
    result = runtime_canary.run_git_status_canary(**setup_workspace)
    assert result["state"] == "BLOCKED"
    assert result["verified"] is False
    assert result["attempted_reads"] == 1
