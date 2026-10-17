"""Pure contract gates: no subprocess, network, or filesystem operations."""
import pytest

from warpblack.task_envelope import TaskEnvelopeV1


def sample(**overrides):
    data = {
        "schema_version": 1,
        "request_id": "request-001",
        "task_id": "BM-CORE-001",
        "source": "user",
        "workspace_id": "WARPBLACK",
        "intent": "inspect",
        "state": "PROPOSED",
        "risk": "read_only",
        "approval_ref": None,
        "expected": ["git status"],
    }
    data.update(overrides)
    return data


def test_valid_envelope():
    task = TaskEnvelopeV1.parse(sample())
    assert task.expected == ("git status",)
    assert task.state == "PROPOSED"


@pytest.mark.parametrize("field,value", [
    ("schema_version", 2),
    ("schema_version", True),
    ("request_id", ""),
    ("workspace_id", " ../escape"),
    ("state", "DONE_ALREADY"),
    ("risk", "anything"),
    ("expected", [""]),
])
def test_rejects_invalid_contract(field, value):
    with pytest.raises(ValueError):
        TaskEnvelopeV1.parse(sample(**{field: value}))


def test_rejects_unknown_fields():
    with pytest.raises(ValueError):
        TaskEnvelopeV1.parse(sample(shell="rm -rf ."))


def test_read_only_state_path():
    task = TaskEnvelopeV1.parse(sample())
    task = task.transition("APPROVED").transition("RUNNING")
    task = task.transition("VERIFIED", evidence_ref="sha256:some-evidence")
    assert task.transition("DONE", evidence_ref="sha256:some-evidence").state == "DONE"


def test_mutation_needs_approval():
    task = TaskEnvelopeV1.parse(sample(risk="mutation"))
    with pytest.raises(ValueError, match="approval"):
        task.transition("APPROVED")
    approved = TaskEnvelopeV1.parse(sample(risk="mutation", approval_ref="approval-1"))
    assert approved.transition("APPROVED").state == "APPROVED"


def test_cannot_skip_execution_or_evidence():
    task = TaskEnvelopeV1.parse(sample())
    with pytest.raises(ValueError, match="invalid transition"):
        task.transition("DONE")
    task = task.transition("APPROVED").transition("RUNNING")
    with pytest.raises(ValueError, match="evidence"):
        task.transition("VERIFIED")
