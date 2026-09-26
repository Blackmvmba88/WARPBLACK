from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import textwrap


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
    proof_renders: dict[str, dict[str, str]]

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
            "proof_renders": self.proof_renders,
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


def _proof_paths(evidence_dir: Path | None) -> dict[str, Path]:
    if evidence_dir is None:
        return {}
    evidence_dir.mkdir(parents=True, exist_ok=True)
    return {
        "before": evidence_dir / "before.png",
        "after": evidence_dir / "after.png",
        "restored": evidence_dir / "restored.png",
    }


def _script(
    object_name: str,
    delta: tuple[float, float, float],
    proof_paths: dict[str, Path],
) -> str:
    name_json = json.dumps(object_name)
    delta_json = json.dumps(list(delta))
    paths_json = json.dumps({key: str(value) for key, value in proof_paths.items()})
    return textwrap.dedent(
        f"""
        import bpy
        import json
        import math
        from mathutils import Vector

        name = {name_json}
        delta = {delta_json}
        proof_paths = {paths_json}
        obj = bpy.data.objects.get(name)
        if obj is None:
            raise RuntimeError(f"object not found: {{name}}")

        def proof_render(path):
            if not path:
                return
            scene = bpy.context.scene
            for candidate in scene.objects:
                if hasattr(candidate, "hide_render"):
                    candidate.hide_render = candidate != obj

            corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
            center = sum(corners, Vector()) / 8.0
            radius = max((corner - center).length for corner in corners)
            radius = max(radius, 0.25)

            camera_data = bpy.data.cameras.new("WARPBLACK_PROOF_CAMERA")
            camera = bpy.data.objects.new("WARPBLACK_PROOF_CAMERA", camera_data)
            scene.collection.objects.link(camera)
            scene.camera = camera

            direction = Vector((1.6, -2.2, 1.4))
            direction.normalize()
            camera.location = center + direction * radius * 3.2
            camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
            camera.data.lens = 52

            light_data = bpy.data.lights.new("WARPBLACK_KEY", type="AREA")
            light_data.energy = 1200
            light_data.shape = "DISK"
            light_data.size = max(radius * 2.0, 1.0)
            light = bpy.data.objects.new("WARPBLACK_KEY", light_data)
            scene.collection.objects.link(light)
            light.location = center + Vector((radius * 2.0, -radius * 1.5, radius * 2.5))

            fill_data = bpy.data.lights.new("WARPBLACK_FILL", type="AREA")
            fill_data.energy = 500
            fill_data.size = max(radius * 2.5, 1.0)
            fill = bpy.data.objects.new("WARPBLACK_FILL", fill_data)
            scene.collection.objects.link(fill)
            fill.location = center + Vector((-radius * 2.0, radius * 1.0, radius * 1.0))

            scene.render.resolution_x = 512
            scene.render.resolution_y = 512
            scene.render.resolution_percentage = 100
            scene.render.image_settings.file_format = "PNG"
            scene.render.image_settings.color_mode = "RGBA"
            scene.render.film_transparent = True
            scene.render.filepath = path
            try:
                scene.render.engine = "BLENDER_EEVEE_NEXT"
            except Exception:
                pass
            bpy.ops.render.render(write_still=True)

        before = tuple(float(v) for v in obj.location)
        proof_render(proof_paths.get("before"))

        obj.location = tuple(before[i] + float(delta[i]) for i in range(3))
        after = tuple(float(v) for v in obj.location)
        proof_render(proof_paths.get("after"))

        obj.location = before
        restored = tuple(float(v) for v in obj.location)
        proof_render(proof_paths.get("restored"))

        verified = all(abs(restored[i] - before[i]) <= 1e-9 for i in range(3))
        payload = {{
            "before": before,
            "after": after,
            "restored": restored,
            "restore_verified": verified,
        }}
        print("{RESULT_PREFIX}" + json.dumps(payload, sort_keys=True))
        if not verified:
            raise RuntimeError("restore verification failed")
        """
    )


def translate_restore(
    blend_file: Path,
    *,
    object_name: str,
    delta: object,
    approved: bool,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    evidence_dir: Path | None = None,
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
    proof_paths = _proof_paths(evidence_dir)
    source_sha256_before = _sha256(blend_file)
    blender = _trusted_blender_binary()
    command = [
        blender,
        "--background",
        str(blend_file),
        "--python-expr",
        _script(object_name.strip(), safe_delta, proof_paths),
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

    proof_renders: dict[str, dict[str, str]] = {}
    for phase, path in proof_paths.items():
        if not path.is_file():
            raise BlenderError(f"missing {phase} proof render")
        proof_renders[phase] = {
            "path": str(path),
            "sha256": _sha256(path),
        }

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
        proof_renders=proof_renders,
    )
