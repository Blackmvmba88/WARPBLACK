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

# ripgrep can leave the pure-read model: --pre launches a command for files and
# compressed-search mode can spawn external decompressors. These require the
# elevated approval path instead of inheriting READ_ONLY trust.
READ_ONLY_RISKY_FLAGS = {
    "rg": {"--pre", "-z", "--search-zip"},
}
READ_ONLY_RISKY_PREFIXES = {
    "rg": ("--pre=",),
}

SAFE_GIT_SUBCOMMANDS = {
    "status",
    "diff",
    "log",
    "show",
    "rev-parse",
    "ls-files",
    "ls-tree",
}

GIT_RISKY_FLAGS = {"--ext-diff", "--textconv", "--output"}
GIT_RISKY_PREFIXES = ("--output=",)


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


def _should_check_as_path(value: str, cwd: Path) -> bool:
    if _looks_path_like(value):
        return True
    candidate = cwd / value
    return candidate.exists() or candidate.is_symlink()


def _path_args_stay_inside(request: CommandRequest, workspace_root: Path) -> bool:
    """Fail closed on explicit, existing/symlink, or option-embedded paths."""

    for raw in request.argv[1:]:
        candidate_raw = raw
        if raw.startswith("-"):
            if "=" not in raw:
                continue
            candidate_raw = raw.split("=", 1)[1]
        if not _should_check_as_path(candidate_raw, request.cwd):
            continue
        if candidate_raw.startswith("~"):
            return False
        candidate = Path(candidate_raw)
        if not candidate.is_absolute():
            candidate = request.cwd / candidate
        if not _inside(workspace_root, candidate):
            return False
    return True


def _read_only_has_risky_flags(program: str, argv: tuple[str, ...]) -> bool:
    exact = READ_ONLY_RISKY_FLAGS.get(program, set())
    prefixes = READ_ONLY_RISKY_PREFIXES.get(program, ())
    return any(arg in exact or arg.startswith(prefixes) for arg in argv[1:])


def _git_has_risky_flags(argv: tuple[str, ...]) -> bool:
    for arg in argv[2:]:
        if arg in GIT_RISKY_FLAGS or arg.startswith(GIT_RISKY_PREFIXES):
            return True
    return False


def _git_remote_is_read_only(argv: tuple[str, ...]) -> bool:
    args = argv[2:]
    if not args:
        return True
    if args in (("-v",), ("--verbose",)):
        return True
    return args[0] == "get-url"


def decide(request: CommandRequest, workspace_root: Path) -> PolicyDecision:
    if request.timeout_s <= 0 or request.timeout_s > 900:
        return PolicyDecision(False, "timeout must be between 0 and 900 seconds", "blocked")

    if not _inside(workspace_root, request.cwd):
        return PolicyDecision(False, "cwd escapes configured workspace root", "blocked")

    program = Path(request.argv[0]).name.lower()
    if program in HARD_DENY:
        return PolicyDecision(False, f"'{program}' is hard-denied", "blocked")

    if program in READ_ONLY:
        risky_flags = _read_only_has_risky_flags(program, request.argv)
        paths_confined = _path_args_stay_inside(request, workspace_root)
        if not risky_flags and paths_confined:
            return PolicyDecision(True, "read-only command confined to workspace", "low")
        if not request.approved:
            return PolicyDecision(
                False,
                "read command may execute helpers or escape workspace; explicit approval required",
                "approval-required",
            )

    if program == "git" and len(request.argv) > 1:
        subcommand = request.argv[1].lower()
        paths_confined = _path_args_stay_inside(request, workspace_root)
        risky_flags = _git_has_risky_flags(request.argv)
        safe_subcommand = subcommand in SAFE_GIT_SUBCOMMANDS
        safe_remote = subcommand == "remote" and _git_remote_is_read_only(request.argv)
        if (safe_subcommand or safe_remote) and not risky_flags and paths_confined:
            return PolicyDecision(True, f"read-only git {subcommand}", "low")
        if (safe_subcommand or subcommand == "remote") and not request.approved:
            return PolicyDecision(
                False,
                "git arguments may mutate, execute helpers, or escape workspace; approval required",
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
