from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .executor import TerminalExecutor
from .models import CommandRequest
from .policy import PolicyError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="warpblack",
        description="BlackMamba safety-first terminal bridge",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    execute = sub.add_parser("exec", help="Execute one structured terminal command")
    execute.add_argument("--workspace", default=".", help="Allowed workspace root")
    execute.add_argument("--cwd", default=".", help="Working directory inside workspace")
    execute.add_argument("--timeout", type=float, default=60.0, help="Timeout in seconds")
    execute.add_argument("--approve", action="store_true", help="Approve stateful/code execution")
    execute.add_argument("argv", nargs=argparse.REMAINDER, help="Command after --")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command != "exec":
        return 2

    command = list(args.argv)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print(json.dumps({"ok": False, "error": "missing command argv"}), file=sys.stderr)
        return 2

    workspace = Path(args.workspace).resolve()
    cwd = Path(args.cwd)
    if not cwd.is_absolute():
        cwd = workspace / cwd

    request = CommandRequest.from_parts(
        command,
        cwd,
        timeout_s=args.timeout,
        approved=args.approve,
    )

    try:
        result = TerminalExecutor(workspace).execute(request)
    except (PolicyError, FileNotFoundError, PermissionError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 3

    payload = result.to_dict()
    payload["ok"] = result.exit_code == 0 and not result.timed_out
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
