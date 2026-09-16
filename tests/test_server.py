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
