from __future__ import annotations

import json

import warpblack.cli as cli


class _FakeResult:
    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "capability": "blender.object.translate_restore",
            "changed": False,
        }


class _FakeRegistry:
    last_intent = None
    last_workspace = None

    def __init__(self, workspace):
        type(self).last_workspace = workspace

    def execute(self, intent):
        type(self).last_intent = intent
        return _FakeResult()


def test_blender_translate_restore_cli_builds_structured_intent(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli, "CapabilityRegistry", _FakeRegistry)

    code = cli.main(
        [
            "blender",
            "translate-restore",
            "COMBI_TOPOLOGIA_PRO.blend",
            "--workspace",
            str(tmp_path),
            "--object",
            "Mirror_L",
            "--dx",
            "0.01",
            "--approve",
            "--request-id",
            "bm-blender-001-mirror-l-10mm",
            "--project",
            "COMBI",
        ]
    )

    assert code == 0
    intent = _FakeRegistry.last_intent
    assert intent.intent == "blender.object.translate_restore"
    assert intent.target == "COMBI_TOPOLOGIA_PRO.blend"
    assert intent.project == "COMBI"
    assert intent.request_id == "bm-blender-001-mirror-l-10mm"
    assert intent.constraints == {
        "object": "Mirror_L",
        "delta": [0.01, 0.0, 0.0],
        "approved": True,
        "timeout_s": 120.0,
    }
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True


def test_blender_translate_restore_cli_preserves_missing_approval(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(cli, "CapabilityRegistry", _FakeRegistry)

    code = cli.main(
        [
            "blender",
            "translate-restore",
            "scene.blend",
            "--workspace",
            str(tmp_path),
            "--object",
            "Cube",
            "--dx",
            "0.01",
        ]
    )

    assert code == 0
    assert _FakeRegistry.last_intent.constraints["approved"] is False


def test_blender_certify_cli_selects_certificate_capability(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(cli, "CapabilityRegistry", _FakeRegistry)

    code = cli.main(
        [
            "blender",
            "certify-translate-restore",
            "COMBI_TOPOLOGIA_PRO.blend",
            "--workspace",
            str(tmp_path),
            "--object",
            "Mirror_L",
            "--dx",
            "0.01",
            "--approve",
            "--request-id",
            "bm-blender-002-mirror-l-10mm",
        ]
    )

    assert code == 0
    assert (
        _FakeRegistry.last_intent.intent
        == "blender.object.translate_restore_certify"
    )
    assert _FakeRegistry.last_intent.constraints["approved"] is True
