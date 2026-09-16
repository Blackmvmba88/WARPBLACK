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

## Local HTTP transport

Endpoints:

- `GET /v1/health` — unauthenticated liveness only
- `GET /v1/capabilities` — authenticated
- `POST /v1/execute` — authenticated execution

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
4. issue body contains only JSON with `protocol = warpblack-job-v1`

Example body:

```json
{
  "protocol": "warpblack-job-v1",
  "argv": ["git", "status"],
  "cwd": ".",
  "timeout_s": 60
}
```

### Remote approval

The remote JSON body cannot grant approval. Elevated execution is authorized only when the issue also carries:

```text
warpblack-approved
```

WARPBLACK derives `approved=true` from that label locally.

### Remote result

WARPBLACK comments on the issue with:

```text
WARPBLACK_RESULT_V1
```json
{...execution result...}
```
```

and then closes the issue. Long stdout/stderr streams are truncated in the remote comment and accompanied by SHA-256 hashes. The local audit ledger retains correlation hashes.

## Correlation

Every execution has a `request_id`.

For GitHub jobs WARPBLACK uses a deterministic correlation form based on repository and issue number:

```text
github:OWNER/REPO#ISSUE_NUMBER
```

This lets a remote issue, local audit record, and returned execution result refer to the same action.

## Compatibility

Protocol v1 should evolve additively. Removing or changing the meaning of an existing field requires a new protocol version.
