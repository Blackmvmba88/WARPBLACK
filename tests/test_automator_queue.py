from __future__ import annotations

import json
from pathlib import Path

import warpblack.automator_queue as automator_queue
from warpblack.automator_queue import AutomatorQueueWorker
from warpblack.project_registry import ProjectRegistry


def _job(
    project_path: Path,
    *,
    risk: str = "low",
    requires_authorization: bool = False,
    authorization=None,
):
    return {
        "job_id": "job-1",
        "idempotency_key": "idem-1",
        "source": "test",
        "project": project_path.name,
        "adapter": "workspace",
        "intent": "import_project_reference",
        "inputs": {
            "trigger_kind": "workspace.project_discovered",
            "path": str(project_path),
        },
        "validators": [{"name": "project_reference_exists", "params": {}}],
        "risk": risk,
        "evidence_targets": ["local-jsonl", "github", "notion"],
        "requires_authorization": requires_authorization,
        "authorization": authorization,
    }


def test_workspace_job_round_trip(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project = workspace / "MEngine"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname='mengine'\n", encoding="utf-8")
    queue = tmp_path / "queue"
    registry_file = tmp_path / "projects.json"

    worker = AutomatorQueueWorker(
        queue_dir=queue,
        workspace_root=workspace,
        project_registry_file=registry_file,
    )
    job_path = worker.jobs / "job-1.warpblack-job.json"
    job_path.write_text(json.dumps(_job(project)), encoding="utf-8")

    assert worker.run_once() == 1

    result_path = worker.results / "job-1.warpblack-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "validated"
    assert result["validation"][0]["ok"] is True
    assert not job_path.exists()
    assert (worker.processed / job_path.name).exists()

    registry = ProjectRegistry(registry_file)
    assert len(registry.entries) == 1
    assert registry.entries[0].path == str(project.resolve())


def test_workspace_escape_is_rejected(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    queue = tmp_path / "queue"

    worker = AutomatorQueueWorker(
        queue_dir=queue,
        workspace_root=workspace,
        project_registry_file=tmp_path / "projects.json",
    )
    job_path = worker.jobs / "job-1.warpblack-job.json"
    job_path.write_text(json.dumps(_job(outside)), encoding="utf-8")

    assert worker.run_once() == 1
    result = json.loads(
        (worker.results / "job-1.warpblack-result.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "failed"
    assert "escapes" in result["errors"][0]


def test_authorized_distribution_prepares_bundle_without_publishing(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    queue = tmp_path / "queue"

    worker = AutomatorQueueWorker(
        queue_dir=queue,
        workspace_root=workspace,
        project_registry_file=tmp_path / "projects.json",
    )
    job = {
        "job_id": "dist-1",
        "idempotency_key": "dist-idem-1",
        "source": "mengine",
        "project": "music-catalog",
        "adapter": "distribution-work",
        "intent": "prepare_distribution_bundle",
        "inputs": {
            "trigger_kind": "music.distribute_requested",
            "track_id": "frequency-demo",
            "title": "Frequency",
            "distribution_gate_passed": True,
            "metadata": {"artist": "Iyari Gomez", "style": "reggae"},
            "assets": {"audio": {"path": "Frequency.wav"}},
        },
        "validators": [{"name": "distribution_bundle_ready", "params": {}}],
        "risk": "medium",
        "evidence_targets": ["local-jsonl"],
        "requires_authorization": True,
        "authorization": {
            "granted": True,
            "at": "2026-09-27T13:00:00+00:00",
            "source": "explicit_user_action",
        },
    }
    job_path = worker.jobs / "dist-1.warpblack-job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")

    assert worker.run_once() == 1
    result = json.loads(
        (worker.results / "dist-1.warpblack-result.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "validated"
    artifact = Path(result["artifacts"][0]["path"])
    bundle = json.loads(artifact.read_text(encoding="utf-8"))
    assert bundle["publicationStatus"] == "not_published"
    assert bundle["trackId"] == "frequency-demo"


def test_authorized_job_requires_real_receipt(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    project.mkdir(parents=True)
    queue = tmp_path / "queue"

    worker = AutomatorQueueWorker(
        queue_dir=queue,
        workspace_root=workspace,
        project_registry_file=tmp_path / "projects.json",
    )
    job = _job(
        project,
        risk="irreversible",
        requires_authorization=True,
        authorization={"granted": True},
    )
    (worker.jobs / "job-1.warpblack-job.json").write_text(
        json.dumps(job), encoding="utf-8"
    )

    assert worker.run_once() == 1
    result = json.loads(
        (worker.results / "job-1.warpblack-result.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "blocked"


def test_authorization_gated_job_is_blocked(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    project.mkdir(parents=True)
    queue = tmp_path / "queue"

    worker = AutomatorQueueWorker(
        queue_dir=queue,
        workspace_root=workspace,
        project_registry_file=tmp_path / "projects.json",
    )
    job = _job(project, risk="irreversible", requires_authorization=True)
    (worker.jobs / "job-1.warpblack-job.json").write_text(
        json.dumps(job), encoding="utf-8"
    )

    assert worker.run_once() == 1
    result = json.loads(
        (worker.results / "job-1.warpblack-result.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "blocked"
    assert result["artifacts"] == []


def test_git_status_canary_round_trip(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    queue = tmp_path / "queue"
    seen = {}

    def fake_dispatch(action, args, *, workspace_root, approved=False, request_id=None, executor=None):
        seen.update(
            {
                "action": action,
                "args": args,
                "workspace_root": str(workspace_root),
                "request_id": request_id,
            }
        )
        return {
            "status": "success",
            "intent": "git.status",
            "data": {"branch": "main", "dirty": False},
        }

    monkeypatch.setattr(automator_queue, "dispatch_action", fake_dispatch)
    worker = AutomatorQueueWorker(
        queue_dir=queue,
        workspace_root=workspace,
        project_registry_file=tmp_path / "projects.json",
    )
    job = {
        "job_id": "git-status-1",
        "idempotency_key": "git-status-idem-1",
        "source": "operator",
        "project": "WARPBLACK",
        "adapter": "warpblack-action",
        "intent": "git.status",
        "inputs": {
            "trigger_kind": "workspace.git_status_requested",
            "target": "WARPBLACK",
        },
        "validators": [{"name": "git_status_returned", "params": {}}],
        "risk": "low",
        "evidence_targets": ["local-jsonl"],
        "requires_authorization": False,
        "authorization": None,
    }
    job_path = worker.jobs / "git-status-1.warpblack-job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")

    assert worker.run_once() == 1
    result = json.loads(
        (worker.results / "git-status-1.warpblack-result.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "validated"
    assert result["validation"][0]["ok"] is True
    assert result["diff"]["git_status"]["data"]["branch"] == "main"
    assert seen["action"] == "git.status"
    assert seen["args"] == {"target": "WARPBLACK"}
    assert seen["request_id"] == "automator:git-status-1"
