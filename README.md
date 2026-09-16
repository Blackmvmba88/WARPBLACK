# WARPBLACK

**BlackMamba terminal bridge for AI-assisted software engineering.**

WARPBLACK is the controlled execution layer between an AI planner and a local terminal. Its job is not to give an AI unrestricted shell access; its job is to turn a structured request into an observable, bounded, auditable execution and return evidence.

```text
AI / XarvisCore
      ↓
structured command request
      ↓
WARPBLACK policy gate
      ↓
TerminalExecutor
      ↓
local process
      ↓
stdout + stderr + exit code + duration
      ↓
Verifier / read-back
      ↓
AI
```

## Core contract

Every action follows the BlackMamba execution loop:

```text
READ → PLAN → EXECUTE → READ BACK → COMPARE → CERTIFY
```

The terminal is an **actuator**, never the source of truth. Results must be read back and verified.

## Safety model

WARPBLACK starts fail-closed:

- commands are executed as argument arrays, never with `shell=True`
- execution is restricted to an allowed workspace root
- timeouts are mandatory
- environment inheritance is minimized
- dangerous command families are denied by policy
- mutating/high-impact actions can require explicit approval
- every execution produces a structured audit result

## MVP

The first milestone provides:

1. structured command schema
2. terminal policy gate
3. subprocess executor
4. JSON result envelope
5. CLI entrypoint
6. tests for allowed/denied commands and workspace confinement

Later milestones will add repository-aware planning, diffs, test runners, process observation, long-running jobs, and a local authenticated bridge for XarvisCore.

## Status

Initial architecture established September 2026.
