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
