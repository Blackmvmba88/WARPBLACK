import json
from pathlib import Path

import pytest

import warpblack.actions as actions
import warpblack.github_queue as github_queue
from warpblack.actions import ACTION_PROTOCOL, ActionError, dispatch_action
from warpblack.desktop import DesktopResult
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
                "action": "blender.observe",
                "args": {},
            }
        ),
        allowed_actor="Blackmvmba88",
    )
    assert isinstance(job, GitHubActionJob)
    assert job.action == "blender.observe"
    assert job.args == {}
    assert job.approved is False


def test_action_approval_comes_only_from_label() -> None:
    body_claim = {
        "protocol": ACTION_PROTOCOL,
        "action": "blender.activate",
        "args": {},
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


def test_desktop_capture_rejects_remote_output_path() -> None:
    with pytest.raises(ActionError, match="unsupported args"):
        dispatch_action("desktop.capture", {"output": "/tmp/forced.png"})


def test_blender_mutation_requires_approval() -> None:
    with pytest.raises(ActionError, match="requires explicit remote approval"):
        dispatch_action("blender.activate", {})


def test_read_only_action_dispatches_without_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        actions,
        "frontmost_application",
        lambda: DesktopResult(True, "frontmost", {"application": "Terminal"}),
    )
    result = dispatch_action("desktop.frontmost", {})
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
        lambda action, args, approved=False: {
            "ok": True,
            "action": action,
            "data": {"approved": approved, "args": args},
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
                "action": "blender.observe",
                "args": {},
            }
        ),
        allowed_actor="Blackmvmba88",
    )
    assert isinstance(job, GitHubActionJob)

    control._execute_job(job)

    comment = next(call for call in calls if call[0] == "POST")
    assert '"job_type": "action"' in comment[2]["body"]
    assert '"requested_action": "blender.observe"' in comment[2]["body"]
    assert any(call[0] == "PATCH" for call in calls)
