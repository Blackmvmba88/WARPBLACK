from __future__ import annotations

from dataclasses import asdict, dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class IntentEnvelope:
    intent: str
    target: str = "."
    project: str | None = None
    constraints: dict[str, object] = field(default_factory=dict)
    request_id: str = ""

    @classmethod
    def from_payload(cls, payload: object) -> "IntentEnvelope":
        if not isinstance(payload, dict):
            raise TypeError("intent payload must be a JSON object")

        intent = payload.get("intent")
        if not isinstance(intent, str) or not intent.strip():
            raise TypeError("intent must be a non-empty string")

        target = payload.get("target", ".")
        if not isinstance(target, str) or not target.strip():
            raise TypeError("target must be a non-empty string")

        project = payload.get("project")
        if project is not None and not isinstance(project, str):
            raise TypeError("project must be a string")

        constraints = payload.get("constraints", {})
        if not isinstance(constraints, dict) or not all(
            isinstance(key, str) for key in constraints
        ):
            raise TypeError("constraints must be an object with string keys")

        request_id = payload.get("request_id")
        if request_id is None:
            request_id = uuid4().hex
        if not isinstance(request_id, str) or not request_id.strip():
            raise TypeError("request_id must be a non-empty string")

        return cls(
            intent=intent.strip(),
            target=target,
            project=project,
            constraints=dict(constraints),
            request_id=request_id,
        )


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    risk: str
    mutates: bool
    requires_approval: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionPlan:
    request_id: str
    intent: str
    capability: str
    steps: tuple[str, ...]
    risk: str
    mutates: bool
    requires_approval: bool

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["steps"] = list(self.steps)
        return data


@dataclass(frozen=True)
class ResultEnvelope:
    request_id: str
    status: str
    capability: str
    project: str | None
    changed: bool
    summary: str
    evidence: dict[str, object]
    plan: ExecutionPlan

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.status == "success",
            "request_id": self.request_id,
            "status": self.status,
            "capability": self.capability,
            "project": self.project,
            "changed": self.changed,
            "summary": self.summary,
            "evidence": self.evidence,
            "plan": self.plan.to_dict(),
        }
