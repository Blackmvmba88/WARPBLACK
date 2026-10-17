"""Versioned, execution-free task envelope for modular BlackMamba handoffs."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal, Mapping
from uuid import UUID

State = Literal["PROPOSED", "APPROVED", "RUNNING", "BLOCKED", "NEEDS_REVIEW", "VERIFIED", "DONE"]
Risk = Literal["read_only", "mutation", "high_impact"]
STATES = frozenset({"PROPOSED", "APPROVED", "RUNNING", "BLOCKED", "NEEDS_REVIEW", "VERIFIED", "DONE"})
RISKS = frozenset({"read_only", "mutation", "high_impact"})
TRANSITIONS = {
    "PROPOSED": frozenset({"APPROVED", "BLOCKED"}),
    "APPROVED": frozenset({"RUNNING", "BLOCKED"}),
    "RUNNING": frozenset({"BLOCKED", "NEEDS_REVIEW", "VERIFIED"}),
    "BLOCKED": frozenset({"APPROVED"}),
    "NEEDS_REVIEW": frozenset({"APPROVED", "BLOCKED", "VERIFIED"}),
    "VERIFIED": frozenset({"DONE"}),
    "DONE": frozenset(),
}
FIELDS = frozenset({"schema_version", "request_id", "task_id", "source", "workspace_id", "intent", "state", "risk", "approval_ref", "expected"})


def _required(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be a nonempty, trimmed string")
    if len(value) > 512 or any(ord(c) < 32 for c in value):
        raise ValueError(f"{field} contains invalid characters")
    return value


@dataclass(frozen=True)
class TaskEnvelopeV1:
    schema_version: int
    request_id: str
    task_id: str
    source: str
    workspace_id: str
    intent: str
    state: State
    risk: Risk
    approval_ref: str | None
    expected: tuple[str, ...]

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> "TaskEnvelopeV1":
        if not isinstance(raw, Mapping) or set(raw) != FIELDS:
            raise ValueError("invalid envelope fields")
        if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
            raise ValueError("unsupported schema version")
        if raw["state"] not in STATES or raw["risk"] not in RISKS:
            raise ValueError("invalid state or risk")
        approval = raw["approval_ref"]
        if approval is not None:
            approval = _required(approval, "approval_ref")
        expected = raw["expected"]
        if not isinstance(expected, (list, tuple)) or len(expected) > 32:
            raise ValueError("expected must be a bounded list")
        expected_tuple = tuple(_required(item, "expected item") for item in expected)
        return cls(
            schema_version=1,
            request_id=_required(raw["request_id"], "request_id"),
            task_id=_required(raw["task_id"], "task_id"),
            source=_required(raw["source"], "source"),
            workspace_id=_required(raw["workspace_id"], "workspace_id"),
            intent=_required(raw["intent"], "intent"),
            state=raw["state"],
            risk=raw["risk"],
            approval_ref=approval,
            expected=expected_tuple,
        )

    def transition(self, next_state: State, *, evidence_ref: str | None = None) -> "TaskEnvelopeV1":
        if next_state not in TRANSITIONS[self.state]:
            raise ValueError(f"invalid transition: {self.state} -> {next_state}")
        if next_state == "APPROVED" and self.risk != "read_only" and not self.approval_ref:
            raise ValueError("mutation requires explicit approval reference")
        if next_state in {"VERIFIED", "DONE"} and not evidence_ref:
            raise ValueError("verification requires evidence reference")
        if evidence_ref is not None:
            _required(evidence_ref, "evidence_ref")
        return replace(self, state=next_state)
