# BM-BLENDER-002 — Visual + cryptographic evidence certificate

## Objective

Extend BM-BLENDER-001 so a bounded Blender transaction produces inspectable evidence instead of only numeric output.

BM-BLENDER-002 certifies four independent things:

1. the focused desktop application is Blender and its PID/title are captured;
2. the requested object is rendered in BEFORE, AFTER, and RESTORED states;
3. the object's transform returns to the exact original location within tolerance;
4. the source `.blend` SHA-256 is identical before and after execution.

The source scene is never saved by this capability.

## Acceptance command

Bring the intended Blender scene to the front, then run:

```bash
warpblack blender certify-translate-restore COMBI_TOPOLOGIA_PRO.blend \
  --workspace . \
  --object Mirror_L \
  --dx 0.01 \
  --approve \
  --request-id bm-blender-002-mirror-l-10mm \
  --project COMBI
```

## Structured capability

`blender.object.translate_restore_certify`

Equivalent intent:

```json
{
  "intent": "blender.object.translate_restore_certify",
  "target": "COMBI_TOPOLOGIA_PRO.blend",
  "project": "COMBI",
  "request_id": "bm-blender-002-mirror-l-10mm",
  "constraints": {
    "object": "Mirror_L",
    "delta": [0.01, 0.0, 0.0],
    "approved": true,
    "timeout_s": 120
  }
}
```

## Evidence directory

The request id is sanitized and evidence is written only inside the configured workspace:

```text
.warpblack/
  evidence/
    bm-blender-002-mirror-l-10mm/
      desktop-identity.png
      certificate.json
      certificate.sha256
      renders/
        before.png
        after.png
        restored.png
```

## Why proof renders instead of desktop screenshots for each phase

The transaction uses Blender background mode so arbitrary Python is not exposed and the user's visible scene is not mutated. A normal desktop screenshot during AFTER would therefore be misleading because the visible foreground Blender process would not contain that temporary movement.

For that reason:

- `desktop-identity.png` proves which Blender window/PID was active;
- Blender itself generates isolated proof renders from the transaction process for BEFORE, AFTER, and RESTORED;
- each proof render is hashed;
- the numeric transform evidence is stored in the same certificate.

## Certificate verdict

A successful certificate requires:

- focused application is Blender;
- desktop capture succeeds while PID/title still match;
- BEFORE proof render exists;
- AFTER proof render exists;
- RESTORED proof render exists;
- `restore_verified == true`;
- `source_sha256_before == source_sha256_after`;
- all evidence remains under the workspace evidence directory.

## Example certificate shape

```json
{
  "schema": "warpblack.blender-certificate.v1",
  "request_id": "bm-blender-002-mirror-l-10mm",
  "desktop_identity": {
    "application": "Blender",
    "pid": 60293,
    "frontmost": true,
    "title": "COMBI_TOPOLOGIA_PRO.blend - Blender 5.2.0 LTS"
  },
  "desktop_capture": {
    "path": ".../desktop-identity.png",
    "sha256": "<sha256>"
  },
  "transaction": {
    "object": "Mirror_L",
    "delta": [0.01, 0.0, 0.0],
    "before": ["<x>", "<y>", "<z>"],
    "after": ["<x+0.01>", "<y>", "<z>"],
    "restored": ["<x>", "<y>", "<z>"],
    "restore_verified": true,
    "source_sha256_before": "<sha256>",
    "source_sha256_after": "<same-sha256>",
    "proof_renders": {
      "before": {"path": ".../before.png", "sha256": "<sha256>"},
      "after": {"path": ".../after.png", "sha256": "<sha256>"},
      "restored": {"path": ".../restored.png", "sha256": "<sha256>"}
    }
  },
  "verdict": {
    "restore_verified": true,
    "source_unchanged": true,
    "proof_phases": ["after", "before", "restored"]
  }
}
```

## Fail-closed behavior

Certification fails when Blender is not focused, PID/title changes before the desktop capture, the object does not exist, a proof render is missing, restoration fails, the source scene changes, the target escapes the workspace, approval is missing, or the delta exceeds the BM-BLENDER safety bounds.

## Next gate

BM-BLENDER-003 should turn this certificate format into a reusable application-operation protocol so the same pattern can cover Blender edits, Arduino compilation/upload verification, CAD operations, and other desktop tools.
