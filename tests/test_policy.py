from pathlib import Path

from warpblack.models import CommandRequest
from warpblack.policy import decide


def test_read_only_command_is_allowed(tmp_path: Path) -> None:
    request = CommandRequest.from_parts(["ls"], tmp_path)
    decision = decide(request, tmp_path)
    assert decision.allowed
    assert decision.risk == "low"


def test_stateful_command_requires_approval(tmp_path: Path) -> None:
    request = CommandRequest.from_parts(["python3", "-c", "print('x')"], tmp_path)
    decision = decide(request, tmp_path)
    assert not decision.allowed
    assert decision.risk == "approval-required"


def test_approved_stateful_command_is_allowed(tmp_path: Path) -> None:
    request = CommandRequest.from_parts(
        ["python3", "-c", "print('x')"], tmp_path, approved=True
    )
    decision = decide(request, tmp_path)
    assert decision.allowed
    assert decision.risk == "elevated"


def test_hard_deny_wins_even_with_approval(tmp_path: Path) -> None:
    request = CommandRequest.from_parts(["sudo", "true"], tmp_path, approved=True)
    decision = decide(request, tmp_path)
    assert not decision.allowed


def test_cwd_must_stay_inside_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent
    request = CommandRequest.from_parts(["ls"], outside)
    decision = decide(request, tmp_path)
    assert not decision.allowed


def test_low_risk_command_cannot_read_absolute_path_outside_workspace(tmp_path: Path) -> None:
    request = CommandRequest.from_parts(["cat", "/etc/passwd"], tmp_path)
    decision = decide(request, tmp_path)
    assert not decision.allowed
    assert decision.risk == "approval-required"


def test_low_risk_command_cannot_traverse_outside_workspace(tmp_path: Path) -> None:
    request = CommandRequest.from_parts(["cat", "../../secret.txt"], tmp_path)
    decision = decide(request, tmp_path)
    assert not decision.allowed


def test_find_is_not_implicitly_read_only(tmp_path: Path) -> None:
    request = CommandRequest.from_parts(["find", ".", "-delete"], tmp_path)
    decision = decide(request, tmp_path)
    assert not decision.allowed
    assert decision.risk == "approval-required"


def test_git_ext_diff_requires_approval(tmp_path: Path) -> None:
    request = CommandRequest.from_parts(["git", "diff", "--ext-diff"], tmp_path)
    decision = decide(request, tmp_path)
    assert not decision.allowed
    assert decision.risk == "approval-required"
