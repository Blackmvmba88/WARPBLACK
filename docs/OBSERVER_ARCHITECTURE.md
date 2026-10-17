# BlackMamba Agent Separation

## Goal

Separate the BlackMamba automation stack into small, auditable processes with one responsibility each.

The core rule is:

> Idea != instruction != approval != execution != verification.

## Architecture

```text
IYARI
  |
  v
PLANNER / CHATGPT
  |
  v
OBSERVER
  |
  v
TASK SPEC
  |
  v
CODER
  |
  v
WARPBLACK
  |
  v
VERIFIER
  |
  v
LEDGER
  |
  +----> OBSERVER
```

## 1. Planner

Purpose:
- Interpret human intent.
- Design the solution.
- Define success criteria.
- Propose constraints and verification.

Must not:
- Execute local commands.
- Modify repositories directly as part of planning.
- Mark work complete without evidence.

Output:
- Human-readable plan.
- Structured task proposal.

## 2. Observer

Purpose:
- Read conversation and project state.
- Detect decisions, pending work, approvals, blockers, and changes.
- Convert context into a clean task specification.
- Maintain state transitions.

Observer is read-only by default.

It must not:
- Modify product code.
- Run arbitrary local commands.
- Treat an idea as approval.
- Infer completion from conversation alone.

Suggested states:

```text
PROPOSED
APPROVED
RUNNING
BLOCKED
NEEDS_REVIEW
VERIFIED
DONE
```

Example task:

```yaml
task_id: BM-OBS-001
source: chat
status: APPROVED

goal:
  separate_observer_from_warpblack

inputs:
  - conversation_state
  - repository_state

outputs:
  - task_spec.yaml
  - decision_log.json

permissions:
  observer: read_only
  coder: workspace_write
  warpblack: controlled_execution
  verifier: read_only
```

## 3. Coder

Purpose:
- Receive an approved task specification.
- Change code only within the declared scope.
- Produce a diff and implementation notes.

Must not:
- Interpret a long conversation as its task source.
- Choose project priorities.
- Expand scope silently.
- Execute destructive operations unless explicitly authorized.

## 4. WARPBLACK

WARPBLACK becomes the execution layer.

Purpose:
- Execute approved commands.
- Run tests, builds, inspections, and controlled machine actions.
- Capture stdout, stderr, exit codes, artifacts, and workspace state.

WARPBLACK should not answer:

> What did Iyari mean?

It should answer:

> What command was requested, what happened, and what evidence was produced?

Example contract:

```yaml
cwd: /Users/blackmamba/Documents/GitHub/example

command:
  - pytest
  - -q

expected:
  exit_code: 0

capture:
  - stdout
  - stderr
  - workspace_diff
  - artifacts
```

## 5. Verifier

Purpose:
- Compare expected vs actual results.
- Check tests, diffs, hashes, artifacts, and side effects.
- Reject false completion.

Possible checks:
- Git diff before/after.
- Workspace hashes when required.
- Test results.
- Artifact existence.
- Schema validation.
- Exit codes.
- Reproducibility / idempotency checks.

Output:

```yaml
task_id: BM-OBS-001
result: VERIFIED
evidence:
  tests: passed
  expected_files: present
  unexpected_workspace_changes: false
```

## 6. Ledger

Purpose:
- Persist what actually happened.
- Keep an auditable history independent of chat memory.

Suggested records:
- task_id
- source
- approval
- commands executed
- commit / branch
- evidence
- timestamps
- result
- blocker
- next action

The ledger should record facts, not reinterpret them.

## Observer contract

The Observer should transform conversational statements into explicit state changes.

Examples:

| Conversation | Observer interpretation |
| --- | --- |
| "se me ocurrió X" | PROPOSED |
| "hazlo" / "adelante" | APPROVED |
| command started | RUNNING |
| test failed | BLOCKED or NEEDS_REVIEW |
| tests and evidence pass | VERIFIED |
| result accepted / merged | DONE |

Ambiguous language must not silently escalate privileges.

## Permission model

Default policy:

```text
Planner   -> reasoning only
Observer  -> read-only
Coder     -> scoped workspace write
WARPBLACK -> controlled execution
Verifier  -> read-only verification
Ledger    -> append-only records
```

Sensitive execution should require an explicit approval policy.

## First implementation milestone

### BM-OBS-001

Create the Observer as an independent module/process.

Minimum viable scope:
1. Parse a structured event stream.
2. Generate `task_spec.yaml`.
3. Maintain task state.
4. Write `decision_log.json`.
5. Never execute commands.
6. Never modify product code.
7. Provide a machine-readable handoff to Coder/WARPBLACK.

Definition of done:
- Observer receives sample conversation events.
- Correctly distinguishes idea, instruction, approval, execution result, and verification.
- Produces deterministic task specs.
- Unit tests cover state transitions.
- No subprocess execution exists in the Observer package.

## Design principle

WARPBLACK does not think for the system.

The Observer does not execute for the system.

The Coder does not decide for the system.

Each component produces evidence for the next one.
