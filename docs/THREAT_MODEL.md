# WARPBLACK Threat Model

WARPBLACK is intentionally treated as a high-trust actuator. The design assumes that a terminal bridge can cause real damage if authentication, authorization, workspace confinement, or approval semantics fail.

## Assets

- local source repositories and working files
- developer credentials present on the machine
- Git history and uncommitted work
- terminal availability and host stability
- execution evidence and audit correlation

## Trust boundaries

```text
AI planner / operator
        │
        ├── local loopback HTTP ──► WARPBLACK
        │
        └── private GitHub repo ──► outbound poller ──► WARPBLACK
                                              │
                                              ▼
                                      policy / approval
                                              │
                                              ▼
                                       local subprocess
```

The subprocess boundary is the point of highest impact. Nothing arriving from HTTP or a remote queue bypasses `TerminalExecutor` policy.

## Security invariants

1. **No unrestricted shell string execution.** Commands are argument arrays and execute with `shell=False`.
2. **Workspace confinement.** The working directory must resolve beneath the configured workspace root.
3. **Path-aware low-risk policy.** Explicit and option-embedded path arguments that may escape the workspace are not granted low-risk execution.
4. **Hard-deny beats approval.** Privileged/system-destructive command families remain blocked even when approval is present.
5. **Remote jobs require a private repository.** The GitHub control-plane transport refuses public repositories.
6. **Remote identity is allowlisted.** A job from any other GitHub actor is ignored.
7. **Job JSON cannot self-approve.** Elevated approval is derived from the separate `warpblack-approved` label.
8. **Local HTTP is loopback-only.** The built-in server refuses non-loopback bind addresses.
9. **Bounded execution.** Every process has a timeout and remote stream output is bounded before posting back to GitHub.
10. **Audit without raw secrets.** The local ledger stores correlation metadata and SHA-256 hashes rather than raw stdout/stderr or full argv.

## Threats and mitigations

### Public issue injection

**Threat:** an attacker submits a terminal job to a public repository.

**Mitigation:** WARPBLACK verifies repository metadata and refuses to use a repository unless GitHub reports `private=true`.

### Unauthorized private-repo collaborator

**Threat:** another collaborator creates a malicious issue.

**Mitigation:** only the configured `allowed_actor` is accepted. Keep control-repo write access minimal.

### Self-approved malicious payload

**Threat:** issue body contains `"approved": true`.

**Mitigation:** that field is ignored. Approval comes only from the `warpblack-approved` label.

### Workspace escape

**Threat:** a nominally read-only command attempts to read outside the workspace using `/absolute/path`, `../../path`, or option-embedded paths.

**Mitigation:** low-risk path arguments are resolved and checked against the workspace root. Escapes require explicit elevated approval.

### Read-only command with hidden mutation/execution

**Threat:** a command classified as read-only has an option that mutates state or executes helpers.

**Mitigation:** risky command families/options are excluded or narrowed. Examples include `find`, Git external diff/textconv, Git output flags, and mutating `git remote` operations.

### Result exfiltration through remote comments

**Threat:** huge or sensitive command output is copied into the remote control plane.

**Mitigation:** the control repository must be private and remote stdout/stderr are length-bounded. Full local evidence remains hash-correlated in the audit ledger.

### Credential leakage in audit logs

**Threat:** command arguments or output contain tokens/passwords.

**Mitigation:** the audit ledger records the program name plus hashes of argv, cwd, stdout and stderr rather than raw content.

## Explicit non-goals in v0.2

- container/process sandboxing beyond subprocess policy
- OS-level privilege separation
- encrypted remote job payloads beyond GitHub HTTPS/private-repo controls
- multi-user authorization or role delegation
- unattended package installation or arbitrary privileged host administration

## Review rule

Any new executor, transport, or shortcut must preserve the same policy boundary. A feature that can reach the terminal without passing through policy + audit correlation is considered an architectural regression.
