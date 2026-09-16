from pathlib import Path
import sys

from warpblack.executor import TerminalExecutor
from warpblack.models import CommandRequest


def test_executor_returns_structured_evidence(tmp_path: Path) -> None:
    request = CommandRequest.from_parts(
        [sys.executable, "-c", "print('warp-ok')"],
        tmp_path,
        approved=True,
    )
    result = TerminalExecutor(tmp_path).execute(request)

    assert result.exit_code == 0
    assert result.stdout.strip() == "warp-ok"
    assert result.stderr == ""
    assert result.timed_out is False
    assert result.duration_ms >= 0
