from __future__ import annotations

import pytest

from warpblack.desktop import DesktopError, DesktopResult, activate_application, click_at


def test_desktop_result_serializes() -> None:
    result = DesktopResult(True, "frontmost", {"application": "Finder"})
    assert result.to_dict()["data"]["application"] == "Finder"


def test_activate_requires_approval() -> None:
    with pytest.raises(DesktopError, match="explicit approval"):
        activate_application("Finder", approved=False)


def test_click_requires_approval() -> None:
    with pytest.raises(DesktopError, match="explicit approval"):
        click_at(10, 20, approved=False)


def test_click_rejects_negative_coordinates() -> None:
    with pytest.raises(DesktopError, match="non-negative"):
        click_at(-1, 20, approved=True)


@pytest.mark.parametrize("titles", [[], ["A, B\tC\n雪", "Untitled - Blender"]])
def test_windows_preserves_json_boundaries(monkeypatch, titles):
    import json

    from warpblack import desktop
    windows = [{"application": "Blender", "title": title} for title in titles]
    monkeypatch.setattr(desktop, "_run_osascript", lambda *a, **k: json.dumps({
        "windows": windows, "errors": [],
    }))
    assert desktop.list_windows().data["windows"] == windows


def test_windows_reports_partial_failure(monkeypatch):
    from warpblack import desktop
    monkeypatch.setattr(desktop, "_desktop_json", lambda script: {
        "windows": [], "errors": [{"application": "Finder", "error": "denied"}],
    })
    assert not desktop.list_windows().ok


def test_focused_window_without_window(monkeypatch):
    from warpblack import desktop
    data = {"application": "Finder", "title": None, "frontmost": True}
    import json

    monkeypatch.setattr(desktop, "_run_osascript", lambda *a, **k: json.dumps(data))
    assert desktop.focused_window().data == data


def test_invalid_desktop_json(monkeypatch):
    from warpblack import desktop
    monkeypatch.setattr(desktop, "_run_osascript", lambda *a, **k: "broken")
    with pytest.raises(DesktopError, match="JSON"):
        desktop.list_windows()
