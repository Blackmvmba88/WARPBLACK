from pathlib import Path

from warpblack.doctor import run_doctor


def test_doctor_reports_workspace(tmp_path: Path) -> None:
    payload = run_doctor(workspace=tmp_path, repository="owner/control", actor="owner")
    assert payload["workspace"] == str(tmp_path.resolve())
    names = {item["name"] for item in payload["checks"]}
    assert "python" in names
    assert "workspace" in names
    assert "control_repo_format" in names


def test_doctor_flags_bad_repository(tmp_path: Path) -> None:
    payload = run_doctor(workspace=tmp_path, repository="not-a-repo")
    checks = {item["name"]: item for item in payload["checks"]}
    assert checks["control_repo_format"]["ok"] is False
