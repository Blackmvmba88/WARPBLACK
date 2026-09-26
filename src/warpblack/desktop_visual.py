from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import Path
import subprocess
import tempfile
import time
from uuid import uuid4

from .desktop import (
    DesktopError,
    DesktopResult,
    capture_screen,
    click_at,
    focused_window,
)


@dataclass(frozen=True)
class VisualBox:
    x: int
    y: int
    width: int
    height: int
    confidence: float
    label: str | None = None

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["center"] = list(self.center)
        return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_dimensions(path: Path) -> tuple[int, int]:
    completed = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "sips failed").strip()
        raise DesktopError(message)

    width: int | None = None
    height: int | None = None
    for raw in completed.stdout.splitlines():
        line = raw.strip()
        if line.startswith("pixelWidth:"):
            width = int(line.split(":", 1)[1].strip())
        elif line.startswith("pixelHeight:"):
            height = int(line.split(":", 1)[1].strip())

    if width is None or height is None or width <= 0 or height <= 0:
        raise DesktopError("could not determine screenshot dimensions")
    return width, height


def visual_snapshot(
    output: str | Path | None = None,
    *,
    expected_pid: int | None = None,
    expected_title: str | None = None,
) -> DesktopResult:
    if output is None:
        target = Path(tempfile.gettempdir()) / f"warpblack-visual-{uuid4().hex}.png"
    else:
        target = Path(output).expanduser().resolve()

    captured = capture_screen(
        target,
        expected_pid=expected_pid,
        expected_title=expected_title,
    )
    width, height = _image_dimensions(target)
    return DesktopResult(
        True,
        "visual-snapshot",
        {
            "path": str(target),
            "sha256": _sha256(target),
            "width": width,
            "height": height,
            "target": captured.data["target"],
        },
    )


def _validate_sha256(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise DesktopError("snapshot SHA-256 must be a 64-character hex digest")
    return normalized


def click_visual_box(
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    snapshot_sha256: str,
    confidence: float,
    label: str | None = None,
    min_confidence: float = 0.65,
    approved: bool = False,
    verify_change: bool = False,
    settle_s: float = 0.15,
    expected_pid: int | None = None,
    expected_title: str | None = None,
) -> DesktopResult:
    if not approved:
        raise DesktopError("desktop mutation requires explicit approval")

    expected_sha = _validate_sha256(snapshot_sha256)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise DesktopError("visual box must have non-negative origin and positive size")

    if not math.isfinite(confidence) or confidence < 0 or confidence > 1:
        raise DesktopError("confidence must be finite and between 0 and 1")
    if not math.isfinite(min_confidence) or min_confidence < 0 or min_confidence > 1:
        raise DesktopError("minimum confidence must be finite and between 0 and 1")
    if confidence < min_confidence:
        raise DesktopError(
            f"visual target confidence {confidence:.3f} is below threshold {min_confidence:.3f}"
        )
    if not math.isfinite(settle_s) or settle_s < 0 or settle_s > 5:
        raise DesktopError("settle time must be finite and between 0 and 5 seconds")

    before_path = Path(tempfile.gettempdir()) / f"warpblack-visual-check-{uuid4().hex}.png"
    after_path: Path | None = None
    try:
        snapshot = visual_snapshot(
            before_path,
            expected_pid=expected_pid,
            expected_title=expected_title,
        )
        current_sha = str(snapshot.data["sha256"])
        if current_sha != expected_sha:
            raise DesktopError(
                "visual snapshot is stale; screen changed since the target was planned"
            )

        screen_width = int(snapshot.data["width"])
        screen_height = int(snapshot.data["height"])
        if x + width > screen_width or y + height > screen_height:
            raise DesktopError(
                f"visual box escapes screenshot bounds {screen_width}x{screen_height}"
            )

        target = VisualBox(
            x=int(x),
            y=int(y),
            width=int(width),
            height=int(height),
            confidence=float(confidence),
            label=label,
        )
        cx, cy = target.center

        focused = snapshot.data["target"]
        pid = int(focused["pid"])
        title = str(focused["title"])
        click_result = click_at(
            cx,
            cy,
            approved=True,
            expected_pid=pid,
            expected_title=title,
        )

        if verify_change:
            time.sleep(settle_s)

        post_focus = focused_window().data
        after_hash: str | None = None
        visual_changed: bool | None = None
        if verify_change:
            after_path = Path(tempfile.gettempdir()) / f"warpblack-visual-after-{uuid4().hex}.png"
            after = visual_snapshot(after_path)
            after_hash = str(after.data["sha256"])
            visual_changed = after_hash != current_sha
            if not visual_changed:
                raise DesktopError("visual click completed but verification found no screen change")

        return DesktopResult(
            True,
            "click-visual-box",
            {
                "box": target.to_dict(),
                "snapshot_sha256": current_sha,
                "click": click_result.data,
                "post_focus": post_focus,
                "focus_changed": post_focus.get("pid") != pid or post_focus.get("title") != title,
                "verification": {
                    "enabled": verify_change,
                    "visual_changed": visual_changed,
                    "after_sha256": after_hash,
                },
            },
        )
    finally:
        try:
            before_path.unlink(missing_ok=True)
        except OSError:
            pass
        if after_path is not None:
            try:
                after_path.unlink(missing_ok=True)
            except OSError:
                pass
