from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

from .audit import AuditLedger
from .capabilities import CapabilityError, CapabilityRegistry
from .contracts import IntentEnvelope
from .client import WarpClient, WarpClientError
from .construct import PatchConstructor
from .doctor import run_doctor
from .desktop import (
    DesktopError,
    activate_application,
    capture_screen,
    click_at,
    frontmost_application,
    focused_window,
    keystroke,
    list_windows,
)
from .executor import TerminalExecutor
from .github_queue import GitHubControlPlane, GitHubQueueError, token_from_env
from .models import CommandRequest
from .policy import PolicyError
from .project_registry import DEFAULT_PROJECTS_FILE, ProjectRegistry, ProjectRegistryError
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

    construct = sub.add_parser(
        "construct",
        help="Apply an explicit AI-produced patch using absorbed project context",
    )
    construct.add_argument("--workspace", default=".", help="Project workspace root")
    construct.add_argument("--message", required=True, help="Must contain the explicit construct trigger")
    construct.add_argument("--objective", required=True, help="Human-readable task objective")
    construct.add_argument("--patch-file", required=True, help="Unified diff file to apply")
    construct.add_argument(
        "--check-json",
        action="append",
        default=[],
        help='Validation argv as JSON, e.g. ["pytest","-q"]; repeatable',
    )
    construct.add_argument("--timeout", type=float, default=120.0)
    construct.add_argument("--task-id")
    _add_audit_arg(construct)

    construct_call = sub.add_parser(
        "construct-call",
        help="Send an explicit patch construction task through a running bridge",
    )
    construct_call.add_argument("--url", default=DEFAULT_URL)
    construct_call.add_argument("--message", required=True)
    construct_call.add_argument("--objective", required=True)
    construct_call.add_argument("--patch-file", required=True)
    construct_call.add_argument("--check-json", action="append", default=[])
    construct_call.add_argument("--timeout", type=float, default=120.0)
    construct_call.add_argument("--task-id")

    health = sub.add_parser("health", help="Check bridge liveness")
    health.add_argument("--url", default=DEFAULT_URL)

    capabilities = sub.add_parser("capabilities", help="Read authenticated bridge capabilities")
    capabilities.add_argument("--url", default=DEFAULT_URL)

    doctor = sub.add_parser("doctor", help="Check whether this machine is ready to run WARPBLACK")
    doctor.add_argument("--workspace", default=".", help="Workspace root to validate")
    doctor.add_argument("--repo", help="Optional private control repo as owner/name")
    doctor.add_argument("--actor", help="Optional allowlisted GitHub actor")

    desktop = sub.add_parser("desktop", help="Observe or control the local macOS desktop")
    desktop_sub = desktop.add_subparsers(dest="desktop_command", required=True)
    desktop_sub.add_parser("frontmost", help="Read the frontmost application")
    desktop_sub.add_parser("focused-window", help="Read PID and title of the focused window")
    desktop_sub.add_parser("windows", help="List visible application windows")
    desktop_capture = desktop_sub.add_parser("capture", help="Capture the current screen")
    desktop_capture.add_argument("--output", help="Optional PNG output path")
    desktop_capture.add_argument("--expect-pid", type=int)
    desktop_capture.add_argument("--expect-title")
    desktop_activate = desktop_sub.add_parser("activate", help="Bring an application to the front")
    desktop_activate.add_argument("application")
    desktop_activate.add_argument("--approve", action="store_true")
    desktop_keys = desktop_sub.add_parser("keystroke", help="Send a keyboard chord")
    desktop_keys.add_argument("keys")
    desktop_keys.add_argument("--modifier", action="append", default=[])
    desktop_keys.add_argument("--approve", action="store_true")
    desktop_keys.add_argument("--expect-pid", type=int)
    desktop_keys.add_argument("--expect-title")
    desktop_click = desktop_sub.add_parser("click", help="Click a screen coordinate")
    desktop_click.add_argument("x", type=int)
    desktop_click.add_argument("y", type=int)
    desktop_click.add_argument("--approve", action="store_true")
    desktop_click.add_argument("--expect-pid", type=int)
    desktop_click.add_argument("--expect-title")


    blender = sub.add_parser("blender", help="Run bounded structured Blender capabilities")
    blender_sub = blender.add_subparsers(dest="blender_command", required=True)
    blender_translate = blender_sub.add_parser(
        "translate-restore",
        help="Move one Blender object, verify the delta, and restore it without saving",
    )
    blender_translate.add_argument("target", help="Workspace-relative .blend path")
    blender_translate.add_argument("--workspace", default=".", help="Allowed workspace root")
    blender_translate.add_argument("--object", required=True, dest="object_name")
    blender_translate.add_argument("--dx", type=float, default=0.0)
    blender_translate.add_argument("--dy", type=float, default=0.0)
    blender_translate.add_argument("--dz", type=float, default=0.0)
    blender_translate.add_argument("--timeout", type=float, default=120.0)
    blender_translate.add_argument("--request-id")
    blender_translate.add_argument("--project")
    blender_translate.add_argument(
        "--approve",
        action="store_true",
        help="Explicitly approve the bounded Blender transaction",
    )

    blender_certify = blender_sub.add_parser(
        "certify-translate-restore",
        help="Create BM-BLENDER-002 visual and cryptographic evidence",
    )
    blender_certify.add_argument("target", help="Workspace-relative .blend path")
    blender_certify.add_argument("--workspace", default=".", help="Allowed workspace root")
    blender_certify.add_argument("--object", required=True, dest="object_name")
    blender_certify.add_argument("--dx", type=float, default=0.0)
    blender_certify.add_argument("--dy", type=float, default=0.0)
    blender_certify.add_argument("--dz", type=float, default=0.0)
    blender_certify.add_argument("--timeout", type=float, default=120.0)
    blender_certify.add_argument("--request-id")
    blender_certify.add_argument("--project")
    blender_certify.add_argument(
        "--approve",
        action="store_true",
        help="Explicitly approve the certified Blender transaction",
    )

    github_bootstrap = sub.add_parser(
        "github-bootstrap",
        help="Verify private control repo and create required labels",
    )
    _add_github_control_args(github_bootstrap)

    github_once = sub.add_parser("github-once", help="Process at most one private GitHub job")
    _add_github_control_args(github_once)

    github_watch = sub.add_parser("github-watch", help="Watch a private GitHub repo for jobs")
    _add_github_control_args(github_watch)
    github_watch.add_argument("--poll", type=float, default=5.0, help="Polling interval in seconds")

    projects = sub.add_parser(
        "projects",
        help="Register project folders and maintain a logical order independent of disk layout",
    )
    projects.add_argument(
        "--registry",
        default=DEFAULT_PROJECTS_FILE,
        help="Persistent project registry JSON file",
    )
    project_sub = projects.add_subparsers(dest="projects_command", required=True)

    project_add = project_sub.add_parser("add", help="Register one project folder")
    project_add.add_argument("path")
    project_add.add_argument("--name")
    project_add.add_argument("--group")
    project_add.add_argument("--status", default="active")
    project_add.add_argument("--position", type=int, help="1-based logical position")

    project_scan = project_sub.add_parser("scan", help="Discover project folders below a root")
    project_scan.add_argument("root")
    project_scan.add_argument("--depth", type=int, default=2)
    project_scan.add_argument("--group")

    project_sub.add_parser("list", help="List projects in canonical logical order")

    project_move = project_sub.add_parser("move", help="Move a project in logical order")
    project_move.add_argument("project", help="Project id, unique name, or registered path")
    project_move.add_argument("position", type=int, help="1-based target position")

    project_remove = project_sub.add_parser("remove", help="Remove a project from the registry")
    project_remove.add_argument("project", help="Project id, unique name, or registered path")

    project_refresh = project_sub.add_parser("refresh", help="Refresh project metadata and missing state")
    project_refresh.add_argument("project", nargs="?", help="Optional project id/name/path")

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


def _parse_checks(raw_values: list[str]) -> list[list[str]]:
    checks: list[list[str]] = []
    for raw in raw_values:
        value = json.loads(raw)
        if not isinstance(value, list) or not value or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise ValueError("--check-json must be a non-empty JSON array of strings")
        checks.append(value)
    return checks


def _project_payload(entry) -> dict[str, object]:
    payload = asdict(entry)
    payload["position"] = entry.order + 1
    return payload


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

    if args.command == "desktop":
        try:
            if args.desktop_command == "frontmost":
                payload = frontmost_application().to_dict()
            elif args.desktop_command == "focused-window":
                payload = focused_window().to_dict()
            elif args.desktop_command == "windows":
                payload = list_windows().to_dict()
            elif args.desktop_command == "capture":
                payload = capture_screen(
                    args.output,
                    expected_pid=args.expect_pid,
                    expected_title=args.expect_title,
                ).to_dict()
            elif args.desktop_command == "activate":
                payload = activate_application(args.application, approved=args.approve).to_dict()
            elif args.desktop_command == "keystroke":
                payload = keystroke(
                    args.keys,
                    modifiers=args.modifier,
                    approved=args.approve,
                    expected_pid=args.expect_pid,
                    expected_title=args.expect_title,
                ).to_dict()
            else:
                payload = click_at(
                    args.x,
                    args.y,
                    approved=args.approve,
                    expected_pid=args.expect_pid,
                    expected_title=args.expect_title,
                ).to_dict()
        except DesktopError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
            return 3
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok") else 1


    if args.command == "blender":
        workspace = Path(args.workspace).resolve()
        try:
            registry = CapabilityRegistry(workspace)
            capability_name = (
                "blender.object.translate_restore_certify"
                if args.blender_command == "certify-translate-restore"
                else "blender.object.translate_restore"
            )
            intent = IntentEnvelope.from_payload(
                {
                    "intent": capability_name,
                    "target": args.target,
                    "project": args.project,
                    "request_id": args.request_id,
                    "constraints": {
                        "object": args.object_name,
                        "delta": [args.dx, args.dy, args.dz],
                        "approved": args.approve,
                        "timeout_s": args.timeout,
                    },
                }
            )
            payload = registry.execute(intent).to_dict()
        except (CapabilityError, TypeError, ValueError, OSError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
            return 3
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok") else 1

    if args.command == "doctor":
        payload = run_doctor(
            workspace=args.workspace,
            repository=args.repo,
            actor=args.actor,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["ok"] else 1

    if args.command == "projects":
        try:
            registry = ProjectRegistry(args.registry)
            if args.projects_command == "add":
                if args.position is not None and args.position < 1:
                    raise ProjectRegistryError("position must be >= 1")
                entry = registry.add(
                    args.path,
                    name=args.name,
                    group=args.group,
                    status=args.status,
                    position=args.position - 1 if args.position is not None else None,
                )
                payload = {"ok": True, "project": _project_payload(entry)}
            elif args.projects_command == "scan":
                added = registry.scan(args.root, max_depth=args.depth, group=args.group)
                payload = {
                    "ok": True,
                    "added": [_project_payload(item) for item in added],
                    "projects": [_project_payload(item) for item in registry.entries],
                }
            elif args.projects_command == "list":
                payload = {
                    "ok": True,
                    "registry": str(registry.state_file),
                    "projects": [_project_payload(item) for item in registry.entries],
                }
            elif args.projects_command == "move":
                if args.position < 1:
                    raise ProjectRegistryError("position must be >= 1")
                entry = registry.move(args.project, args.position - 1)
                payload = {
                    "ok": True,
                    "project": _project_payload(entry),
                    "projects": [_project_payload(item) for item in registry.entries],
                }
            elif args.projects_command == "remove":
                entry = registry.remove(args.project)
                payload = {"ok": True, "removed": _project_payload(entry)}
            else:
                refreshed = registry.refresh(args.project)
                payload = {
                    "ok": True,
                    "refreshed": [_project_payload(item) for item in refreshed],
                }
        except (ProjectRegistryError, OSError, ValueError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
            return 3

        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

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

    if args.command in {"construct", "construct-call"}:
        try:
            patch = Path(args.patch_file).read_text(encoding="utf-8")
            checks = _parse_checks(args.check_json)
            if args.command == "construct":
                workspace = Path(args.workspace).resolve()
                constructor = PatchConstructor(
                    workspace,
                    executor=TerminalExecutor(
                        workspace,
                        audit_ledger=AuditLedger(_audit_path(args.audit_log)),
                        source="construct-cli",
                    ),
                )
                payload = constructor.construct(
                    message=args.message,
                    objective=args.objective,
                    patch=patch,
                    checks=checks,
                    timeout_s=args.timeout,
                    task_id=args.task_id,
                    approved=True,
                ).to_dict()
            else:
                client = WarpClient(args.url, _token())
                payload = client.construct(
                    message=args.message,
                    objective=args.objective,
                    patch=patch,
                    checks=checks,
                    timeout_s=args.timeout,
                    task_id=args.task_id,
                )
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            WarpClientError,
            PolicyError,
        ) as exc:
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

    if args.command in {"github-bootstrap", "github-once", "github-watch"}:
        try:
            control = _github_control(args)
            if args.command == "github-bootstrap":
                print(json.dumps(control.bootstrap(), ensure_ascii=False))
                return 0
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
