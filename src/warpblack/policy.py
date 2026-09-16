from __future__ import annotations

from pathlib import Path

from .models import CommandRequest, PolicyDecision


HARD_DENY = {
    "sudo",
    "su",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "diskutil",
    "fdisk",
    "mkfs",
    "dd",
}

# Commands in this set are only low-risk after their path-like arguments are
# proven to stay inside the configured workspace. `find` is intentionally not
# here because options such as -delete and -exec can mutate/execute.
READ_ONLY = {
    "pwd",
    "ls",
    "cat",
    "head",
    "tail",
    "grep",
    "rg",
    "which",
    "whereis",
}

SAFE_GIT_SUBCOMMANDS = {
    "status",
    "diff",
    "log",
    "show",
    "rev-parse",
    "remote",
    "ls-files",
    "ls-tree",
}

GIT_EXECUTION_FLAGS = {"--ext-diff", "--textconv"}


class PolicyError(RuntimeError):
    pass


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _looks_path_like(value: str) -> bool:
    return (
        value.startswith(("/", "~", "."))
        or "/" in value
        or "\\" in value
    )


def _path_args_stay_inside(request: CommandRequest, workspace_root: Path) -> bool:
    """Fail closed on explicit path-like arguments that escape the workspace.

    This is deliberately conservative. A false positive only promotes the
    request to the explicit-approval path; it never silently grants more access.
    """

    for raw in request.argv[1:]:
        if raw.startswith("-"):
            continue
        if not _looks_path_like(raw):
            continue
        if raw.startswith("~"):
            return False
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = request.cwd / candidate
        if not _inside(workspace_root, candidate):
            return False
    return True


def decide(request: CommandRequest, workspace_root: Path) -> PolicyDecision:
    if request.timeout_s <= 0 or request.timeout_s > 900:
        return PolicyDecision(False, "timeout must be between 0 and 900 seconds", "blocked")

    if not _inside(workspace_root, request.cwd):
        return PolicyDecision(False, "cwd escapes configured workspace root", "blocked")

    program = Path(request.argv[0]).name.lower()
    if program in HARD_DENY:
        return PolicyDecision(False, f"'{program}' is hard-denied", "blocked")

    if program in READ_ONLY:
        if _path_args_stay_inside(request, workspace_root):
            return PolicyDecision(True, "read-only command confined to workspace", "low")
        if not request.approved:
            return PolicyDecision(
                False,
                "path-like argument may escape workspace; explicit approval required",
                "approval-required",
            )

    if program == "git" and len(request.argv) > 1:
        subcommand = request.argv[1].lower()
        has_execution_flag = any(arg in GIT_EXECUTION_FLAGS for arg in request.argv[2:])
        paths_confined = _path_args_stay_inside(request, workspace_root)
        if subcommand in SAFE_GIT_SUBCOMMANDS and not has_execution_flag and paths_confined:
            return PolicyDecision(True, f"read-only git {subcommand}", "low")
        if subcommand in SAFE_GIT_SUBCOMMANDS and not request.approved:
            return PolicyDecision(
                False,
                "git arguments may execute helpers or escape workspace; explicit approval required",
                "approval-required",
            )

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
