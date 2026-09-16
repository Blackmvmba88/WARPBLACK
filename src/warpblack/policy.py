from __future__ import annotations

from pathlib import Path

from .models import CommandRequest, PolicyDecision


HARD_DENY = {
    "sudo", "su", "shutdown", "reboot", "halt", "poweroff",
    "diskutil", "fdisk", "mkfs", "dd",
}

READ_ONLY = {
    "pwd", "ls", "cat", "head", "tail", "find", "grep", "rg", "which", "whereis",
}

SAFE_GIT_SUBCOMMANDS = {
    "status", "diff", "log", "show", "rev-parse", "remote", "ls-files", "ls-tree",
}


class PolicyError(RuntimeError):
    pass


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def decide(request: CommandRequest, workspace_root: Path) -> PolicyDecision:
    if request.timeout_s <= 0 or request.timeout_s > 900:
        return PolicyDecision(False, "timeout must be between 0 and 900 seconds", "blocked")

    if not _inside(workspace_root, request.cwd):
        return PolicyDecision(False, "cwd escapes configured workspace root", "blocked")

    program = Path(request.argv[0]).name.lower()
    if program in HARD_DENY:
        return PolicyDecision(False, f"'{program}' is hard-denied", "blocked")

    if program in READ_ONLY:
        return PolicyDecision(True, "read-only command", "low")

    if program == "git" and len(request.argv) > 1:
        subcommand = request.argv[1].lower()
        if subcommand in SAFE_GIT_SUBCOMMANDS:
            return PolicyDecision(True, f"read-only git {subcommand}", "low")

    if request.approved:
        return PolicyDecision(True, "explicit approval granted", "elevated")

    return PolicyDecision(
        False,
        "command may execute or mutate state; explicit approval required",
        "approval-required",
    )


def require(request: CommandRequest, workspace_root: Path) -> PolicyDecision:
    decision = decide(request, workspace_root)
    if not decision.allowed:
        raise PolicyError(decision.reason)
    return decision
