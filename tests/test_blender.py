from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

import warpblack.blender as blender
from warpblack.blender import BlenderError, translate_restore


def test_translate_restore_requires_approval(tmp_path: Path) -> None:
    scene = tmp_path / "scene.blend"
    scene.write_bytes(b"BLENDER")

    with pytest.raises(BlenderError, match="approval"):
        translate_restore(
            scene,
            object_name="Cube",
            delta=[0.01, 0.0, 0.0],
            approved=False,
        )


def test_translate_restore_rejects_large_delta(tmp_path: Path) -> None:
    scene = tmp_path / "scene.blend"
    scene.write_bytes(b"BLENDER")

    with pytest.raises(BlenderError, match="safety limit"):
        translate_restore(
            scene,
            object_name="Cube",
            delta=[1.0, 0.0, 0.0],
            approved=True,
        )


def test_translate_restore_parses_and_verifies_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    scene = tmp_path / "scene.blend"
    scene.write_bytes(b"BLENDER")
    monkeypatch.setattr(blender, "_trusted_blender_binary", lambda: "/trusted/blender")

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "Blender 5.2.0\n"
                'WARPBLACK_BLENDER_RESULT={"after":[1.01,2.0,3.0],'
                '"before":[1.0,2.0,3.0],"restore_verified":true,'
                '"restored":[1.0,2.0,3.0]}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr(blender.subprocess, "run", fake_run)

    result = translate_restore(
        scene,
        object_name="Mirror_L",
        delta=[0.01, 0.0, 0.0],
        approved=True,
    )

    assert result.before == (1.0, 2.0, 3.0)
    assert result.after == (1.01, 2.0, 3.0)
    assert result.restored == result.before
    assert result.restore_verified is True
