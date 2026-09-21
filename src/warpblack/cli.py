from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .audit import AuditLedger
from .client import WarpClient, WarpClientError
from .executor import TerminalExecutor
from .github_queue import GitHubControlPlane, GitHubQueueError, token_from_env
from .models import CommandRequest
from .policy import PolicyError
from .readme_absorb import ReadmeAbsorber
from .server import BridgeConfig, serve


DEFAULT_URL = "http://127.0.0.1:8765"
DEFAULT_AUDIT_LOG = "~/.warpblack/audit.jsonl"
TOKEN_ENV = "WARPBLACK_TOKEN"


def _add_audit_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--audit-log",
        default=DEFAULT_AUDIT_LOG,
        help="Append-only local JSONL audit ledger",
    )


def _add_github_control_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", required=True, help="Private control repo as owner/name")
    parser.add_argument("--actor", required=True, help="Only accept jobs authored by this login")
    parser.add_argument("--workspace", default=".", help="Allowed local workspace root")
    _add_audit_arg(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="warpblack",
        description="BlackMamba safety-first terminal bridge",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    execute = sub.add_parser("exec", help="Execute one local structured terminal command")
    execute.add_argument("--workspace", default=".", help="Allowed workspace root")
    execute.add_argument("--cwd", default=".", help="Working directory inside workspace")
    execute.add_argument("--timeout", type=float, default=60.0, help="Timeout in seconds")
    execute.add_argument("--approve", action="store_true", help="Approve stateful/code execution")
    _add_audit_arg(execute)
    execute.add_argument("argv", nargs=argparse.REMAINDER, help="Command after --")

    bridge = sub.add_parser("serve", help="Run authenticated local WARPBLACK bridge")
    bridge.add_argument("--workspace", default=".", help="Allowed workspace root")
    bridge.add_argument("--host", default="127.0.0.1", help="Loopback bind address only")
    bridge.add_argument("--port", type=int, default=8765)
    _add_audit_arg(bridge)

    call = sub.add_parser("call", help="Execute through a running WARPBLACK bridge")
    call.add_argument("--url", default=DEFAULT_URL)
    call.add_argument("--cwd", default=".")
    call.add_argument("--timeout", type=float, default=60.0)
    call.add_argument("--approve", action="store_true")
    call.add_argument("argv", nargs=argparse.REMAINDER, help="Command after --")

    absorb = sub.add_parser("absorb", help="Incrementally absorb project context into README state")
    absorb.add_argument("--workspace", default=".", help="Project workspace root")
    absorb.add_argument("--message", required=True, help="Incoming interaction or trigger phrase")
    absorb.add_argument("--project", help="Project name stored in README state")
    absorb.add_argument("--fact", action="append", default=[], help="Confirmed fact; repeatable")
    absorb.add_argument("--derived", action="append", default=[], help="Derived item; repeatable")
    absorb.add_argument("--proposed", action="append", default=[], help="Proposed item; repeatable")

    absorb_call = sub.add_parser(
        "absorb-call",
        help="Send incremental README context through a running bridge",
    )
    absorb_call.add_argument("--url", default=DEFAULT_URL)
    absorb_call.add_argument("--message", required=True, help="Incoming interaction or trigger phrase")
    absorb_call.add_argument("--project", help="Project name stored in README state")
    absorb_call.add_argument("--fact", action="append", default=[], help="Confirmed fact; repeatable")
    absorb_call.add_argument("--derived", action="append", default=[], help="Derived item; repeatable")
    absorb_call.add_argument("--proposed", action="append", default=[], help="Proposed item; repeatable")

    health = sub.add_parser("health", help="Check bridge liveness")
    health.add_argument("--url", default=DEFAULT_URL)

    capabilities = sub.add_parser("capabilities", help="Read authenticated bridge capabilities")
    capabilities.add_argument("--url", default=DEFAULT_URL)

    github_once = sub.add_parser("github-once", help="Process at most one private GitHub job")
    _add_github_control_args(github_once)

    github_watch = sub.add_parser("github-watch", help="Watch a private GitHub repo for jobs")
    _add_github_control_args(github_watch)
    github_watch.add_argument("--poll", type=float, default=5.0, help="Polling interval in seconds")

    return parser


def _command_argv(raw: list[str]) -> list[str]:
    command = list(raw)
    if command and command[0] == "--":
        command = command[1:]
    return command


def _token(required: bool = True) -> str:
    value = os.environ.get(TOKEN_ENV, "")
    if required and not value:
        raise ValueError(f"{TOKEN_ENV} is required")
    return value


def _audit_path(raw: str) -> Path:
    return Path(raw).expanduser()


def _github_control(args: argparse.Namespace) -> GitHubControlPlane:
    return GitHubControlPlane(
        token=token_from_env(),
        repository=args.repo,
        allowed_actor=args.actor,
        workspace_root=Path(args.workspace).resolve(),
        audit_log=_audit_path(args.audit_log),
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "exec":
        command = _command_argv(args.argv)
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
        executor = TerminalExecutor(
            workspace,
            audit_ledger=AuditLedger(_audit_path(args.audit_log)),
            source="cli",
        )
        try:
            result = executor.execute(request)
        except (PolicyError, FileNotFoundError, PermissionError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}))
            return 3

        payload = result.to_dict()
        payload["ok"] = result.exit_code == 0 and not result.timed_out
        print(json.dumps(payload, ensure_ascii=False))
        return 0 if payload["ok"] else 1

    if args.command == "absorb":
        try:
            absorber = ReadmeAbsorber(Path(args.workspace).resolve())
            payload = absorber.ingest(
                message=args.message,
                project_name=args.project,
                confirmed=args.fact,
                derived=args.derived,
                proposed=args.proposed,
            ).to_dict()
        except (TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
            return 3
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.command == "absorb-call":
        try:
            client = WarpClient(args.url, _token())
            payload = client.absorb_readme(
                message=args.message,
                project_name=args.project,
                confirmed=args.fact,
                derived=args.derived,
                proposed=args.proposed,
            )
        except (ValueError, WarpClientError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
            return 3
        print(json.dumps(payload, ensure_ascii=False))
        return 0 if payload.get("ok") else 1

    if args.command == "serve":
        try:
            config = BridgeConfig(
                workspace_root=Path(args.workspace).resolve(),
                token=_token(),
                host=args.host,
                port=args.port,
                audit_log=_audit_path(args.audit_log),
            )
        except ValueError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
            return 2
        print(
            json.dumps(
                {
                    "ok": True,
                    "service": "warpblack",
                    "listen": f"http://{config.host}:{config.port}",
                    "workspace": str(config.workspace_root),
                    "audit_log": str(config.audit_log),
                }
            ),
            flush=True,
        )
        serve(config)
        return 0

    if args.command in {"call", "health", "capabilities"}:
        try:
            token = _token(required=args.command != "health")
            client = WarpClient(args.url, token)
            if args.command == "health":
                payload = client.health()
            elif args.command == "capabilities":
                payload = client.capabilities()
            else:
                command = _command_argv(args.argv)
                if not command:
                    raise ValueError("missing command argv")
                payload = client.execute(
                    command,
                    cwd=args.cwd,
                    timeout_s=args.timeout,
                    approved=args.approve,
                )
        except (ValueError, WarpClientError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
            return 3

        print(json.dumps(payload, ensure_ascii=False))
        return 0 if payload.get("ok") else 1

    if args.command in {"github-once", "github-watch"}:
        try:
            control = _github_control(args)
            control.assert_private_repository()
            if args.command == "github-once":
                processed = control.run_once()
                print(json.dumps({"ok": True, "processed": processed}))
                return 0
            control.watch(poll_interval_s=args.poll)
            return 0
        except KeyboardInterrupt:
            return 0
        except (ValueError, GitHubQueueError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
            return 3

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
