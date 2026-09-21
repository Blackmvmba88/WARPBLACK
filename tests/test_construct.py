from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from warpblack.construct import PatchConstructor, has_construct_trigger


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _hello_patch() -> str:
    return """diff --git a/hello.txt b/hello.txt
new file mode 100644
index 0000000..ce01362
--- /dev/null
+++ b/hello.txt
@@ -0,0 +1 @@
+hello
"""


def test_construct_trigger_normalizes_spanish_accent_and_punctuation() -> None:
    assert has_construct_trigger("bro, CONSTRÚYELO!!!") is True
    assert has_construct_trigger("construye-lo") is True
    assert has_construct_trigger("solo guarda contexto") is False


def test_construct_applies_patch_runs_checks_and_returns_diff(tmp_path: Path) -> None:
    _git_init(tmp_path)
    constructor = PatchConstructor(tmp_path)

    result = constructor.construct(
        message="constrúyelo",
        objective="create a hello marker",
        patch=_hello_patch(),
        checks=[["cat", "hello.txt"]],
        task_id="task-001",
    )

    assert result.status == "done"
    assert result.to_dict()["ok"] is True
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello\n"
    assert result.checks[0].stdout == "hello\n"
    assert "hello.txt" in result.diff_stat.stdout
    assert (tmp_path / ".warpblack/tasks/task-001/task.json").exists()


def test_construct_requires_explicit_trigger(tmp_path: Path) -> None:
    _git_init(tmp_path)
    constructor = PatchConstructor(tmp_path)

    with pytest.raises(ValueError, match="explicit"):
        constructor.construct(
            message="maybe build this",
            objective="create marker",
            patch=_hello_patch(),
        )

    assert not (tmp_path / "hello.txt").exists()


def test_construct_rejects_control_plane_patch_paths(tmp_path: Path) -> None:
    _git_init(tmp_path)
    constructor = PatchConstructor(tmp_path)
    patch = """diff --git a/.warpblack/state.json b/.warpblack/state.json
new file mode 100644
--- /dev/null
+++ b/.warpblack/state.json
@@ -0,0 +1 @@
+{}
"""

    with pytest.raises(ValueError, match="not allowed"):
        constructor.construct(
            message="constrúyelo",
            objective="tamper with control state",
            patch=patch,
        )


def test_failed_check_keeps_patch_for_review(tmp_path: Path) -> None:
    _git_init(tmp_path)
    constructor = PatchConstructor(tmp_path)

    result = constructor.construct(
        message="constrúyelo",
        objective="create marker",
        patch=_hello_patch(),
        checks=[["cat", "missing.txt"]],
        task_id="task-review",
    )

    assert result.status == "needs-review"
    assert result.to_dict()["ok"] is False
    assert (tmp_path / "hello.txt").exists()
