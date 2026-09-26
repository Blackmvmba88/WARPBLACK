# BM-BLENDER-001 — Transactional Blender acceptance

## Objective

Prove that WARPBLACK can perform one bounded Blender operation against a real `.blend` file, capture evidence, and restore the original state without saving the scene.

## Safety contract

- Capability: `blender.object.translate_restore`
- Target must resolve inside the configured WARPBLACK workspace.
- Target must be an existing `.blend` file.
- `constraints.approved` must be exactly `true`.
- `constraints.object` must be a non-empty Blender object name.
- `constraints.delta` must contain exactly three finite numbers.
- Each delta component is limited to ±0.25 m.
- The adapter launches trusted Blender in background mode.
- WARPBLACK supplies fixed transaction code; callers cannot supply arbitrary Python.
- The adapter never saves the `.blend` file.
- Success requires exact restoration verification.

## Real-machine acceptance payload

Use the normal structured-intent entrypoint with a payload equivalent to:

```json
{
  "intent": "blender.object.translate_restore",
  "target": "COMBI_TOPOLOGIA_PRO.blend",
  "project": "COMBI",
  "request_id": "bm-blender-001-mirror-l-10mm",
  "constraints": {
    "object": "Mirror_L",
    "delta": [0.01, 0.0, 0.0],
    "approved": true,
    "timeout_s": 120
  }
}
```

If the scene lives in a subdirectory, replace `target` with its workspace-relative path.

## Pass criteria

The result is accepted only when all of the following are true:

1. `ok == true`
2. `capability == "blender.object.translate_restore"`
3. `changed == false`
4. evidence object is `Mirror_L`
5. `after.x - before.x` is approximately `0.01` m
6. Y and Z are unchanged
7. `restored == before` within the adapter tolerance
8. `restore_verified == true`
9. the source `.blend` modification timestamp/hash remains unchanged by the capability

## Expected evidence shape

```json
{
  "ok": true,
  "changed": false,
  "capability": "blender.object.translate_restore",
  "evidence": {
    "file": ".../COMBI_TOPOLOGIA_PRO.blend",
    "object": "Mirror_L",
    "delta": [0.01, 0.0, 0.0],
    "before": [0.0, 0.0, 0.0],
    "after": [0.01, 0.0, 0.0],
    "restored": [0.0, 0.0, 0.0],
    "restore_verified": true,
    "blender_binary": "/Applications/Blender.app/Contents/MacOS/Blender"
  }
}
```

The numeric coordinates above are illustrative. The acceptance decision uses the relationships between BEFORE, AFTER, and RESTORED, not those example coordinates.

## Failure behavior

The capability must fail closed when:

- approval is missing;
- the target escapes the workspace, including via symlink;
- the target is not a `.blend` file;
- the object does not exist;
- the delta is malformed, non-finite, zero, or outside the safety bound;
- Blender cannot be found;
- Blender exits non-zero;
- evidence is missing or malformed;
- restoration cannot be verified.

## Next gate

After this acceptance passes on Blender 5.2.0 LTS, the next slice is BM-BLENDER-002: capture BEFORE/AFTER/RESTORED screenshots tied to the transaction evidence and object/window identity.
