from pathlib import Path
import subprocess
from warpblack.readme_handoff import ReadmeHandoff

def test_non_trigger_only_absorbs(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    result = ReadmeHandoff(tmp_path).run(
        message="keep thinking",
        objective="unused",
        patch="unused",
        approved=True,
    )
    assert result.absorb.triggered is False
    assert result.construct is None
