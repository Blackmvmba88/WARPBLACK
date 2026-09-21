from __future__ import annotations

import json
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class WarpClientError(RuntimeError):
    pass


class WarpClient:
    def __init__(self, base_url: str, token: str, *, timeout_s: float = 70.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_s = timeout_s

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/v1/health", authenticated=False)

    def capabilities(self) -> dict[str, Any]:
        return self._request("GET", "/v1/capabilities", authenticated=True)

    def execute(
        self,
        argv: Sequence[str],
        *,
        cwd: str = ".",
        timeout_s: float = 60.0,
        approved: bool = False,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if not argv:
            raise ValueError("argv must not be empty")
        payload: dict[str, Any] = {
            "argv": list(argv),
            "cwd": cwd,
            "timeout_s": timeout_s,
            "approved": approved,
        }
        if request_id is not None:
            payload["request_id"] = request_id
        return self._request(
            "POST",
            "/v1/execute",
            authenticated=True,
            payload=payload,
        )

    def absorb_readme(
        self,
        *,
        message: str,
        project_name: str | None = None,
        confirmed: Sequence[str] = (),
        derived: Sequence[str] = (),
        proposed: Sequence[str] = (),
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "message": message,
            "confirmed": list(confirmed),
            "derived": list(derived),
            "proposed": list(proposed),
        }
        if project_name is not None:
            payload["project_name"] = project_name
        return self._request(
            "POST",
            "/v1/readme/absorb",
            authenticated=True,
            payload=payload,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if authenticated:
            headers["Authorization"] = f"Bearer {self.token}"

        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                error_payload = json.loads(raw)
                message = str(error_payload.get("error", raw))
            except json.JSONDecodeError:
                message = raw or str(exc)
            raise WarpClientError(f"bridge returned HTTP {exc.code}: {message}") from exc
        except URLError as exc:
            raise WarpClientError(f"bridge unavailable: {exc.reason}") from exc
