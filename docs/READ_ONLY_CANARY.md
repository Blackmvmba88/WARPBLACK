# BM-CORE-001: read-only modular canary

This is the first **execution-capable slice** of the modular runtime. It does not
integrate an Observer event stream or enable an unrestricted autonomous agent.

## Contract and boundaries

Flow:

```text
TaskEnvelopeV1 (PROPOSED, read_only, git.status)
  -> ProjectRegistry (registered project confined to workspace)
  -> request_id claim (exclusive persistent record)
  -> typed dispatch_action("git.status") -> policy -> TerminalExecutor -> audit
  -> typed dispatch_action("git.status") -> policy -> TerminalExecutor -> audit
  -> compare stdout digests + branch + dirty state + policy evidence
  -> immutable result record (DONE or NEEDS_REVIEW / BLOCKED)
```

The canary only accepts `git.status`. It never accepts arbitrary argv, desktop
commands, patches, or approvals from the envelope. Both reads go through the
existing WARPBLACK typed action and executor with `approved=False`.

It requires a project registered in WARPBLACK's ProjectRegistry and physically
located inside the `--workspace` root. Symlink resolution is checked against
that root. A missing, inactive, or out-of-scope registration is rejected.

## Run locally

Register the project if needed:

```bash
warpblack projects add /path/to/Projects/WARPBLACK
warpblack projects list
```

Use the unique project ID from `projects list` (or an unambiguous project name)
as `workspace_id`.

Create `canary-task.json`:

```json
{
  "schema_version": 1,
  "request_id": "manual-git-status-001",
  "task_id": "BM-CORE-001",
  "source": "user",
  "workspace_id": "WARPBLACK",
  "intent": "git.status",
  "state": "PROPOSED",
  "risk": "read_only",
  "approval_ref": null,
  "expected": ["two matching git status reads"]
}
```

Run using Python 3.11+ in the installed WARPBLACK environment:

```bash
python -m warpblack.runtime_canary \
  --task-file canary-task.json \
  --workspace /path/to/Projects
```

The default persistent records are stored outside the source tree at
`~/.warpblack/modular-canary/`. A successful result contains:
`state: "DONE"`, `verified: true`, a SHA-256 evidence fingerprint,
`branch`, and `worktree_dirty`. It intentionally does **not** write
the raw `git status` stdout to the result/claim records.

## Replay and crash handling

- `request_id` is claimed with exclusive file creation before execution.
- Reusing the same `request_id` and identical envelope returns the stored
  result with `replayed: true`; there is **no subprocess replay**.
- Reusing the same `request_id` for a different envelope is rejected.
- If a claim exists without a completed result, the outcome is unknown:
  WARPBLACK reports `NEEDS_REVIEW` and does not execute it again.
- If either execution is invalid, elevated, timed out, or if the two readbacks
  differ, the task is not certified.
- The immutable result record is separate from the existing append-only
  terminal audit ledger. A valid `DONE` is not a claim that all other
  workstation activity is safe or unchanged.

## Validation and rollout

```bash
pytest -q tests/test_runtime_canary.py
pytest -q
ruff check .
```

Gates before merge: run these tests with the **real repository dependencies**,
confirm the CI runner actually starts, and perform a local macOS read-only
acceptance. The existing draft PR should remain unmerged until then.

Next slice: add an Observer event adapter that emits this exact envelope, then
wire the ledger's stored result into the unified runtime without introducing
write permissions.
