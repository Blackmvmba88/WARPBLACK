from __future__ import annotations

import pytest
from warpblack.desktop import DesktopError, DesktopResult
import warpblack.desktop_target as target


@pytest.fixture
def windows(monkeypatch):
    rows = [
        {"application": "Blender", "pid": 60001, "title": "Untitled - Blender", "frontmost": False},
        {"application": "Blender", "pid": 60293, "title": "COMBI_TOPOLOGIA_PRO.blend", "frontmost": True},
    ]
    monkeypatch.setattr(target, "list_windows", lambda: DesktopResult(True, "windows", {"windows": rows}))
    return rows


def test_resolves_exact_pid_and_title(windows):
    assert target.resolve_window(pid=60293, title="COMBI_TOPOLOGIA_PRO.blend") == windows[1]


def test_rejects_ambiguous_application(windows):
    with pytest.raises(DesktopError, match="requires PID or exact"):
        target.resolve_window(application="Blender")


def test_rejects_wrong_pid_title_pair(windows):
    with pytest.raises(DesktopError, match="not found"):
        target.resolve_window(pid=60001, title="COMBI_TOPOLOGIA_PRO.blend")


def test_rejects_duplicate_titles(windows):
    windows[0]["title"] = windows[1]["title"]
    with pytest.raises(DesktopError, match="ambiguous"):
        target.resolve_window(title="COMBI_TOPOLOGIA_PRO.blend")


def test_rejects_invalid_pid(windows):
    with pytest.raises(DesktopError, match="positive integer"):
        target.resolve_window(pid=-1)
