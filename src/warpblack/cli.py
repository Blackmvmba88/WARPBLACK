from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .client import WarpClient, WarpClientError
from .executor import TerminalExecutor
from .models import CommandRequest
from .policy import PolicyError
from .server import BridgeConfig, serve


DEFAULT_URL = "http://127.0.0.1:8765"
TOKEN_ENV = "WARPBLACK_TOKEN"


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
    execute.add_argument("argv", nargs=argparse.REMAINDER, help="Command after --")

    bridge = sub.add_parser("serve", help="Run authenticated local WARPBLACK bridge")
    bridge.add_argument("--workspace", default=".", help="Allowed workspace root")
    bridge.add_argument("--host", default="127.0.0.1", help="Loopback bind address only")
    bridge.add_argument("--port", type=int, default=8765)

    call = sub.add_parser("call", help="Execute through a running WARPBLACK bridge")
    call.add_argument("--url", default=DEFAULT_URL)
    call.add_argument("--cwd", default=".")
    call.add_argument("--timeout", type=float, default=60.0)
    call.add_argument("--approve", action="store_true")
    call.add_argument("argv", nargs=argparse.REMAINDER, help="Command after --")

    health = sub.add_parser("health", help="Check bridge liveness")
    health.add_argument("--url", default=DEFAULT_URL)

    capabilities = sub.add_parser("capabilities", help="Read authenticated bridge capabilities")
    capabilities.add_argument("--url", default=DEFAULT_URL)

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

        try:
            result = TerminalExecutor(workspace).execute(request)
        except (PolicyError, FileNotFoundError, PermissionError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}))
            return 3

        payload = result.to_dict()
        payload["ok"] = result.exit_code == 0 and not result.timed_out
        print(json.dumps(payload, ensure_ascii=False))
        return 0 if payload["ok"] else 1

    if args.command == "serve":
        try:
            config = BridgeConfig(
                workspace_root=Path(args.workspace).resolve(),
                token=_token(),
                host=args.host,
                port=args.port,
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

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
