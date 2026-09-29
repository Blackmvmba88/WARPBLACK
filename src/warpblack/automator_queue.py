from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from .actions import ActionError, dispatch_action
from .project_registry import DEFAULT_PROJECTS_FILE, ProjectRegistry, ProjectRegistryError


AUTOMATOR_JOB_SUFFIX = ".warpblack-job.json"
AUTOMATOR_RESULT_SUFFIX = ".warpblack-result.json"
BLOCKED_RISKS = {"high", "irreversible"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


@dataclass(frozen=True)
class AutomatorJob:
    job_id: str
    idempotency_key: str
    source: str
    project: str
    adapter: str
    intent: str
    inputs: dict[str, Any]
    validators: tuple[dict[str, Any], ...]
    risk: str
    evidence_targets: tuple[str, ...]
    requires_authorization: bool
    authorization: dict[str, Any] | None = None

    @classmethod
    def from_payload(cls, payload: object) -> "AutomatorJob":
        if not isinstance(payload, dict):
            raise TypeError("automator job must be a JSON object")

        required_strings = (
            "job_id",
            "idempotency_key",
            "source",
            "project",
            "adapter",
            "intent",
            "risk",
        )
        values: dict[str, str] = {}
        for key in required_strings:
            value = payload.get(key)
            if not isinstance(value, str) or not value.strip():
                raise TypeError(f"{key} must be a non-empty string")
            values[key] = value.strip()

        inputs = payload.get("inputs", {})
        if not isinstance(inputs, dict):
            raise TypeError("inputs must be an object")

        validators_raw = payload.get("validators", [])
        if not isinstance(validators_raw, list):
            raise TypeError("validators must be a list")
        validators: list[dict[str, Any]] = []
        for item in validators_raw:
            if not isinstance(item, dict):
                raise TypeError("each validator must be an object")
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                raise TypeError("validator name must be a non-empty string")
            params = item.get("params", {})
            if not isinstance(params, dict):
                raise TypeError("validator params must be an object")
            validators.append({"name": name.strip(), "params": dict(params)})

        evidence_raw = payload.get("evidence_targets", [])
        if not isinstance(evidence_raw, list) or not all(
            isinstance(item, str) and item.strip() for item in evidence_raw
        ):
            raise TypeError("evidence_targets must be a list of strings")

        requires_authorization = payload.get("requires_authorization", False)
        if not isinstance(requires_authorization, bool):
            raise TypeError("requires_authorization must be boolean")

        authorization = payload.get("authorization")
        if authorization is not None and not isinstance(authorization, dict):
            raise TypeError("authorization must be an object or null")

        return cls(
            job_id=values["job_id"],
            idempotency_key=values["idempotency_key"],
            source=values["source"],
            project=values["project"],
            adapter=values["adapter"],
            intent=values["intent"],
            inputs=dict(inputs),
            validators=tuple(validators),
            risk=values["risk"],
            evidence_targets=tuple(evidence_raw),
            requires_authorization=requires_authorization,
            authorization=dict(authorization) if authorization is not None else None,
        )


class AutomatorQueueWorker:
    """Allowlisted WARPBLACK worker for BlackMamba Automator jobs.

    There is deliberately no generic argv/shell field in this protocol.
    """

    def __init__(
        self,
        *,
        queue_dir: str | Path,
        workspace_root: str | Path,
        project_registry_file: str | Path = DEFAULT_PROJECTS_FILE,
    ) -> None:
        self.root = Path(queue_dir).expanduser()
        self.jobs = self.root / "jobs"
        self.results = self.root / "results"
        self.processed = self.root / "processed"
        self.rejected = self.root / "rejected"
        self.artifacts = self.root / "artifacts"
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.project_registry_file = Path(project_registry_file).expanduser()
        for path in (
            self.jobs,
            self.results,
            self.processed,
            self.rejected,
            self.artifacts,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def run_once(self) -> int:
        pending = sorted(self.jobs.glob(f"*{AUTOMATOR_JOB_SUFFIX}"))
        if not pending:
            return 0
        self._consume(pending[0])
        return 1

    def watch(self, *, poll_interval_s: float = 2.0) -> None:
        if poll_interval_s < 0.5:
            raise ValueError("poll interval must be at least 0.5 seconds")
        while True:
            self.run_once()
            time.sleep(poll_interval_s)

    def _consume(self, path: Path) -> None:
        started = _utc_now()
        job: AutomatorJob | None = None
        try:
            job = AutomatorJob.from_payload(
                json.loads(path.read_text(encoding="utf-8"))
            )
            result = self._execute(job, started_at=started)
            destination = self.processed / path.name
        except (
            OSError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
            ProjectRegistryError,
            ActionError,
        ) as exc:
            job_id = (
                job.job_id
                if job is not None
                else path.name.removesuffix(AUTOMATOR_JOB_SUFFIX)
            )
            idem = job.idempotency_key if job is not None else "unknown"
            result = self._result(
                job_id=job_id,
                idempotency_key=idem,
                status="failed",
                started_at=started,
                errors=[str(exc)],
            )
            destination = self.rejected / path.name

        self._write_result(result)
        path.replace(destination)

    def _execute(self, job: AutomatorJob, *, started_at: str) -> dict[str, Any]:
        authorization_granted = bool(
            job.authorization
            and job.authorization.get("granted") is True
            and isinstance(job.authorization.get("at"), str)
            and bool(job.authorization.get("at"))
        )
        if (
            job.requires_authorization or job.risk in BLOCKED_RISKS
        ) and not authorization_granted:
            return self._result(
                job_id=job.job_id,
                idempotency_key=job.idempotency_key,
                status="blocked",
                started_at=started_at,
                errors=["explicit authorization receipt required"],
            )

        if job.adapter == "workspace" and job.intent == "import_project_reference":
            return self._workspace_import(job, started_at=started_at)

        if job.adapter == "warpblack-action" and job.intent == "git.status":
            return self._git_status(job, started_at=started_at)

        if (
            job.adapter == "distribution-work"
            and job.intent == "prepare_distribution_bundle"
        ):
            return self._prepare_distribution_bundle(job, started_at=started_at)

        return self._result(
            job_id=job.job_id,
            idempotency_key=job.idempotency_key,
            status="failed",
            started_at=started_at,
            errors=[
                f"unsupported automator adapter/intent: {job.adapter}/{job.intent}"
            ],
        )

    def _workspace_import(
        self,
        job: AutomatorJob,
        *,
        started_at: str,
    ) -> dict[str, Any]:
        raw_path = job.inputs.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("workspace import requires inputs.path")

        project_path = Path(raw_path).expanduser().resolve()
        if not _inside(self.workspace_root, project_path):
            raise ValueError("project path escapes configured workspace root")
        if not project_path.exists() or not project_path.is_dir():
            raise ValueError(f"project folder does not exist: {project_path}")

        registry = ProjectRegistry(self.project_registry_file)
        entry = registry.add(project_path, name=job.project)

        validation: list[dict[str, Any]] = []
        for spec in job.validators:
            name = spec["name"]
            if name == "project_reference_exists":
                ok = project_path.exists() and any(
                    item.id == entry.id for item in registry.entries
                )
                detail = (
                    f"registry={self.project_registry_file}; "
                    f"project_id={entry.id}"
                )
            else:
                ok = False
                detail = f"unsupported validator: {name}"
            validation.append(
                {"validator": name, "ok": ok, "detail": detail}
            )

        if not validation:
            validation.append(
                {
                    "validator": "project_reference_exists",
                    "ok": True,
                    "detail": (
                        f"registry={self.project_registry_file}; "
                        f"project_id={entry.id}"
                    ),
                }
            )

        status = (
            "validated"
            if all(item["ok"] for item in validation)
            else "failed"
        )
        return self._result(
            job_id=job.job_id,
            idempotency_key=job.idempotency_key,
            status=status,
            started_at=started_at,
            validation=validation,
            artifacts=[
                {
                    "type": "project_reference",
                    "project_id": entry.id,
                    "name": entry.name,
                    "path": entry.path,
                }
            ],
            logs=[f"registered workspace project {entry.name}"],
            evidence_links=[str(self.project_registry_file)],
        )

    def _git_status(
        self,
        job: AutomatorJob,
        *,
        started_at: str,
    ) -> dict[str, Any]:
        target = job.inputs.get("target", ".")
        if not isinstance(target, str) or not target.strip():
            raise ValueError("git.status requires a non-empty inputs.target")

        action_result = dispatch_action(
            "git.status",
            {"target": target.strip()},
            workspace_root=self.workspace_root,
            request_id=f"automator:{job.job_id}",
        )
        ok = action_result.get("status") == "success" or action_result.get("ok") is True

        validation: list[dict[str, Any]] = []
        for spec in job.validators:
            name = spec["name"]
            if name == "git_status_returned":
                validation.append(
                    {
                        "validator": name,
                        "ok": ok,
                        "detail": f"git.status target={target.strip()}",
                    }
                )
            else:
                validation.append(
                    {
                        "validator": name,
                        "ok": False,
                        "detail": f"unsupported validator: {name}",
                    }
                )

        if not validation:
            validation.append(
                {
                    "validator": "git_status_returned",
                    "ok": ok,
                    "detail": f"git.status target={target.strip()}",
                }
            )

        status = "validated" if all(item["ok"] for item in validation) else "failed"
        return self._result(
            job_id=job.job_id,
            idempotency_key=job.idempotency_key,
            status=status,
            started_at=started_at,
            validation=validation,
            diff={"git_status": action_result},
            logs=[f"executed read-only git.status for {target.strip()}"],
        )

    def _prepare_distribution_bundle(
        self,
        job: AutomatorJob,
        *,
        started_at: str,
    ) -> dict[str, Any]:
        if job.inputs.get("distribution_gate_passed") is not True:
            raise ValueError(
                "distribution gate must be passed before bundle preparation"
            )

        track_id = job.inputs.get("track_id")
        title = job.inputs.get("title")
        metadata = job.inputs.get("metadata")
        assets = job.inputs.get("assets")

        if not isinstance(track_id, str) or not track_id.strip():
            raise ValueError("distribution request requires track_id")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("distribution request requires title")
        if not isinstance(metadata, dict):
            raise ValueError("distribution request requires metadata object")
        if not isinstance(assets, dict):
            raise ValueError("distribution request requires assets object")

        bundle = {
            "schema": "blackmamba.distribution.bundle.v1",
            "preparedAt": _utc_now(),
            "jobId": job.job_id,
            "trackId": track_id,
            "title": title,
            "metadata": metadata,
            "assets": assets,
            "sources": job.inputs.get("sources", {}),
            "technical": job.inputs.get("technical", {}),
            "ratings": job.inputs.get("ratings", {}),
            "authorization": job.authorization,
            "publicationStatus": "not_published",
        }
        artifact = (
            self.artifacts
            / f"{job.job_id}.distribution-bundle.json"
        )
        temp = artifact.with_suffix(artifact.suffix + ".tmp")
        temp.write_text(
            json.dumps(bundle, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp.replace(artifact)

        validation: list[dict[str, Any]] = []
        for spec in job.validators:
            name = spec["name"]
            if name == "distribution_bundle_ready":
                ok = (
                    artifact.exists()
                    and bundle["publicationStatus"] == "not_published"
                )
                detail = (
                    f"bundle={artifact}; external publication not executed"
                )
            else:
                ok = False
                detail = f"unsupported validator: {name}"
            validation.append(
                {"validator": name, "ok": ok, "detail": detail}
            )

        if not validation:
            validation.append(
                {
                    "validator": "distribution_bundle_ready",
                    "ok": artifact.exists(),
                    "detail": (
                        f"bundle={artifact}; external publication not executed"
                    ),
                }
            )

        status = (
            "validated"
            if all(item["ok"] for item in validation)
            else "failed"
        )
        return self._result(
            job_id=job.job_id,
            idempotency_key=job.idempotency_key,
            status=status,
            started_at=started_at,
            validation=validation,
            artifacts=[
                {
                    "type": "distribution_bundle",
                    "path": str(artifact),
                    "track_id": track_id,
                    "publication_status": "not_published",
                }
            ],
            logs=[f"prepared distribution bundle for {title}"],
            evidence_links=[str(artifact)],
        )

    def _write_result(self, result: dict[str, Any]) -> Path:
        path = self.results / (
            f"{result['job_id']}{AUTOMATOR_RESULT_SUFFIX}"
        )
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(
            json.dumps(result, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp.replace(path)
        return path

    @staticmethod
    def _result(
        *,
        job_id: str,
        idempotency_key: str,
        status: str,
        started_at: str,
        validation: list[dict[str, Any]] | None = None,
        diff: dict[str, Any] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        logs: list[str] | None = None,
        errors: list[str] | None = None,
        evidence_links: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "idempotency_key": idempotency_key,
            "status": status,
            "started_at": started_at,
            "finished_at": _utc_now(),
            "validation": validation or [],
            "diff": diff or {},
            "artifacts": artifacts or [],
            "logs": logs or [],
            "errors": errors or [],
            "evidence_links": evidence_links or [],
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="warpblack-automator",
        description=(
            "Allowlisted WARPBLACK worker for BlackMamba Automator jobs"
        ),
    )
    parser.add_argument(
        "--queue",
        required=True,
        help="Shared Automator/WARPBLACK queue root",
    )
    parser.add_argument(
        "--workspace",
        required=True,
        help="Allowed local workspace root",
    )
    parser.add_argument(
        "--registry",
        default=str(DEFAULT_PROJECTS_FILE),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once",
        action="store_true",
        help="Process at most one job",
    )
    mode.add_argument(
        "--watch",
        action="store_true",
        help="Watch continuously",
    )
    parser.add_argument("--poll", type=float, default=2.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    worker = AutomatorQueueWorker(
        queue_dir=args.queue,
        workspace_root=args.workspace,
        project_registry_file=args.registry,
    )
    if args.watch:
        try:
            worker.watch(poll_interval_s=args.poll)
        except KeyboardInterrupt:
            return 0
        return 0

    processed = worker.run_once()
    print(json.dumps({"ok": True, "processed": processed}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
