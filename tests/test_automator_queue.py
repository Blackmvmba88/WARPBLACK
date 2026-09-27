from __future__ import annotations

import json
from pathlib import Path

from warpblack.automator_queue import AutomatorQueueWorker
from warpblack.project_registry import ProjectRegistry


def _job(project_path: Path, *, risk: str = "low", requires_authorization: bool = False):
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
