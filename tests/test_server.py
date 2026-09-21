from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading

import pytest

from warpblack.client import WarpClient, WarpClientError
from warpblack.server import BridgeConfig, WarpHTTPServer


TOKEN = "warpblack-test-token-1234567890"


@contextmanager
def running_bridge(workspace: Path):
    config = BridgeConfig(workspace_root=workspace, token=TOKEN, port=0)
    server = WarpHTTPServer(config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_health_and_capabilities(tmp_path: Path) -> None:
    with running_bridge(tmp_path) as base_url:
        client = WarpClient(base_url, TOKEN)
        assert client.health()["ok"] is True
        capabilities = client.capabilities()
        assert capabilities["ok"] is True
        assert "execute" in capabilities["capabilities"]
        assert "audit-correlation" in capabilities["capabilities"]
        assert "readme-absorb" in capabilities["capabilities"]
        assert "construct-patch" in capabilities["capabilities"]
        assert "intent-plan" in capabilities["capabilities"]
        assert "intent-execute" in capabilities["capabilities"]
        registered = {item["name"] for item in capabilities["registered"]}
        assert registered == {"files.read", "git.status"}


def test_wrong_token_is_rejected(tmp_path: Path) -> None:
    with running_bridge(tmp_path) as base_url:
        client = WarpClient(base_url, "wrong-token-that-is-long-enough")
        with pytest.raises(WarpClientError, match="401"):
            client.capabilities()


def test_read_only_execution_round_trip(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    marker.write_text("mamba\n", encoding="utf-8")

    with running_bridge(tmp_path) as base_url:
        client = WarpClient(base_url, TOKEN)
        result = client.execute(
            ["cat", "marker.txt"],
            request_id="bridge-round-trip-1",
        )

    assert result["ok"] is True
    assert result["request_id"] == "bridge-round-trip-1"
    assert result["stdout"] == "mamba\n"
    assert result["exit_code"] == 0
    assert result["policy_risk"] == "low"


def test_workspace_escape_is_rejected_over_bridge(tmp_path: Path) -> None:
    with running_bridge(tmp_path) as base_url:
        client = WarpClient(base_url, TOKEN)
        with pytest.raises(WarpClientError, match="403"):
            client.execute(["cat", "/etc/passwd"])


def test_stateful_execution_requires_explicit_approval(tmp_path: Path) -> None:
    with running_bridge(tmp_path) as base_url:
        client = WarpClient(base_url, TOKEN)
        with pytest.raises(WarpClientError, match="403"):
            client.execute(["python3", "-c", "print('blocked')"])


def test_readme_absorption_round_trip(tmp_path: Path) -> None:
    with running_bridge(tmp_path) as base_url:
        client = WarpClient(base_url, TOKEN)
        first = client.absorb_readme(
            message="add project context",
            project_name="Bridge Demo",
            confirmed=["Only explicit commands may execute actions"],
            derived=["Persistent project state is required"],
            proposed=["Add section planning later"],
        )
        assert first["ok"] is True
        assert first["triggered"] is False
        assert first["output_file"] is None

        triggered = client.absorb_readme(message="bro dame el README")

    assert triggered["ok"] is True
    assert triggered["triggered"] is True
    generated = tmp_path / "README.generated.md"
    assert generated.exists()
    text = generated.read_text(encoding="utf-8")
    assert "# Bridge Demo" in text
    assert "Only explicit commands may execute actions" in text
    assert "Persistent project state is required" in text
    assert "Add section planning later" in text


def test_construct_round_trip_over_bridge(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    patch = """diff --git a/bridge.txt b/bridge.txt
new file mode 100644
--- /dev/null
+++ b/bridge.txt
@@ -0,0 +1 @@
+bridge
"""

    with running_bridge(tmp_path) as base_url:
        client = WarpClient(base_url, TOKEN)
        result = client.construct(
            message="constrúyelo",
            objective="create a bridge marker",
            patch=patch,
            checks=[["cat", "bridge.txt"]],
            task_id="bridge-construct-1",
        )

    assert result["ok"] is True
    assert result["status"] == "done"
    assert (tmp_path / "bridge.txt").read_text(encoding="utf-8") == "bridge\n"
    assert "bridge.txt" in result["workspace_status"]["stdout"]


def test_structured_intent_round_trip(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    marker = tmp_path / "marker.txt"
    marker.write_text("mamba\n", encoding="utf-8")

    with running_bridge(tmp_path) as base_url:
        client = WarpClient(base_url, TOKEN)

        plan = client.plan_intent(
            "files.read",
            target="marker.txt",
            project="Bridge Demo",
            request_id="plan-read-1",
        )
        assert plan["ok"] is True
        assert plan["plan"]["capability"] == "files.read"
        assert plan["plan"]["mutates"] is False

        read_result = client.execute_intent(
            "files.read",
            target="marker.txt",
            project="Bridge Demo",
            request_id="read-round-trip-1",
        )
        assert read_result["ok"] is True
        assert read_result["evidence"]["content"] == "mamba\n"

        status_result = client.execute_intent(
            "git.status",
            target=".",
            request_id="git-status-round-trip-1",
        )
        assert status_result["ok"] is True
        assert status_result["evidence"]["worktree_dirty"] is True
        assert "marker.txt" in status_result["evidence"]["stdout"]
