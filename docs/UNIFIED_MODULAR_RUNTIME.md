# BlackMamba Unified Modular Runtime — BM-CORE-001

## Decision
One installable product and one operator interface, **not** one monolithic process.
The canonical codebase is WARPBLACK. Existing `control` remains an external private queue/transport; `vision` remains an optional perception adapter until compatibility is tested. No forced repository deletion or unreviewed code migration.

## Dependency rules
- `core/contracts`: pure versioned schemas; depends on no adapters.
- `observer`: read-only events and state; never imports executor.
- `planner`: produces proposed task specs, never approvals.
- `coder`: produces scoped patch proposals; cannot run shell.
- `policy`: validates identity, approval, workspace scope, and risk.
- `executor` (WARPBLACK): sole owner of terminal/desktop actuation.
- `verifier`: read-back of results, tests, hashes and workspace diff.
- `ledger`: append-only audit with correlation IDs.
- `adapters`: GitHub control, macOS desktop, voice, Vision, Blender; optional feature flags.
- `runtime`: composition root and lifecycle. No module may bypass policy to call executor.

```text
User / Voice / UI / GitHub
            |
       Runtime gateway
            |
         Observer ----> Ledger
            |
         Planner
            |
       Task proposal
            |
       Approval / Policy
            |
           Coder ----> proposed patch
            |
         Executor ----> artifacts
            |
         Verifier ----> Ledger / UI
```

## Task envelope v1
Every boundary must validate a versioned object. Example:
```json
{
  "schema_version": 1,
  "request_id": "unique-id",
  "task_id": "BM-CORE-001",
  "source": "user",
  "workspace_id": "registered-project",
  "intent": "inspect",
  "state": "PROPOSED",
  "risk": "read_only",
  "approval_ref": null,
  "expected": ["git status evidence"]
}
```
No natural-language statement is authorization by itself for high-impact actions. Approvals are bound to a task ID, exact proposed operation, scope, and expiration. Retrying the same request_id must not re-run a mutation.

## State machine
`PROPOSED -> APPROVED -> RUNNING -> NEEDS_REVIEW|BLOCKED|VERIFIED -> DONE`.
`VERIFIED` requires evidence, not just exit code 0. Invalid transitions fail closed. Crash recovery must reconcile the ledger before resuming, never replay an unknown mutation automatically.

## Runtime requirements
- One CLI entrypoint: `warpblack`; one dashboard can be added without creating another orchestration service.
- Explicit plugin registry and capability negotiation; optional dependencies load lazily.
- Process boundary for risky adapters; bounded timeouts and cancellation.
- Default local-only bridge, least privileges, secrets excluded from logs.
- Desktop observation must respect macOS Accessibility/Screen Recording permissions.
- Resource budgeting for Mac mini M1 / 8 GB: no perpetual high-frequency screenshot/video/model loops by default.
- Four-window autonomous mode is a later optional feature, never an authorization bypass.
- Project folders remain where they are; use the existing project registry.

## Migration order (small reversible slices)
1. Baseline: preserve existing unit tests, CLI behavior, threat model and commands; inventory public interfaces.
2. Add pure `TaskEnvelopeV1` schema/validator and contract tests without changing existing queue semantics.
3. Adapt Observer and GitHub control ingress to emit the envelope; retain legacy protocol compatibility.
4. Centralize policy/approval gate and idempotency ledger; reject duplicate requests.
5. Wire one read-only end-to-end canary: Observer -> task -> policy -> `git status` -> verifier -> ledger.
6. Wire approved patch execution with preflight, snapshot, read-back and human review.
7. Enable optional voice, vision and desktop adapters one by one behind flags, with permission/timeout tests.
8. Expose unified local dashboard; benchmark memory, CPU and crash recovery.

## Acceptance gates
- Existing WARPBLACK tests remain green; no regression in CLI/queue behavior.
- Schema rejects unknown versions, malformed paths and invalid state transitions.
- Observer cannot invoke subprocess, filesystem mutations or UI actions.
- Executor refuses unapproved mutation or out-of-scope workspace.
- Replayed request IDs do not duplicate side effects.
- Timeouts, failed checks, closed terminals, missing permissions and restart recovery are tested.
- Read-back includes actual artifacts, status and hashes; report differentiates attempted/verified/done.
- Each migration slice has tests, rollback path and reviewable PR. No direct merge into main.

## Immediate next engineering change
Implement only Step 2 (typed, pure task contract + tests), then the read-only canary. Keep this document as the integration design decision; it is not a claim that the modules have been implemented.
