from __future__ import annotations

from typing import Any

import pytest

from warpblack.xarvis import PROTOCOL, XarvisAdapter, XarvisProtocolError


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def health(self) -> dict[str, Any]:
        self.calls.append(("health", {}))
        return {"ok": True, "status": "alive"}

    def capabilities(self) -> dict[str, Any]:
        self.calls.append(("capabilities", {}))
        return {"ok": True, "capabilities": ["execute"]}

    def execute(self, argv: list[str], **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("execute", {"argv": argv, **kwargs}))
        return {
            "ok": True,
            "request_id": kwargs.get("request_id") or "generated-id",
            "argv": argv,
            "exit_code": 0,
        }


def test_execute_maps_xarvis_envelope_to_warp_client() -> None:
    client = FakeClient()
    adapter = XarvisAdapter(client)  # type: ignore[arg-type]

    response = adapter.handle(
        {
            "protocol": PROTOCOL,
            "action": "terminal.execute",
            "argv": ["git", "status"],
            "cwd": ".",
            "timeout_s": 30,
            "request_id": "xarvis-1",
        }
    )

    assert response["ok"] is True
    assert response["request_id"] == "xarvis-1"
    assert client.calls == [
        (
            "execute",
            {
                "argv": ["git", "status"],
                "cwd": ".",
                "timeout_s": 30.0,
                "approved": False,
                "request_id": "xarvis-1",
            },
        )
    ]


def test_payload_cannot_self_approve() -> None:
    adapter = XarvisAdapter(FakeClient())  # type: ignore[arg-type]

    with pytest.raises(XarvisProtocolError, match="out-of-band"):
        adapter.handle(
            {
                "protocol": PROTOCOL,
                "action": "terminal.execute",
                "argv": ["python3", "-c", "print('hi')"],
                "approved": True,
            }
        )


def test_trusted_caller_can_supply_out_of_band_approval() -> None:
    client = FakeClient()
    adapter = XarvisAdapter(client)  # type: ignore[arg-type]

    adapter.handle(
        {
            "protocol": PROTOCOL,
            "action": "terminal.execute",
            "argv": ["python3", "-c", "print('hi')"],
        },
        approved=True,
    )

    assert client.calls[0][1]["approved"] is True


def test_health_and_capabilities_are_read_only_actions() -> None:
    client = FakeClient()
    adapter = XarvisAdapter(client)  # type: ignore[arg-type]

    health = adapter.handle({"protocol": PROTOCOL, "action": "terminal.health"})
    capabilities = adapter.handle(
        {"protocol": PROTOCOL, "action": "terminal.capabilities"}
    )

    assert health["ok"] is True
    assert capabilities["ok"] is True
    assert [name for name, _ in client.calls] == ["health", "capabilities"]


def test_unknown_protocol_or_action_is_rejected() -> None:
    adapter = XarvisAdapter(FakeClient())  # type: ignore[arg-type]

    with pytest.raises(XarvisProtocolError, match="unsupported protocol"):
        adapter.handle({"protocol": "future-v99", "action": "terminal.health"})

    with pytest.raises(XarvisProtocolError, match="unsupported action"):
        adapter.handle({"protocol": PROTOCOL, "action": "terminal.destroy-world"})


def test_execute_validates_argv_and_timeout() -> None:
    adapter = XarvisAdapter(FakeClient())  # type: ignore[arg-type]

    with pytest.raises(XarvisProtocolError, match="argv"):
        adapter.handle({"protocol": PROTOCOL, "action": "terminal.execute", "argv": []})

    with pytest.raises(XarvisProtocolError, match="timeout_s"):
        adapter.handle(
            {
                "protocol": PROTOCOL,
                "action": "terminal.execute",
                "argv": ["git", "status"],
                "timeout_s": 0,
            }
        )
