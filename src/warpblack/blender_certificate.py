from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from .blender import BlenderTransactionResult, translate_restore
from .desktop import DesktopError, capture_screen, focused_window


SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


class BlenderCertificateError(RuntimeError):
    pass


@dataclass(frozen=True)
class BlenderCertificateResult:
    certificate_path: str
    certificate_sha256: str
    desktop_capture_path: str
    desktop_capture_sha256: str
    desktop_identity: dict[str, object]
    transaction: BlenderTransactionResult

    def to_dict(self) -> dict[str, object]:
        return {
            "certificate_path": self.certificate_path,
            "certificate_sha256": self.certificate_sha256,
            "desktop_capture_path": self.desktop_capture_path,
            "desktop_capture_sha256": self.desktop_capture_sha256,
            "desktop_identity": self.desktop_identity,
            "transaction": self.transaction.to_dict(),
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_evidence_id(request_id: str) -> str:
    cleaned = SAFE_ID.sub("-", request_id.strip()).strip(".-_")
    if not cleaned:
        raise BlenderCertificateError("request_id cannot produce an empty evidence id")
    return cleaned[:96]


def certify_translate_restore(
    blend_file: Path,
    *,
    workspace_root: Path,
    request_id: str,
    object_name: str,
    delta: object,
    approved: bool,
    timeout_s: float = 120.0,
) -> BlenderCertificateResult:
    if not approved:
        raise BlenderCertificateError("explicit approval is required")

    root = workspace_root.resolve()
    evidence_id = safe_evidence_id(request_id)
    evidence_dir = (root / ".warpblack" / "evidence" / evidence_id).resolve()
    try:
        evidence_dir.relative_to(root)
    except ValueError as exc:
        raise BlenderCertificateError("evidence directory escapes workspace") from exc
    evidence_dir.mkdir(parents=True, exist_ok=True)

    try:
        identity = focused_window().data
    except DesktopError as exc:
        raise BlenderCertificateError(str(exc)) from exc

    if str(identity.get("application", "")).lower() != "blender":
        raise BlenderCertificateError("focused application must be Blender")

    title = str(identity.get("title", ""))
    if blend_file.name not in title:
        raise BlenderCertificateError(
            f"focused Blender window does not match target file: {blend_file.name}"
        )

    desktop_path = evidence_dir / "desktop-identity.png"
    try:
        capture_screen(
            desktop_path,
            expected_pid=int(identity["pid"]),
            expected_title=str(identity["title"]),
        )
    except (DesktopError, KeyError, TypeError, ValueError) as exc:
        raise BlenderCertificateError(str(exc)) from exc

    transaction = translate_restore(
        blend_file,
        object_name=object_name,
        delta=delta,
        approved=True,
        timeout_s=timeout_s,
        evidence_dir=evidence_dir / "renders",
    )

    payload = {
        "schema": "warpblack.blender-certificate.v1",
        "request_id": request_id,
        "desktop_identity": identity,
        "desktop_capture": {
            "path": str(desktop_path),
            "sha256": _sha256(desktop_path),
        },
        "transaction": transaction.to_dict(),
        "verdict": {
            "restore_verified": transaction.restore_verified,
            "source_unchanged": (
                transaction.source_sha256_before == transaction.source_sha256_after
            ),
            "proof_phases": sorted(transaction.proof_renders),
        },
    }
    if payload["verdict"]["proof_phases"] != ["after", "before", "restored"]:
        raise BlenderCertificateError("incomplete proof render set")
    if not payload["verdict"]["restore_verified"]:
        raise BlenderCertificateError("restore verification failed")
    if not payload["verdict"]["source_unchanged"]:
        raise BlenderCertificateError("source .blend changed")

    certificate_path = evidence_dir / "certificate.json"
    certificate_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    certificate_sha256 = _sha256(certificate_path)
    checksum_path = evidence_dir / "certificate.sha256"
    checksum_path.write_text(
        f"{certificate_sha256}  {certificate_path.name}\n",
        encoding="utf-8",
    )

    return BlenderCertificateResult(
        certificate_path=str(certificate_path),
        certificate_sha256=certificate_sha256,
        desktop_capture_path=str(desktop_path),
        desktop_capture_sha256=payload["desktop_capture"]["sha256"],
        desktop_identity=identity,
        transaction=transaction,
    )
