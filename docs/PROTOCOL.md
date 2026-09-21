# WARPBLACK Protocol v1

This document defines the machine-to-machine contract used by the local HTTP bridge and the private GitHub control plane.

## Execution request

Canonical fields:

```json
{
  "argv": ["git", "status"],
  "cwd": ".",
  "timeout_s": 60,
  "approved": false,
  "request_id": "optional-correlation-id"
}
```

Rules:

- `argv` is a non-empty array of strings.
- `cwd` is resolved against the configured workspace when relative.
- `timeout_s` must pass policy bounds.
- `approved` is accepted by the local authenticated bridge, but remote GitHub jobs do **not** trust approval from JSON.
- `request_id` is optional on local HTTP. WARPBLACK generates one if omitted.

## Execution result

```json
{
  "ok": true,
  "request_id": "...",
  "argv": ["git", "status"],
  "cwd": "/workspace/repo",
  "exit_code": 0,
  "stdout": "...",
  "stderr": "",
  "duration_ms": 18,
  "timed_out": false,
  "policy_reason": "read-only git status",
  "policy_risk": "low"
}
```

`ok=true` means exit code zero and no timeout. It is not a semantic guarantee that the requested engineering goal is correct; callers must still perform READ BACK → COMPARE → CERTIFY.

## README absorption contract

Absorption is non-executing project-memory capture.

Canonical payload:

```json
{
  "message": "dame el README",
  "project_name": "MEngine",
  "confirmed": ["Live microphone input"],
  "derived": ["Audio buffering is required"],
  "proposed": ["Consider AudioWorklet"]
}
```

Rules:

- `confirmed`, `derived`, and `proposed` stay separate.
- Absorption persists state to `.warpblack/readme_state.json`.
- The phrase `dame el README` materializes `README.generated.md`.
- Absorption never executes shell commands or mutates application code.

## Explicit construction contract

Construction applies a planner-produced unified diff through the existing WARPBLACK policy boundary.

Canonical payload:

```json
{
  "message": "constrúyelo",
  "objective": "Add a health endpoint",
  "patch": "diff --git ...",
  "checks": [["pytest", "-q"]],
  "timeout_s": 120,
  "task_id": "optional-task-id"
}
```

Rules:

- The explicit `constrúyelo` trigger is mandatory.
- Patches targeting `.git/`, `.warpblack/`, absolute paths, or parent-directory escapes are rejected.
- WARPBLACK runs `git apply --check` before applying the patch.
- Validation checks execute sequentially and stop on the first failure.
- Failed validation returns `needs-review` and leaves the working tree available for inspection.
- Read-back evidence contains workspace status and diff statistics.
- Construction does not imply push, merge, release, or publish.

For local authenticated HTTP, the explicit construct request is treated as the local action authorization. For remote GitHub transport, construction additionally requires the separate `warpblack-approved` label.

## Local HTTP transport

Endpoints:

- `GET /v1/health` — unauthenticated liveness only
- `GET /v1/capabilities` — authenticated
- `POST /v1/execute` — authenticated execution
- `POST /v1/readme/absorb` — authenticated non-executing project-memory capture
- `POST /v1/construct` — authenticated explicit patch construction

Authenticated endpoints require:

```text
Authorization: Bearer <WARPBLACK_TOKEN>
```

The built-in server binds only to loopback addresses.

## Private GitHub transport

A remote job is a GitHub issue in a private control repository.

Required conditions:

1. repository metadata reports `private=true`
2. issue author matches the configured allowlisted actor
3. issue carries `warpblack-job`
4. issue body contains only JSON using one supported protocol envelope

Supported envelopes:

### Command

```json
{
  "protocol": "warpblack-job-v1",
  "argv": ["git", "status"],
  "cwd": ".",
  "timeout_s": 60
}
```

### Absorb

```json
{
  "protocol": "warpblack-absorb-v1",
  "message": "dame el README",
  "project_name": "MEngine",
  "confirmed": ["Live microphone input"],
  "derived": ["Audio buffering is required"],
  "proposed": ["Consider AudioWorklet"]
}
```

Absorb jobs are non-executing and do not require elevated approval.

### Construct

```json
{
  "protocol": "warpblack-construct-v1",
  "message": "constrúyelo",
  "objective": "Add a health endpoint",
  "patch": "diff --git ...",
  "checks": [["pytest", "-q"]],
  "timeout_s": 120
}
```

Construct jobs require elevated remote approval.

### Remote approval

The remote JSON body cannot grant approval. Elevated command execution and all construct jobs are authorized only when the issue also carries:

```text
warpblack-approved
```

WARPBLACK derives remote approval from that label locally. A JSON field such as `"approved": true` is ignored.

### Remote result

WARPBLACK posts a comment beginning with `WARPBLACK_RESULT_V1`, followed by a fenced JSON result object, and then closes the issue.

Long stdout/stderr streams are truncated in the remote comment and accompanied by SHA-256 hashes. The local audit ledger retains correlation hashes.

## Correlation and audit

Every execution has a `request_id`.

For GitHub jobs WARPBLACK uses a deterministic correlation form based on repository and issue number:

```text
github:OWNER/REPO#ISSUE_NUMBER
```

Construct tasks also persist a local task manifest and content hashes under:

```text
.warpblack/tasks/<task-id>/
```

The local audit ledger is append-only JSONL. It stores correlation metadata, policy outcome, timing and SHA-256 hashes of argv/cwd/stdout/stderr. It intentionally does not store raw command arguments or raw streams.

This lets a remote issue, local audit record, and returned execution result refer to the same action without copying potentially sensitive raw content into the ledger.

## Compatibility

Protocol v1 should evolve additively. Existing `warpblack-job-v1` command jobs remain valid. New behavior is introduced through separate additive envelopes such as `warpblack-absorb-v1` and `warpblack-construct-v1`. Removing or changing the meaning of an existing field requires a new protocol version.
