import json
from pathlib import Path

import pytest

import warpblack.actions as actions
import warpblack.github_queue as github_queue
from warpblack.actions import ACTION_PROTOCOL, ActionError, dispatch_action
from warpblack.audit import AuditLedger
from warpblack.desktop import DesktopError, DesktopResult
from warpblack.executor import TerminalExecutor
from warpblack.github_queue import (
    APPROVAL_LABEL,
    JOB_LABEL,
    GitHubActionJob,
    GitHubControlPlane,
    parse_issue_job,
)


def make_issue(payload: dict[str, object], *, approved: bool = False) -> dict[str, object]:
    labels = [JOB_LABEL]
    if approved:
        labels.append(APPROVAL_LABEL)
    return {
        "number": 21,
        "user": {"login": "Blackmvmba88"},
        "labels": [{"name": label} for label in labels],
        "body": json.dumps(payload),
    }


def test_typed_action_job_is_parsed() -> None:
    job = parse_issue_job(
        make_issue(
            {
                "protocol": ACTION_PROTOCOL,
                "action": "git.status",
                "args": {"target": "."},
            }
        ),
        allowed_actor="Blackmvmba88",
    )
    assert isinstance(job, GitHubActionJob)
    assert job.action == "git.status"
    assert job.args == {"target": "."}
    assert job.approved is False


def test_action_approval_comes_only_from_label() -> None:
    body_claim = {
        "protocol": ACTION_PROTOCOL,
        "action": "blender.object.translate_restore",
        "args": {
            "target": "scene.blend",
            "object": "Cube",
            "delta": [0.01, 0.0, 0.0],
        },
        "approved": True,
    }
    without = parse_issue_job(make_issue(body_claim), allowed_actor="Blackmvmba88")
    with_label = parse_issue_job(
        make_issue(body_claim, approved=True),
        allowed_actor="Blackmvmba88",
    )
    assert isinstance(without, GitHubActionJob)
    assert isinstance(with_label, GitHubActionJob)
    assert without.approved is False
    assert with_label.approved is True


def test_desktop_capture_rejects_remote_output_path(tmp_path: Path) -> None:
    with pytest.raises(ActionError, match="unsupported args"):
        dispatch_action(
            "desktop.capture",
            {"output": "/tmp/forced.png"},
            workspace_root=tmp_path,
        )


def test_blender_action_requires_approval(tmp_path: Path) -> None:
    with pytest.raises(ActionError, match="requires the separate remote approval label"):
        dispatch_action(
            "blender.object.translate_restore",
            {
                "target": "scene.blend",
                "object": "Cube",
                "delta": [0.01, 0.0, 0.0],
            },
            workspace_root=tmp_path,
        )


def test_read_only_desktop_action_dispatches_without_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        actions,
        "frontmost_application",
        lambda: DesktopResult(True, "frontmost", {"application": "Terminal"}),
    )
    result = dispatch_action("desktop.frontmost", {}, workspace_root=tmp_path)
    assert result["ok"] is True
    assert result["data"]["application"] == "Terminal"


def test_control_plane_executes_typed_action_and_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, object]] = []

    class FakeControlPlane(GitHubControlPlane):
        def _request_json(self, method, path, payload=None):
            calls.append((method, path, payload))
            return {}

    monkeypatch.setattr(
        github_queue,
        "dispatch_action",
        lambda action, args, workspace_root, approved=False, request_id=None, executor=None: {
            "ok": True,
            "action": action,
            "data": {
                "approved": approved,
                "args": args,
                "request_id": request_id,
                "workspace": str(workspace_root),
                "executor_bound": executor is not None,
            },
        },
    )

    control = FakeControlPlane(
        token="token",
        repository="owner/private-control",
        allowed_actor="Blackmvmba88",
        workspace_root=tmp_path,
    )
    job = parse_issue_job(
        make_issue(
            {
                "protocol": ACTION_PROTOCOL,
                "action": "git.status",
                "args": {"target": "."},
            }
        ),
        allowed_actor="Blackmvmba88",
    )
    assert isinstance(job, GitHubActionJob)

    control._execute_job(job)

    comment = next(call for call in calls if call[0] == "POST")
    body = comment[2]["body"]
    assert '"job_type": "action"' in body
    assert '"requested_action": "git.status"' in body
    assert any(call[0] == "PATCH" for call in calls)



def test_desktop_error_is_normalized_as_action_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> DesktopResult:
        raise DesktopError("Accessibility permission denied")

    monkeypatch.setattr(actions, "frontmost_application", fail)

    with pytest.raises(ActionError, match="Accessibility permission denied"):
        dispatch_action("desktop.frontmost", {}, workspace_root=tmp_path)


def test_typed_file_read_uses_supplied_audited_executor(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    target.write_text("hello audit", encoding="utf-8")
    audit_path = tmp_path / "audit.jsonl"
    executor = TerminalExecutor(
        tmp_path,
        audit_ledger=AuditLedger(audit_path),
        source="github:owner/private-control",
        actor="Blackmvmba88",
    )

    result = dispatch_action(
        "files.read",
        {"target": "hello.txt"},
        workspace_root=tmp_path,
        request_id="github:owner/private-control#21",
        executor=executor,
    )

    assert result["status"] == "success"
    records = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records[-1]["request_id"] == "github:owner/private-control#21"
    assert records[-1]["source"] == "github:owner/private-control"
    assert records[-1]["actor"] == "Blackmvmba88"


def test_control_plane_bounds_nested_typed_action_strings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, object]] = []
    huge = "x" * 50_000

    class FakeControlPlane(GitHubControlPlane):
        def _request_json(self, method, path, payload=None):
            calls.append((method, path, payload))
            return {}

    monkeypatch.setattr(
        github_queue,
        "dispatch_action",
        lambda action, args, workspace_root, approved=False, request_id=None, executor=None: {
            "ok": True,
            "evidence": {
                "content": huge,
                "execution": {"stdout": huge, "stderr": ""},
            },
        },
    )

    control = FakeControlPlane(
        token="token",
        repository="owner/private-control",
        allowed_actor="Blackmvmba88",
        workspace_root=tmp_path,
    )
    job = GitHubActionJob(
        issue_number=21,
        action="files.read",
        args={"target": "big.txt"},
        approved=False,
        actor="Blackmvmba88",
    )

    control._execute_job(job)

    comment = next(call for call in calls if call[0] == "POST")
    body = comment[2]["body"]
    assert '"content_truncated": true' in body
    assert '"stdout_truncated": true' in body
    assert huge not in body
