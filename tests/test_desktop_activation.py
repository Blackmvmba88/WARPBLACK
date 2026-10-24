from __future__ import annotations

import pytest
import warpblack.desktop as desktop
from warpblack.desktop import DesktopError, activate_application


def test_activation_requires_identity():
    with pytest.raises(DesktopError, match="exact PID"):
        activate_application("Blender", approved=True)


def test_activation_rejects_wrong_target_before_action(monkeypatch):
    import warpblack.desktop_target as target

    def reject(**kwargs):
        raise DesktopError("needs-review: target identity not found")

    monkeypatch.setattr(target, "resolve_window", reject)
    monkeypatch.setattr(desktop, "_run_osascript", lambda lines: pytest.fail("unexpected activation"))
    with pytest.raises(DesktopError, match="not found"):
        activate_application("Blender", approved=True, expected_pid=42, expected_title="Scene")


def test_activation_checks_readback(monkeypatch):
    import warpblack.desktop_target as target
    monkeypatch.setattr(target, "resolve_window", lambda **kw: {"pid": 42, "title": "Scene", "application": "Blender"})
    commands = []
    monkeypatch.setattr(desktop, "_run_osascript", lambda lines: commands.append(lines))
    monkeypatch.setattr(desktop, "_assert_focused_window", lambda **kw: {"pid": 42, "title": "Scene", "application": "Blender"})
    result = activate_application("Blender", approved=True, expected_pid=42, expected_title="Scene")
    assert result.ok and result.data["focused"]["pid"] == 42
    assert any("unix id is 42" in line for line in commands[0])


def test_activation_rejects_wrong_app_readback(monkeypatch):
    import warpblack.desktop_target as target
    monkeypatch.setattr(target, "resolve_window", lambda **kw: {"pid": 42, "title": "Scene", "application": "Blender"})
    monkeypatch.setattr(desktop, "_run_osascript", lambda lines: "")
    monkeypatch.setattr(desktop, "_assert_focused_window", lambda **kw: {"pid": 42, "title": "Scene", "application": "Other"})
    with pytest.raises(DesktopError, match="identity mismatch"):
        activate_application("Blender", approved=True, expected_pid=42, expected_title="Scene")


def test_activation_rejects_pid_focus_mismatch(monkeypatch):
    import warpblack.desktop_target as target

    monkeypatch.setattr(target, "resolve_window", lambda **kw: {"pid": 42, "title": "Scene", "application": "Blender"})
    monkeypatch.setattr(desktop, "_run_osascript", lambda lines: "")
    monkeypatch.setattr(desktop, "_assert_focused_window", lambda **kw: (_ for _ in ()).throw(DesktopError("focused window PID mismatch")))
    with pytest.raises(DesktopError, match="PID mismatch"):
        activate_application("Blender", approved=True, expected_pid=42, expected_title="Scene")


def test_activation_rejects_title_focus_mismatch(monkeypatch):
    import warpblack.desktop_target as target

    monkeypatch.setattr(target, "resolve_window", lambda **kw: {"pid": 42, "title": "Scene", "application": "Blender"})
    monkeypatch.setattr(desktop, "_run_osascript", lambda lines: "")
    monkeypatch.setattr(desktop, "_assert_focused_window", lambda **kw: (_ for _ in ()).throw(DesktopError("focused window title mismatch")))
    with pytest.raises(DesktopError, match="title mismatch"):
        activate_application("Blender", approved=True, expected_pid=42, expected_title="Scene")
