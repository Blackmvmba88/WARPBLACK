import pytest

from warpblack import blender
from warpblack.desktop import DesktopError, DesktopResult


def focused(application="Blender"):
    return DesktopResult(True, "focused-window", {
        "application": application, "title": "Untitled - Blender 5.2.0 LTS", "frontmost": True,
    })


def test_shortcut_requires_approval_before_observation(monkeypatch):
    monkeypatch.setattr(blender, "focused_window", lambda: pytest.fail("side effect"))
    with pytest.raises(DesktopError, match="approval"):
        blender.shortcut("toggle-sidebar")


def test_shortcut_rejects_unknown_action():
    with pytest.raises(DesktopError, match="unsupported"):
        blender.shortcut("delete-all", approved=True)


def test_observe_rejects_wrong_app(monkeypatch):
    monkeypatch.setattr(blender, "focused_window", lambda: focused("Finder"))
    monkeypatch.setattr(blender, "capture_screen", lambda *a: pytest.fail("capture"))
    with pytest.raises(DesktopError, match="frontmost"):
        blender.observe()


def test_shortcut_evidence_is_not_visual_success(monkeypatch, tmp_path):
    monkeypatch.setattr(blender, "focused_window", focused)
    monkeypatch.setattr(blender.tempfile, "mkdtemp", lambda **k: str(tmp_path))
    monkeypatch.setattr(blender, "capture_screen", lambda p: p.write_bytes(p.name.encode()))
    calls = []
    monkeypatch.setattr(blender, "_run_osascript", lambda lines, **kwargs: calls.append(lines))
    monkeypatch.setattr(blender.time, "sleep", lambda n: None)
    result = blender.shortcut("toggle-sidebar", approved=True)
    assert result.data["capture_bytes_changed"]
    assert result.data["visual_verification"] == "needs-review"
    assert (tmp_path / "before.png").exists()
    assert (tmp_path / "after.png").exists()
    assert 'Blender lost focus' in '\n'.join(calls[0])


def test_shortcut_focus_loss_fails(monkeypatch, tmp_path):
    states = iter([focused(), focused("Finder")])
    monkeypatch.setattr(blender, "focused_window", lambda: next(states))
    monkeypatch.setattr(blender.tempfile, "mkdtemp", lambda **k: str(tmp_path))
    monkeypatch.setattr(blender, "capture_screen", lambda p: p.write_bytes(b"png"))
    monkeypatch.setattr(blender, "_run_osascript", lambda lines, **kwargs: None)
    monkeypatch.setattr(blender.time, "sleep", lambda n: None)
    with pytest.raises(DesktopError, match="frontmost"):
        blender.shortcut("toggle-sidebar", approved=True)
    assert not (tmp_path / "after.png").exists()


def test_shortcut_rejects_file_dialog_before_capture(monkeypatch):
    state = focused()
    state.data["title"] = "Blender File View"
    monkeypatch.setattr(blender, "focused_window", lambda: state)
    monkeypatch.setattr(blender, "capture_screen", lambda *a: pytest.fail("capture"))
    with pytest.raises(DesktopError, match="main editor"):
        blender.shortcut("toggle-sidebar", approved=True)


def test_cli_observe_returns_structured_result(monkeypatch, capsys):
    import json

    from warpblack.cli import main

    monkeypatch.setattr(blender, "observe", lambda: DesktopResult(
        True, "blender-observe", {"visual_verification": "needs-review"},
    ))
    assert main(["blender", "observe"]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "blender-observe"


def test_cli_shortcut_requires_approval(capsys):
    from warpblack.cli import main

    assert main(["blender", "shortcut", "toggle-sidebar"]) == 3
    assert "approval" in capsys.readouterr().err
