from __future__ import annotations

import pytest

import warpblack.desktop_agent as agent
from warpblack.desktop import DesktopError, DesktopResult
from warpblack.desktop_agent import UIElement, click_label, find_ui_elements


def _payload(elements: list[UIElement]) -> DesktopResult:
    return DesktopResult(
        True,
        "ui-elements",
        {
            "target": {"application": "Blender", "pid": 77, "title": "Scene.blend"},
            "elements": [item.to_dict() for item in elements],
        },
    )


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


def test_click_label_clicks_center_and_checks_focus(monkeypatch) -> None:
    focus = {"application": "Blender", "pid": 77, "title": "Scene.blend"}
    monkeypatch.setattr(agent, "_assert_focused_window", lambda **kwargs: focus)
    monkeypatch.setattr(
        agent,
        "find_ui_elements",
        lambda *args, **kwargs: [UIElement("AXButton", "Render", "", 100, 50, 80, 30)],
    )

    calls: list[tuple[int, int, dict[str, object]]] = []

    def fake_click(x: int, y: int, **kwargs):
        calls.append((x, y, kwargs))
        return DesktopResult(True, "click", {"x": x, "y": y, "target": focus})

    monkeypatch.setattr(agent, "click_at", fake_click)

    result = click_label("Render", approved=True)

    assert calls[0][0:2] == (140, 65)
    assert calls[0][2]["expected_pid"] == 77
    assert result.data["matched"]["label"] == "Render"
