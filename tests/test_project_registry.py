from pathlib import Path
import json

import pytest

from warpblack.project_registry import ProjectRegistry, ProjectRegistryError


def test_add_project_creates_logical_registry_without_moving_folder(tmp_path: Path) -> None:
    project = tmp_path / "alpha"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='alpha'\n", encoding="utf-8")
    state = tmp_path / "state" / "projects.json"

    registry = ProjectRegistry(state)
    entry = registry.add(project)

    assert entry.name == "alpha"
    assert entry.path == str(project.resolve())
    assert entry.order == 0
    assert entry.metadata is not None
    assert "python" in entry.metadata["languages"]
    assert project.exists()
    assert json.loads(state.read_text(encoding="utf-8"))["projects"][0]["name"] == "alpha"


def test_duplicate_path_updates_entry_instead_of_creating_duplicate(tmp_path: Path) -> None:
    project = tmp_path / "alpha"
    project.mkdir()
    state = tmp_path / "projects.json"
    registry = ProjectRegistry(state)

    first = registry.add(project)
    second = registry.add(project, name="ALPHA", group="audio")

    assert first.id == second.id
    assert len(registry.entries) == 1
    assert registry.entries[0].name == "ALPHA"
    assert registry.entries[0].group == "audio"


def test_manual_order_is_independent_from_filesystem_name(tmp_path: Path) -> None:
    state = tmp_path / "projects.json"
    registry = ProjectRegistry(state)
    for name in ("aaa", "bbb", "ccc"):
        folder = tmp_path / name
        folder.mkdir()
        registry.add(folder)

    registry.move("ccc", 0)

    assert [item.name for item in registry.entries] == ["ccc", "aaa", "bbb"]
    assert [item.order for item in registry.entries] == [0, 1, 2]


def test_scan_discovers_nested_projects_and_skips_build_folders(tmp_path: Path) -> None:
    root = tmp_path / "work"
    root.mkdir()

    one = root / "music"
    one.mkdir()
    (one / ".git").mkdir()

    two = root / "tools" / "visual"
    two.mkdir(parents=True)
    (two / "package.json").write_text("{}", encoding="utf-8")

    ignored = root / "app" / "node_modules" / "dependency"
    ignored.mkdir(parents=True)
    (ignored / "package.json").write_text("{}", encoding="utf-8")

    registry = ProjectRegistry(tmp_path / "projects.json")
    added = registry.scan(root, max_depth=2)

    assert {item.name for item in added} == {"music", "visual"}
    assert {item.name for item in registry.entries} == {"music", "visual"}


def test_missing_folder_is_rejected(tmp_path: Path) -> None:
    registry = ProjectRegistry(tmp_path / "projects.json")
    with pytest.raises(ProjectRegistryError, match="does not exist"):
        registry.add(tmp_path / "missing")
