from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess


RESULT_PREFIX = "WARPBLACK_BLENDER_RESULT="
MAX_DELTA_M = 0.25
DEFAULT_TIMEOUT_S = 120.0


class BlenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class BlenderTransactionResult:
    file: str
    object_name: str
    delta: tuple[float, float, float]
    before: tuple[float, float, float]
    after: tuple[float, float, float]
    restored: tuple[float, float, float]
    restore_verified: bool
    blender_binary: str
    source_sha256_before: str
    source_sha256_after: str

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "object": self.object_name,
            "delta": list(self.delta),
            "before": list(self.before),
            "after": list(self.after),
            "restored": list(self.restored),
            "restore_verified": self.restore_verified,
            "blender_binary": self.blender_binary,
            "source_sha256_before": self.source_sha256_before,
            "source_sha256_after": self.source_sha256_after,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _trusted_blender_binary() -> str:
    candidates = [
        shutil.which("blender"),
        "/Applications/Blender.app/Contents/MacOS/Blender",
    ]
    for raw in candidates:
        if not raw:
            continue
        candidate = Path(raw)
        if candidate.is_file():
            return str(candidate)
    raise BlenderError("trusted Blender executable not found")


def _delta(raw: object) -> tuple[float, float, float]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        raise BlenderError("delta must be a 3-item array")
    values: list[float] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise BlenderError("delta values must be numbers")
        value = float(item)
        if not math.isfinite(value):
            raise BlenderError("delta values must be finite")
        if abs(value) > MAX_DELTA_M:
            raise BlenderError(f"delta component exceeds {MAX_DELTA_M} m safety limit")
        values.append(value)
    if values == [0.0, 0.0, 0.0]:
        raise BlenderError("delta must move the object")
    return tuple(values)  # type: ignore[return-value]


def _script(object_name: str, delta: tuple[float, float, float]) -> str:
    name_json = json.dumps(object_name)
    delta_json = json.dumps(list(delta))
    return (
        "import bpy, json\n"
        f"name = {name_json}\n"
        f"delta = {delta_json}\n"
        "obj = bpy.data.objects.get(name)\n"
        "if obj is None:\n"
        "    raise RuntimeError(f'object not found: {name}')\n"
        "before = tuple(float(v) for v in obj.location)\n"
        "obj.location = tuple(before[i] + float(delta[i]) for i in range(3))\n"
        "after = tuple(float(v) for v in obj.location)\n"
        "obj.location = before\n"
        "restored = tuple(float(v) for v in obj.location)\n"
        "verified = all(abs(restored[i] - before[i]) <= 1e-9 for i in range(3))\n"
        "payload = {'before': before, 'after': after, 'restored': restored, 'restore_verified': verified}\n"
        f"print('{RESULT_PREFIX}' + json.dumps(payload, sort_keys=True))\n"
        "if not verified:\n"
        "    raise RuntimeError('restore verification failed')\n"
    )


def translate_restore(
    blend_file: Path,
    *,
    object_name: str,
    delta: object,
    approved: bool,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> BlenderTransactionResult:
    if not approved:
        raise BlenderError("explicit approval is required")
    if not isinstance(object_name, str) or not object_name.strip():
        raise BlenderError("object must be a non-empty string")
    if "\x00" in object_name or len(object_name) > 256:
        raise BlenderError("invalid object name")
    if blend_file.suffix.lower() != ".blend" or not blend_file.is_file():
        raise BlenderError("target must be an existing .blend file")
    if timeout_s <= 0 or timeout_s > 300:
        raise BlenderError("timeout must be between 0 and 300 seconds")

    safe_delta = _delta(delta)
    source_sha256_before = _sha256(blend_file)
    blender = _trusted_blender_binary()
    command = [
        blender,
        "--background",
        str(blend_file),
        "--python-expr",
        _script(object_name.strip(), safe_delta),
    ]
    completed = subprocess.run(
        command,
        cwd=blend_file.parent,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_s,
        check=False,
    )
    source_sha256_after = _sha256(blend_file)
    if source_sha256_after != source_sha256_before:
        raise BlenderError("source .blend changed during transaction")
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise BlenderError(f"Blender transaction failed: {detail[-1000:]}")

    payload: dict[str, object] | None = None
    for line in completed.stdout.splitlines():
        if line.startswith(RESULT_PREFIX):
            raw = line[len(RESULT_PREFIX):]
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                payload = parsed

    if payload is None:
        raise BlenderError("Blender did not emit transaction evidence")

    def vec(name: str) -> tuple[float, float, float]:
        raw = payload.get(name)
        if not isinstance(raw, list) or len(raw) != 3:
            raise BlenderError(f"invalid {name} evidence")
        return tuple(float(v) for v in raw)  # type: ignore[return-value]

    verified = payload.get("restore_verified")
    if verified is not True:
        raise BlenderError("restore verification failed")

    return BlenderTransactionResult(
        file=str(blend_file),
        object_name=object_name.strip(),
        delta=safe_delta,
        before=vec("before"),
        after=vec("after"),
        restored=vec("restored"),
        restore_verified=True,
        blender_binary=blender,
        source_sha256_before=source_sha256_before,
        source_sha256_after=source_sha256_after,
    )
