from __future__ import annotations

import json
from pathlib import Path
import sys

from warpblack.audit import AuditLedger
from warpblack.executor import TerminalExecutor
from warpblack.models import CommandRequest


def test_audit_ledger_correlates_without_raw_streams_or_args(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit" / "audit.jsonl"
    secret = "super-secret-value"
    request = CommandRequest.from_parts(
        [sys.executable, "-c", f"print('{secret}')"],
        tmp_path,
        approved=True,
        request_id="req-test-1",
    )

    executor = TerminalExecutor(
        tmp_path,
        audit_ledger=AuditLedger(audit_path),
        source="test",
        actor="tester",
    )
    result = executor.execute(request)

    assert result.request_id == "req-test-1"
    raw = audit_path.read_text(encoding="utf-8")
    assert secret not in raw
    assert "print(" not in raw

    record = json.loads(raw)
    assert record["event"] == "execution_result"
    assert record["request_id"] == "req-test-1"
    assert record["source"] == "test"
    assert record["actor"] == "tester"
    assert record["program"]
    assert len(record["stdout_sha256"]) == 64
    assert len(record["argv_sha256"]) == 64


def test_denied_execution_is_also_audited(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    request = CommandRequest.from_parts(
        ["sudo", "true"],
        tmp_path,
        approved=True,
        request_id="req-denied-1",
    )
    executor = TerminalExecutor(
        tmp_path,
        audit_ledger=AuditLedger(audit_path),
        source="test",
    )

    try:
        executor.execute(request)
    except Exception:
        pass

    record = json.loads(audit_path.read_text(encoding="utf-8"))
    assert record["event"] == "execution_denied"
    assert record["request_id"] == "req-denied-1"
    assert "sudo" in record["reason"]
