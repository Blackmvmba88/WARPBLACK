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
- low-risk file arguments and option-embedded paths are checked for workspace escape
- timeouts are mandatory
- environment inheritance is minimized
- dangerous command families are hard-denied by policy
- mutating/high-impact actions require explicit approval
- Git read-only classification is narrow; mutating `git remote`, external diff/textconv, and output flags require approval
- local HTTP binds only to loopback addresses
- remote GitHub control refuses public repositories
- remote elevated approval is derived from a separate GitHub label, never trusted from job JSON
- every execution receives a correlation `request_id`
- an append-only local audit ledger records metadata and SHA-256 evidence hashes without raw argv/stdout/stderr

Hard-denied command families currently include privileged/system-destructive tools such as `sudo`, `dd`, `mkfs`, `fdisk`, shutdown and reboot commands.

For the security boundary and protocol contract, see `docs/THREAT_MODEL.md` and `docs/PROTOCOL.md`.

## Install

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Local execution

Read-only command:

```bash
warpblack exec --workspace . --cwd . -- git status
```

Code execution or a potentially mutating command requires explicit approval:

```bash
warpblack exec --workspace . --cwd . --approve -- pytest -q
```

By default, execution metadata is appended to:

```text
~/.warpblack/audit.jsonl
```

The ledger stores correlation and SHA-256 hashes rather than raw command arguments or output streams.

## Local authenticated bridge

Generate a strong local token and start the bridge:

```bash
export WARPBLACK_TOKEN="replace-with-a-long-random-token"
warpblack serve --workspace /path/to/workspace
```

Check it:

```bash
warpblack health
warpblack capabilities
warpblack call -- git status
```

The HTTP bridge binds only to loopback (`127.0.0.1`, `localhost`, or `::1`). It is intended for local programs such as XarvisCore, not direct exposure to the internet.

## Remote control plane via private GitHub repo

The remote mode solves the cloud-to-local boundary without exposing an inbound port. WARPBLACK polls a **private** GitHub repository over outbound HTTPS, accepts only jobs created by an allowlisted GitHub actor, executes them through the same policy engine, comments the structured result, and closes the issue.

Environment:

```bash
export WARPBLACK_GITHUB_TOKEN="your-fine-grained-token"
```

Process one job:

```bash
warpblack github-once \
  --repo OWNER/PRIVATE_CONTROL_REPO \
  --actor YOUR_GITHUB_LOGIN \
  --workspace /path/to/workspace
```

Or run continuously:

```bash
warpblack github-watch \
  --repo OWNER/PRIVATE_CONTROL_REPO \
  --actor YOUR_GITHUB_LOGIN \
  --workspace /path/to/workspace \
  --poll 5
```

A job is an issue carrying the `warpblack-job` label whose body contains only JSON:

```json
{
  "protocol": "warpblack-job-v1",
  "argv": ["git", "status"],
  "cwd": ".",
  "timeout_s": 60
}
```

The JSON cannot self-approve elevated execution. A mutating/code-execution job becomes approved only when the separate `warpblack-approved` label is present.

Remote stdout/stderr are bounded before being posted back. Truncated streams carry SHA-256 hashes so the returned evidence remains correlatable.

**Do not use the public WARPBLACK repository itself as the remote control queue.** Terminal commands and their results belong in a dedicated private control repository.

## v0.2 milestone

WARPBLACK now includes:

1. structured command schema and correlation IDs
2. terminal policy gate
3. subprocess executor with `shell=False`
4. JSON evidence envelope with policy risk
5. CLI entrypoint
6. workspace and path-escape defenses
7. narrowed Git read-only policy
8. local authenticated HTTP bridge
9. structured bridge client
10. private GitHub pull-based control plane
11. actor allowlisting and separate approval labeling
12. bounded remote result streams
13. append-only audit ledger with hashed evidence
14. policy, executor, bridge, audit, and control-plane tests
15. threat model and protocol documentation
16. GitHub Actions workflow for Ruff + Pytest

## Next

The next high-value layers are:

- repository-aware READ/PLAN helpers
- deterministic test/diff/certification manifests
- process observation and long-running job handles
- replay/idempotency protection for remote jobs
- provider-independent queue abstraction (GitHub today, Supabase/other transports later)
- XarvisCore adapter that speaks the WARPBLACK protocol directly

## Status

v0.2 architecture established September 2026. Integration remains unmerged until CI produces a trustworthy green verification run.
