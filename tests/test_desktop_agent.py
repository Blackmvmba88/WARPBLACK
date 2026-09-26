from __future__ import annotations

import math
import pytest

import warpblack.desktop_agent as agent
from warpblack.desktop import DesktopError, DesktopResult
from warpblack.desktop_agent import UIElement, click_label, find_ui_elements, inspect_ui


def _payload(elements: list[UIElement]) -> DesktopResult:
    return DesktopResult(
        True,
        "ui-elements",
        {
            "target": {"application": "Blender", "pid": 77, "title": "Scene.blend"},
            "elements": [item.to_dict() for item in elements],
        },
    )


def test_inspect_ui_binds_scan_to_validated_pid(monkeypatch) -> None:
    focus = {"application": "Blender", "pid": 77, "title": "Scene.blend"}
    monkeypatch.setattr(agent, "_assert_focused_window", lambda **kwargs: focus)
    scripts: list[list[str]] = []

    def fake_run(lines, *, timeout_s=10.0):
        scripts.append(list(lines))
        return "AXButton\tRender\t\t100\t50\t80\t30"

    monkeypatch.setattr(agent, "_run_osascript", fake_run)

    payload = inspect_ui().to_dict()

    script = "\n".join(scripts[0])
    assert "unix id is 77" in script
    assert "validated application lost focus" in script
    assert payload["data"]["target"]["pid"] == 77


def test_find_ui_elements_prefers_exact_match(monkeypatch) -> None:
    elements = [
        UIElement("AXButton", "Save As", "", 10, 10, 80, 20),
        UIElement("AXButton", "Save", "", 100, 10, 80, 20),
    ]
    monkeypatch.setattr(agent, "inspect_ui", lambda **kwargs: _payload(elements))

    matches = find_ui_elements("save")

    assert [item.name for item in matches] == ["Save"]


def test_find_ui_elements_ignores_non_actionable_roles(monkeypatch) -> None:
    elements = [
        UIElement("AXStaticText", "Render", "", 10, 10, 80, 20),
        UIElement("AXButton", "Render", "", 100, 10, 80, 20),
    ]
    monkeypatch.setattr(agent, "inspect_ui", lambda **kwargs: _payload(elements))

    matches = find_ui_elements("Render", exact=True)

    assert len(matches) == 1
    assert matches[0].role == "AXButton"


def test_click_label_requires_approval() -> None:
    with pytest.raises(DesktopError, match="explicit approval"):
        click_label("Render")


@pytest.mark.parametrize("settle", [math.nan, math.inf, -math.inf, -0.1, 5.1])
def test_click_label_rejects_invalid_settle_before_mutation(settle) -> None:
    with pytest.raises(DesktopError, match="settle time"):
        click_label("Render", approved=True, settle_s=settle)


def test_click_label_fails_closed_when_ambiguous(monkeypatch) -> None:
    monkeypatch.setattr(
        agent,
        "_assert_focused_window",
        lambda **kwargs: {"application": "Blender", "pid": 77, "title": "Scene.blend"},
    )
    monkeypatch.setattr(
        agent,
        "find_ui_elements",
        lambda *args, **kwargs: [
            UIElement("AXButton", "OK", "", 10, 10, 40, 20),
            UIElement("AXButton", "OK", "", 60, 10, 40, 20),
        ],
    )

    with pytest.raises(DesktopError, match="ambiguous"):
        click_label("OK", approved=True)


def test_click_label_clicks_center_and_allows_focus_change(monkeypatch) -> None:
    focus = {"application": "Blender", "pid": 77, "title": "Scene.blend"}
    next_focus = {"application": "Safari", "pid": 88, "title": "Result"}
    monkeypatch.setattr(agent, "_assert_focused_window", lambda **kwargs: focus)
    monkeypatch.setattr(agent, "focused_window", lambda: DesktopResult(True, "focused-window", next_focus))
    monkeypatch.setattr(
        agent,
        "find_ui_elements",
        lambda *args, **kwargs: [UIElement("AXLink", "Docs", "", 100, 50, 80, 30)],
    )

    calls: list[tuple[int, int, dict[str, object]]] = []

    def fake_click(x: int, y: int, **kwargs):
        calls.append((x, y, kwargs))
        return DesktopResult(True, "click", {"x": x, "y": y, "target": focus})

    monkeypatch.setattr(agent, "click_at", fake_click)

    result = click_label("Docs", approved=True)

    assert calls[0][0:2] == (140, 65)
    assert calls[0][2]["expected_pid"] == 77
    assert result.data["post_focus"]["pid"] == 88
    assert result.data["focus_changed"] is True
