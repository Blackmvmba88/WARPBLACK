from pathlib import Path
import subprocess

import pytest

from warpblack.github_queue import (
    APPROVAL_LABEL,
    CONSTRUCT_PROTOCOL,
    JOB_LABEL,
    JOB_PROTOCOL,
    GitHubConstructJob,
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


def _construct_patch() -> str:
    return """diff --git a/remote.txt b/remote.txt
new file mode 100644
--- /dev/null
+++ b/remote.txt
@@ -0,0 +1 @@
+remote
"""


def test_construct_job_approval_is_derived_from_label() -> None:
    payload = {
        "protocol": CONSTRUCT_PROTOCOL,
        "message": "constrúyelo",
        "objective": "create remote marker",
        "patch": _construct_patch(),
        "checks": [["cat", "remote.txt"]],
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

    assert isinstance(without_label, GitHubConstructJob)
    assert without_label.approved is False
    assert isinstance(with_label, GitHubConstructJob)
    assert with_label.approved is True
    assert with_label.checks == (("cat", "remote.txt"),)


def test_approved_construct_job_executes_and_reports(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    class FakeControlPlane(GitHubControlPlane):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.calls = []

        def _request_json(self, method, path, payload=None):
            self.calls.append((method, path, payload))
            return {}

    control = FakeControlPlane(
        token="token",
        repository="owner/private-control",
        allowed_actor="Blackmvmba88",
        workspace_root=tmp_path,
    )
    job = parse_issue_job(
        make_issue(
            labels=[JOB_LABEL, APPROVAL_LABEL],
            payload={
                "protocol": CONSTRUCT_PROTOCOL,
                "message": "constrúyelo",
                "objective": "create remote marker",
                "patch": _construct_patch(),
                "checks": [["cat", "remote.txt"]],
            },
        ),
        allowed_actor="Blackmvmba88",
    )
    assert isinstance(job, GitHubConstructJob)

    control._execute_job(job)

    assert (tmp_path / "remote.txt").read_text(encoding="utf-8") == "remote\n"
    comment = next(call for call in control.calls if call[0] == "POST")
    assert '"status": "done"' in comment[2]["body"]
    assert '"job_type": "construct"' in comment[2]["body"]


def test_unapproved_construct_job_is_denied_without_applying(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    class FakeControlPlane(GitHubControlPlane):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.calls = []

        def _request_json(self, method, path, payload=None):
            self.calls.append((method, path, payload))
            return {}

    control = FakeControlPlane(
        token="token",
        repository="owner/private-control",
        allowed_actor="Blackmvmba88",
        workspace_root=tmp_path,
    )
    job = parse_issue_job(
        make_issue(
            payload={
                "protocol": CONSTRUCT_PROTOCOL,
                "message": "constrúyelo",
                "objective": "create remote marker",
                "patch": _construct_patch(),
            },
        ),
        allowed_actor="Blackmvmba88",
    )
    assert isinstance(job, GitHubConstructJob)
    assert job.approved is False

    control._execute_job(job)

    assert not (tmp_path / "remote.txt").exists()
    comment = next(call for call in control.calls if call[0] == "POST")
    assert "warpblack-approved" in comment[2]["body"]
