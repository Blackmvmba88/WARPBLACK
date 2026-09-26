from __future__ import annotations

from pathlib import Path

import pytest

import warpblack.blender_certificate as certificate
from warpblack.blender import BlenderTransactionResult
from warpblack.blender_certificate import BlenderCertificateError, certify_translate_restore
from warpblack.desktop import DesktopResult


def _transaction(tmp_path: Path) -> BlenderTransactionResult:
    renders = {}
    for phase in ("before", "after", "restored"):
        path = tmp_path / f"{phase}.png"
        path.write_bytes(phase.encode())
        renders[phase] = {"path": str(path), "sha256": certificate._sha256(path)}
    return BlenderTransactionResult(
        file=str(tmp_path / "scene.blend"),
        object_name="Mirror_L",
        delta=(0.01, 0.0, 0.0),
        before=(1.0, 2.0, 3.0),
        after=(1.01, 2.0, 3.0),
        restored=(1.0, 2.0, 3.0),
        restore_verified=True,
        blender_binary="/trusted/blender",
        source_sha256_before="same",
        source_sha256_after="same",
        proof_renders=renders,
    )


def test_certificate_requires_blender_focused(tmp_path: Path, monkeypatch) -> None:
    scene = tmp_path / "scene.blend"
    scene.write_bytes(b"BLENDER")
    monkeypatch.setattr(
        certificate,
        "focused_window",
        lambda: DesktopResult(True, "focused-window", {
            "application": "Finder",
            "pid": 1,
            "frontmost": True,
            "title": "Finder",
        }),
    )

    with pytest.raises(BlenderCertificateError, match="must be Blender"):
        certify_translate_restore(
            scene,
            workspace_root=tmp_path,
            request_id="bm-blender-002",
            object_name="Mirror_L",
            delta=[0.01, 0.0, 0.0],
            approved=True,
        )


def test_certificate_writes_manifest_and_checksum(tmp_path: Path, monkeypatch) -> None:
    scene = tmp_path / "scene.blend"
    scene.write_bytes(b"BLENDER")
    identity = {
        "application": "Blender",
        "pid": 60293,
        "frontmost": True,
        "title": "COMBI_TOPOLOGIA_PRO.blend - Blender 5.2.0 LTS",
    }
    monkeypatch.setattr(
        certificate,
        "focused_window",
        lambda: DesktopResult(True, "focused-window", identity),
    )

    def fake_capture(output, **kwargs):
        path = Path(output)
        path.write_bytes(b"PNG")
        return DesktopResult(True, "capture", {"path": str(path), "target": identity})

    monkeypatch.setattr(certificate, "capture_screen", fake_capture)
    monkeypatch.setattr(
        certificate,
        "translate_restore",
        lambda *args, **kwargs: _transaction(tmp_path),
    )

    result = certify_translate_restore(
        scene,
        workspace_root=tmp_path,
        request_id="bm-blender-002 mirror",
        object_name="Mirror_L",
        delta=[0.01, 0.0, 0.0],
        approved=True,
    )

    cert = Path(result.certificate_path)
    assert cert.is_file()
    assert cert.parent.name == "bm-blender-002-mirror"
    assert (cert.parent / "certificate.sha256").is_file()
    assert result.desktop_identity["pid"] == 60293
    assert result.transaction.restore_verified is True
