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
- mutating/high-impact actions require explicit approval
- every execution produces a structured audit result

Hard-denied command families currently include privileged/system-destructive tools such as `sudo`, `dd`, `mkfs`, `fdisk`, shutdown and reboot commands.

## Install

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Use

Read-only command:

```bash
warpblack exec --workspace . --cwd . -- git status
```

Code execution or a potentially mutating command requires explicit approval:

```bash
warpblack exec --workspace . --cwd . --approve -- pytest -q
```

The result is emitted as JSON so another process can consume it deterministically:

```json
{
  "ok": true,
  "argv": ["git", "status"],
  "cwd": "/workspace/project",
  "exit_code": 0,
  "stdout": "...",
  "stderr": "",
  "duration_ms": 12,
  "timed_out": false,
  "policy_reason": "read-only git status"
}
```

## MVP

The first milestone provides:

1. structured command schema
2. terminal policy gate
3. subprocess executor
4. JSON result envelope
5. CLI entrypoint
6. tests for allowed/denied commands and workspace confinement
7. CI with Ruff + Pytest

## Next

The next layer is the **local authenticated bridge** that lets XarvisCore or another AI planner submit a structured command request and receive execution evidence without scraping a terminal window.

After that come repository-aware planning, diffs, test runners, process observation, long-running jobs, and certification manifests.

## Status

Initial architecture established September 2026.
