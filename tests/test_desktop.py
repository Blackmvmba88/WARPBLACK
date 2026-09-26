from __future__ import annotations

import pytest

import warpblack.desktop as desktop
from warpblack.desktop import (
    DesktopError,
    DesktopResult,
    activate_application,
    click_at,
    focused_window,
    list_windows,
)


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


def test_focused_window_returns_pid_title_and_frontmost(monkeypatch) -> None:
    monkeypatch.setattr(
        desktop,
        "_run_osascript",
        lambda lines: "Blender\t60293\ttrue\tCOMBI_TOPOLOGIA_PRO.blend - Blender 5.2.0 LTS",
    )

    payload = focused_window().to_dict()

    assert payload["data"] == {
        "application": "Blender",
        "pid": 60293,
        "frontmost": True,
        "title": "COMBI_TOPOLOGIA_PRO.blend - Blender 5.2.0 LTS",
    }


def test_windows_keep_multiple_same_app_instances_separate(monkeypatch) -> None:
    monkeypatch.setattr(
        desktop,
        "_run_osascript",
        lambda lines: (
            "Blender\t60001\tfalse\tUntitled - Blender 5.2.0 LTS\n"
            "Blender\t60293\ttrue\tCOMBI_TOPOLOGIA_PRO.blend - Blender 5.2.0 LTS"
        ),
    )

    payload = list_windows().to_dict()

    assert [item["pid"] for item in payload["data"]["windows"]] == [60001, 60293]
    assert payload["data"]["windows"][1]["frontmost"] is True
    assert payload["data"]["errors"] == []


def test_click_fails_closed_on_pid_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(
        desktop,
        "_run_osascript",
        lambda lines: "Blender\t60293\ttrue\tCOMBI_TOPOLOGIA_PRO.blend",
    )

    with pytest.raises(DesktopError, match="PID mismatch"):
        click_at(10, 20, approved=True, expected_pid=60001)


def test_click_fails_closed_on_title_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(
        desktop,
        "_run_osascript",
        lambda lines: "Blender\t60293\ttrue\tCOMBI_TOPOLOGIA_PRO.blend",
    )

    with pytest.raises(DesktopError, match="title mismatch"):
        click_at(
            10,
            20,
            approved=True,
            expected_pid=60293,
            expected_title="Untitled - Blender",
        )
