from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, TypeAlias
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .audit import AuditLedger
from .construct import PatchConstructor
from .executor import TerminalExecutor
from .models import CommandRequest
from .policy import PolicyError
from .readme_absorb import ReadmeAbsorber


JOB_PROTOCOL = "warpblack-job-v1"
ABSORB_PROTOCOL = "warpblack-absorb-v1"
CONSTRUCT_PROTOCOL = "warpblack-construct-v1"
JOB_LABEL = "warpblack-job"
APPROVAL_LABEL = "warpblack-approved"
MAX_REMOTE_STREAM_CHARS = 12_000


class GitHubQueueError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitHubCommandJob:
    issue_number: int
    argv: tuple[str, ...]
    cwd: str
    timeout_s: float
    approved: bool
    actor: str


@dataclass(frozen=True)
class GitHubAbsorbJob:
    issue_number: int
    message: str
    project_name: str | None
    confirmed: tuple[str, ...]
    derived: tuple[str, ...]
    proposed: tuple[str, ...]
    actor: str


@dataclass(frozen=True)
class GitHubConstructJob:
    issue_number: int
    message: str
    objective: str
    patch: str
    checks: tuple[tuple[str, ...], ...]
    timeout_s: float
    task_id: str | None
    approved: bool
    actor: str


GitHubJob: TypeAlias = GitHubCommandJob | GitHubAbsorbJob | GitHubConstructJob


class GitHubControlPlane:
    """Pull-based private GitHub issue transport for WARPBLACK jobs."""

    def __init__(
        self,
        *,
        token: str,
        repository: str,
        allowed_actor: str,
        workspace_root: str | Path,
        audit_log: str | Path | None = None,
        api_url: str = "https://api.github.com",
    ) -> None:
        if "/" not in repository:
            raise ValueError("repository must be in owner/name form")
        if not token:
            raise ValueError("GitHub token is required")
        if not allowed_actor:
            raise ValueError("allowed_actor is required")
        self.token = token
        self.repository = repository
        self.allowed_actor = allowed_actor
        self.workspace_root = Path(workspace_root).resolve()
        self.api_url = api_url.rstrip("/")
        ledger = AuditLedger(audit_log) if audit_log is not None else None
        self.executor = TerminalExecutor(
            self.workspace_root,
            audit_ledger=ledger,
            source=f"github:{repository}",
            actor=allowed_actor,
        )
        self.absorber = ReadmeAbsorber(self.workspace_root)
        self.constructor = PatchConstructor(
            self.workspace_root,
            executor=self.executor,
            absorber=self.absorber,
        )

    def assert_private_repository(self) -> None:
        metadata = self._request_json("GET", f"/repos/{self.repository}")
        if metadata.get("private") is not True:
            raise GitHubQueueError(
                "control-plane repository must be private; refusing to expose terminal jobs"
            )

    def pending_jobs(self) -> list[GitHubJob]:
        label = quote(JOB_LABEL, safe="")
        issues = self._request_json(
            "GET",
            f"/repos/{self.repository}/issues?state=open&labels={label}&sort=created&direction=asc",
        )
        if not isinstance(issues, list):
            raise GitHubQueueError("unexpected GitHub issues response")

        jobs: list[GitHubJob] = []
        for issue in issues:
            try:
                job = parse_issue_job(issue, allowed_actor=self.allowed_actor)
            except (TypeError, ValueError, GitHubQueueError):
                continue
            if job is not None:
                jobs.append(job)
        return jobs

    def run_once(self) -> int:
        jobs = self.pending_jobs()
        if not jobs:
            return 0
        self._execute_job(jobs[0])
        return 1

    def watch(self, *, poll_interval_s: float = 5.0) -> None:
        if poll_interval_s < 1.0:
            raise ValueError("poll interval must be at least 1 second")
        self.assert_private_repository()
        while True:
            self.run_once()
            time.sleep(poll_interval_s)

    def _execute_job(self, job: GitHubJob) -> None:
        request_id = f"github:{self.repository}#{job.issue_number}"
        try:
            if isinstance(job, GitHubAbsorbJob):
                result = self.absorber.ingest(
                    message=job.message,
                    project_name=job.project_name,
                    confirmed=job.confirmed,
                    derived=job.derived,
                    proposed=job.proposed,
                )
                payload = result.to_dict()
                payload["request_id"] = request_id
                payload["job_type"] = "absorb"
            elif isinstance(job, GitHubConstructJob):
                if not job.approved:
                    raise PolicyError(
                        f"remote construct requires the separate {APPROVAL_LABEL!r} label"
                    )
                result = self.constructor.construct(
                    message=job.message,
                    objective=job.objective,
                    patch=job.patch,
                    checks=job.checks,
                    timeout_s=job.timeout_s,
                    task_id=job.task_id or f"github-{job.issue_number}",
                    approved=True,
                )
                payload: dict[str, Any] = result.to_dict()
                payload["request_id"] = request_id
                payload["job_type"] = "construct"
                self._bound_construct_streams(payload)
            else:
                cwd = Path(job.cwd)
                if not cwd.is_absolute():
                    cwd = self.workspace_root / cwd
                request = CommandRequest.from_parts(
                    job.argv,
                    cwd,
                    timeout_s=job.timeout_s,
                    approved=job.approved,
                    request_id=request_id,
                )
                result = self.executor.execute(request)
                payload = result.to_dict()
                payload["ok"] = result.exit_code == 0 and not result.timed_out
                payload["job_type"] = "command"
                self._bound_stream(payload, "stdout")
                self._bound_stream(payload, "stderr")
        except (PolicyError, FileNotFoundError, FileExistsError, PermissionError, OSError, ValueError) as exc:
            payload = {
                "ok": False,
                "request_id": request_id,
                "job_type": (
                    "construct"
                    if isinstance(job, GitHubConstructJob)
                    else "absorb"
                    if isinstance(job, GitHubAbsorbJob)
                    else "command"
                ),
                "error": str(exc),
            }

        body = "WARPBLACK_RESULT_V1\n```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
        self._request_json(
            "POST",
            f"/repos/{self.repository}/issues/{job.issue_number}/comments",
            {"body": body},
        )
        self._request_json(
            "PATCH",
            f"/repos/{self.repository}/issues/{job.issue_number}",
            {"state": "closed"},
        )

    @classmethod
    def _bound_construct_streams(cls, payload: dict[str, Any]) -> None:
        for key in ("apply_check", "apply_result", "workspace_status", "diff_stat"):
            value = payload.get(key)
            if isinstance(value, dict):
                cls._bound_stream(value, "stdout")
                cls._bound_stream(value, "stderr")
        checks = payload.get("checks")
        if isinstance(checks, list):
            for value in checks:
                if isinstance(value, dict):
                    cls._bound_stream(value, "stdout")
                    cls._bound_stream(value, "stderr")

    @staticmethod
    def _bound_stream(payload: dict[str, Any], key: str) -> None:
        value = payload.get(key)
        if not isinstance(value, str) or len(value) <= MAX_REMOTE_STREAM_CHARS:
            return
        payload[f"{key}_sha256"] = hashlib.sha256(value.encode("utf-8")).hexdigest()
        payload[f"{key}_truncated"] = True
        payload[key] = value[:MAX_REMOTE_STREAM_CHARS]

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        data = None
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "WARPBLACK",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(
            f"{self.api_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise GitHubQueueError(f"GitHub HTTP {exc.code}: {raw}") from exc
        except URLError as exc:
            raise GitHubQueueError(f"GitHub unavailable: {exc.reason}") from exc


def parse_issue_job(issue: object, *, allowed_actor: str) -> GitHubJob | None:
    if not isinstance(issue, dict):
        raise TypeError("issue must be an object")
    if "pull_request" in issue:
        return None

    user = issue.get("user")
    if not isinstance(user, dict) or user.get("login") != allowed_actor:
        return None

    labels_raw = issue.get("labels", [])
    labels = {
        label.get("name")
        for label in labels_raw
        if isinstance(label, dict) and isinstance(label.get("name"), str)
    }
    if JOB_LABEL not in labels:
        return None

    body = issue.get("body")
    if not isinstance(body, str):
        raise GitHubQueueError("job issue body must be JSON")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise GitHubQueueError("job issue body must contain only JSON") from exc
    if not isinstance(payload, dict):
        raise GitHubQueueError("job payload must be a JSON object")

    issue_number = issue.get("number")
    if not isinstance(issue_number, int):
        raise GitHubQueueError("issue number missing")

    protocol = payload.get("protocol")
    approved = APPROVAL_LABEL in labels
    timeout_s = payload.get("timeout_s", 60.0)
    if not isinstance(timeout_s, (int, float)):
        raise GitHubQueueError("timeout_s must be numeric")

    if protocol == JOB_PROTOCOL:
        argv = payload.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
            raise GitHubQueueError("argv must be a non-empty list of strings")
        cwd = payload.get("cwd", ".")
        if not isinstance(cwd, str):
            raise GitHubQueueError("cwd must be a string")
        return GitHubCommandJob(
            issue_number=issue_number,
            argv=tuple(argv),
            cwd=cwd,
            timeout_s=float(timeout_s),
            approved=approved,
            actor=allowed_actor,
        )

    if protocol == ABSORB_PROTOCOL:
        message = payload.get("message")
        if not isinstance(message, str):
            raise GitHubQueueError("absorb message must be a string")
        project_name = payload.get("project_name")
        if project_name is not None and not isinstance(project_name, str):
            raise GitHubQueueError("absorb project_name must be a string")

        classified: dict[str, tuple[str, ...]] = {}
        for key in ("confirmed", "derived", "proposed"):
            raw = payload.get(key, [])
            if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
                raise GitHubQueueError(f"absorb {key} must be a list of strings")
            classified[key] = tuple(raw)

        return GitHubAbsorbJob(
            issue_number=issue_number,
            message=message,
            project_name=project_name,
            confirmed=classified["confirmed"],
            derived=classified["derived"],
            proposed=classified["proposed"],
            actor=allowed_actor,
        )

    if protocol == CONSTRUCT_PROTOCOL:
        message = payload.get("message")
        objective = payload.get("objective")
        patch = payload.get("patch")
        if not isinstance(message, str):
            raise GitHubQueueError("construct message must be a string")
        if not isinstance(objective, str):
            raise GitHubQueueError("construct objective must be a string")
        if not isinstance(patch, str):
            raise GitHubQueueError("construct patch must be a string")

        raw_checks = payload.get("checks", [])
        if not isinstance(raw_checks, list):
            raise GitHubQueueError("construct checks must be a list")
        checks: list[tuple[str, ...]] = []
        for item in raw_checks:
            if not isinstance(item, list) or not item or not all(isinstance(arg, str) for arg in item):
                raise GitHubQueueError("each construct check must be a non-empty argv list")
            checks.append(tuple(item))

        task_id = payload.get("task_id")
        if task_id is not None and not isinstance(task_id, str):
            raise GitHubQueueError("construct task_id must be a string")

        return GitHubConstructJob(
            issue_number=issue_number,
            message=message,
            objective=objective,
            patch=patch,
            checks=tuple(checks),
            timeout_s=float(timeout_s),
            task_id=task_id,
            approved=approved,
            actor=allowed_actor,
        )

    raise GitHubQueueError("unsupported job protocol")


def token_from_env() -> str:
    token = os.environ.get("WARPBLACK_GITHUB_TOKEN", "")
    if not token:
        raise GitHubQueueError("WARPBLACK_GITHUB_TOKEN is required")
    return token
