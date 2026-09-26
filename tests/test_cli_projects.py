from pathlib import Path
import json

from warpblack.cli import main


def test_projects_cli_add_list_and_move(tmp_path: Path, capsys) -> None:
    registry = tmp_path / "projects.json"
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    alpha.mkdir()
    beta.mkdir()

    assert main([
        "projects", "--registry", str(registry),
        "add", str(alpha),
    ]) == 0
    capsys.readouterr()

    assert main([
        "projects", "--registry", str(registry),
        "add", str(beta),
    ]) == 0
    capsys.readouterr()

    assert main([
        "projects", "--registry", str(registry),
        "move", "beta", "1",
    ]) == 0
    moved = json.loads(capsys.readouterr().out)
    assert [item["name"] for item in moved["projects"]] == ["beta", "alpha"]
    assert [item["position"] for item in moved["projects"]] == [1, 2]

    assert main([
        "projects", "--registry", str(registry),
        "list",
    ]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [item["name"] for item in listed["projects"]] == ["beta", "alpha"]
