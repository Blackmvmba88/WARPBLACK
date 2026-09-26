from __future__ import annotations

import math
from pathlib import Path

import pytest

import warpblack.desktop_visual as visual
from warpblack.desktop import DesktopError, DesktopResult
from warpblack.desktop_visual import click_visual_box


FOCUS = {"application": "Blender", "pid": 77, "title": "Scene.blend"}
SHA = "a" * 64


def _snapshot(sha: str = SHA) -> DesktopResult:
    return DesktopResult(
        True,
        "visual-snapshot",
        {
            "path": "/tmp/screen.png",
            "sha256": sha,
            "width": 1920,
            "height": 1080,
            "target": FOCUS,
        },
    )


def test_visual_click_requires_approval() -> None:
    with pytest.raises(DesktopError, match="explicit approval"):
        click_visual_box(
            10,
            20,
            100,
            40,
            snapshot_sha256=SHA,
            confidence=0.9,
        )


@pytest.mark.parametrize("confidence", [math.nan, math.inf, -0.1, 1.1])
def test_visual_click_rejects_invalid_confidence(confidence) -> None:
    with pytest.raises(DesktopError, match="confidence"):
        click_visual_box(
            10,
            20,
            100,
            40,
            snapshot_sha256=SHA,
            confidence=confidence,
            approved=True,
        )


def test_visual_click_rejects_stale_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(visual, "visual_snapshot", lambda *args, **kwargs: _snapshot("b" * 64))

    with pytest.raises(DesktopError, match="stale"):
        click_visual_box(
            10,
            20,
            100,
            40,
            snapshot_sha256=SHA,
            confidence=0.9,
            approved=True,
        )


def test_visual_click_rejects_box_outside_capture(monkeypatch) -> None:
    monkeypatch.setattr(visual, "visual_snapshot", lambda *args, **kwargs: _snapshot())

    with pytest.raises(DesktopError, match="escapes screenshot bounds"):
        click_visual_box(
            1900,
            100,
            100,
            40,
            snapshot_sha256=SHA,
            confidence=0.9,
            approved=True,
        )


def test_visual_click_uses_box_center_and_focus_lock(monkeypatch) -> None:
    monkeypatch.setattr(visual, "visual_snapshot", lambda *args, **kwargs: _snapshot())
    monkeypatch.setattr(
        visual,
        "focused_window",
        lambda: DesktopResult(True, "focused-window", FOCUS),
    )
    clicks: list[tuple[int, int, dict[str, object]]] = []

    def fake_click(x: int, y: int, **kwargs):
        clicks.append((x, y, kwargs))
        return DesktopResult(True, "click", {"x": x, "y": y, "target": FOCUS})

    monkeypatch.setattr(visual, "click_at", fake_click)

    result = click_visual_box(
        100,
        50,
        80,
        30,
        snapshot_sha256=SHA,
        confidence=0.97,
        label="Render icon",
        approved=True,
    )

    assert clicks[0][0:2] == (140, 65)
    assert clicks[0][2]["expected_pid"] == 77
    assert result.data["box"]["label"] == "Render icon"
    assert result.data["snapshot_sha256"] == SHA
