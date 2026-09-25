from __future__ import annotations

from dataclasses import dataclass, asdict
import os
from pathlib import Path
import shutil
import sys


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


def run_doctor(
    *,
    workspace: str | Path = ".",
    repository: str | None = None,
    actor: str | None = None,
) -> dict[str, object]:
    root = Path(workspace).expanduser().resolve()
    checks: list[DoctorCheck] = []

    checks.append(
        DoctorCheck(
            "python",
            sys.version_info >= (3, 11),
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        )
    )
    checks.append(DoctorCheck("git", shutil.which("git") is not None, shutil.which("git") or "missing"))
    checks.append(
        DoctorCheck("github_cli", shutil.which("gh") is not None, shutil.which("gh") or "missing")
    )
    checks.append(DoctorCheck("workspace", root.is_dir(), str(root)))

    if repository:
        checks.append(
            DoctorCheck(
                "control_repo_format",
                repository.count("/") == 1 and all(part.strip() for part in repository.split("/")),
                repository,
            )
        )

    token_present = bool(os.environ.get("WARPBLACK_GITHUB_TOKEN"))
    gh_present = shutil.which("gh") is not None
    checks.append(
        DoctorCheck(
            "github_auth_source",
            token_present or gh_present,
            "WARPBLACK_GITHUB_TOKEN" if token_present else "gh CLI" if gh_present else "missing",
        )
    )

    if actor:
        checks.append(DoctorCheck("actor", bool(actor.strip()), actor))

    failures = [check for check in checks if not check.ok]
    return {
        "ok": not failures,
        "workspace": str(root),
        "checks": [asdict(check) for check in checks],
        "failures": [check.name for check in failures],
    }
