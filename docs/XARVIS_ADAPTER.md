# XarvisCore ↔ WARPBLACK adapter

This layer lets XarvisCore request terminal work without bypassing the WARPBLACK policy, executor, audit, or verification boundaries.

```text
XarvisCore planner
      ↓
xarvis-warpblack-v1 envelope
      ↓
XarvisAdapter
      ↓
WarpClient
      ↓
WARPBLACK authenticated local bridge
      ↓
policy → executor → audit → result
```

## Protocol

Every request carries:

```json
{
  "protocol": "xarvis-warpblack-v1",
  "action": "terminal.execute"
}
```

Supported actions are:

- `terminal.health`
- `terminal.capabilities`
- `terminal.execute`

Execution example:

```json
{
  "protocol": "xarvis-warpblack-v1",
  "action": "terminal.execute",
  "argv": ["git", "status"],
  "cwd": ".",
  "timeout_s": 30,
  "request_id": "xarvis-plan-42"
}
```

The adapter returns a stable envelope around the ordinary WARPBLACK result:

```json
{
  "protocol": "xarvis-warpblack-v1",
  "action": "terminal.execute",
  "ok": true,
  "request_id": "xarvis-plan-42",
  "result": {}
}
```

## Approval boundary

`approved` is intentionally forbidden inside the Xarvis payload.

A model, planner, prompt, or generated job must never be able to authorize its own elevated execution. The trusted caller supplies approval out-of-band only after an independent operator or policy gate has granted it:

```python
adapter.handle(payload, approved=True)
```

That boolean is then passed into the existing WARPBLACK policy engine. Hard-denied command families remain denied even when approval is present.

## Verification boundary

A successful process exit is evidence, not certification. XarvisCore must still follow:

```text
READ → PLAN → EXECUTE → READ BACK → COMPARE → CERTIFY
```

The adapter does not convert `ok=true` into a semantic claim that the engineering goal is correct.

## Integration direction

The first XarvisCore integration should be a small actuator module that:

1. builds `xarvis-warpblack-v1` envelopes from an already-approved plan,
2. sends them through this adapter/client boundary,
3. stores the returned `request_id`,
4. performs repository-aware read-back and comparison,
5. emits a certification result only after those checks pass.

Direct `subprocess` calls in existing XarvisCore modules should be migrated incrementally, not replaced all at once.
