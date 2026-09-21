from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from warpblack.capabilities import CapabilityError, CapabilityRegistry
from warpblack.contracts import IntentEnvelope


def test_files_read_returns_structured_content(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    marker.write_text("mamba\n", encoding="utf-8")
    registry = CapabilityRegistry(tmp_path)

    result = registry.execute(
        IntentEnvelope.from_payload(
            {
                "intent": "files.read",
                "target": "marker.txt",
                "project": "Bridge Demo",
                "request_id": "read-1",
            }
        )
    )

    payload = result.to_dict()
    assert payload["ok"] is True
    assert payload["capability"] == "files.read"
    assert payload["changed"] is False
    assert payload["evidence"]["content"] == "mamba\n"
    assert payload["plan"]["mutates"] is False


def test_files_read_rejects_workspace_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    registry = CapabilityRegistry(tmp_path)

    with pytest.raises(CapabilityError, match="escapes"):
        registry.execute(
            IntentEnvelope.from_payload(
                {
                    "intent": "files.read",
                    "target": str(outside),
                }
            )
        )


def test_files_read_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-symlink-secret.txt"
    outside.write_text("secret\n", encoding="utf-8")
    link = tmp_path / "inside.txt"
    link.symlink_to(outside)
    registry = CapabilityRegistry(tmp_path)

    with pytest.raises(CapabilityError, match="escapes"):
        registry.execute(
            IntentEnvelope.from_payload(
                {
                    "intent": "files.read",
                    "target": "inside.txt",
                }
            )
        )


def test_git_status_runs_through_structured_capability(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "marker.txt").write_text("mamba\n", encoding="utf-8")
    registry = CapabilityRegistry(tmp_path)

    result = registry.execute(
        IntentEnvelope.from_payload(
            {
                "intent": "git.status",
                "target": ".",
                "request_id": "status-1",
            }
        )
    )

    payload = result.to_dict()
    assert payload["ok"] is True
    assert payload["changed"] is False
    assert payload["evidence"]["worktree_dirty"] is True
    assert "marker.txt" in payload["evidence"]["stdout"]


def test_plan_rejects_unknown_intent(tmp_path: Path) -> None:
    registry = CapabilityRegistry(tmp_path)
    intent = IntentEnvelope.from_payload({"intent": "blender.render"})

    with pytest.raises(CapabilityError, match="unknown intent"):
        registry.plan(intent)
