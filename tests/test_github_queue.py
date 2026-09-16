from pathlib import Path

import pytest

from warpblack.github_queue import (
    APPROVAL_LABEL,
    JOB_LABEL,
    JOB_PROTOCOL,
    GitHubControlPlane,
    GitHubQueueError,
    parse_issue_job,
)


def make_issue(
    *,
    actor: str = "Blackmvmba88",
    labels: list[str] | None = None,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    import json

    if labels is None:
        labels = [JOB_LABEL]
    if payload is None:
        payload = {"protocol": JOB_PROTOCOL, "argv": ["git", "status"], "cwd": "."}
    return {
        "number": 7,
        "user": {"login": actor},
        "labels": [{"name": label} for label in labels],
        "body": json.dumps(payload),
    }


def test_valid_job_is_parsed() -> None:
    job = parse_issue_job(make_issue(), allowed_actor="Blackmvmba88")
    assert job is not None
    assert job.issue_number == 7
    assert job.argv == ("git", "status")
    assert job.approved is False


def test_approval_is_derived_from_label_not_body() -> None:
    payload = {
        "protocol": JOB_PROTOCOL,
        "argv": ["python3", "-c", "print('x')"],
        "approved": True,
    }
    without_label = parse_issue_job(
        make_issue(payload=payload),
        allowed_actor="Blackmvmba88",
    )
    with_label = parse_issue_job(
        make_issue(payload=payload, labels=[JOB_LABEL, APPROVAL_LABEL]),
        allowed_actor="Blackmvmba88",
    )
    assert without_label is not None and without_label.approved is False
    assert with_label is not None and with_label.approved is True


def test_wrong_actor_is_ignored() -> None:
    job = parse_issue_job(make_issue(actor="someone-else"), allowed_actor="Blackmvmba88")
    assert job is None


def test_job_label_is_required() -> None:
    job = parse_issue_job(make_issue(labels=["other"]), allowed_actor="Blackmvmba88")
    assert job is None


def test_public_control_repository_is_rejected(tmp_path: Path) -> None:
    class FakeControlPlane(GitHubControlPlane):
        def _request_json(self, method, path, payload=None):
            return {"private": False}

    control = FakeControlPlane(
        token="token",
        repository="owner/private-control",
        allowed_actor="Blackmvmba88",
        workspace_root=tmp_path,
    )
    with pytest.raises(GitHubQueueError, match="must be private"):
        control.assert_private_repository()
