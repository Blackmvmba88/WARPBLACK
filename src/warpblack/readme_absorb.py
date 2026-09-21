from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import unicodedata
from typing import Iterable


TRIGGER_PHRASES = ("dame el readme", "dame el read me")
SCHEMA_VERSION = 1


def _normalized_text(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value)
    asciiish = "".join(ch for ch in folded if not unicodedata.combining(ch))
    lowered = asciiish.casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", lowered).split())


def has_readme_trigger(message: str) -> bool:
    """Return True when the magic phrase appears in the incoming message."""
    normalized = _normalized_text(message)
    return any(phrase in normalized for phrase in TRIGGER_PHRASES)


def _append_unique(target: list[str], values: Iterable[str]) -> None:
    seen = {_normalized_text(item) for item in target}
    for value in values:
        clean = value.strip()
        key = _normalized_text(clean)
        if not clean or not key or key in seen:
            continue
        target.append(clean)
        seen.add(key)


@dataclass(frozen=True)
class AbsorbResult:
    triggered: bool
    state_file: str
    output_file: str | None
    confirmed_count: int
    derived_count: int
    proposed_count: int
    interaction_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "triggered": self.triggered,
            "state_file": self.state_file,
            "output_file": self.output_file,
            "counts": {
                "confirmed": self.confirmed_count,
                "derived": self.derived_count,
                "proposed": self.proposed_count,
                "interactions": self.interaction_count,
            },
        }


class ReadmeAbsorber:
    """Incremental project-memory layer for WARPBLACK.

    WARPBLACK itself does not decide what is fact, derived, or proposed. The caller
    supplies those classifications. The magic phrase only causes materialization.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        state_file: str | Path = ".warpblack/readme_state.json",
        output_file: str | Path = "README.generated.md",
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.state_path = self._inside_workspace(state_file)
        self.output_path = self._inside_workspace(output_file)

    def _inside_workspace(self, value: str | Path) -> Path:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        candidate = candidate.resolve()
        try:
            candidate.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError("README absorber paths must stay inside workspace") from exc
        return candidate

    def _new_state(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "project_name": self.workspace_root.name,
            "confirmed": [],
            "derived": [],
            "proposed": [],
            "interactions": [],
        }

    def load(self) -> dict[str, object]:
        if not self.state_path.exists():
            return self._new_state()

        raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("README absorber state must be a JSON object")
        if raw.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported README absorber state schema")

        expected_lists = ("confirmed", "derived", "proposed", "interactions")
        for key in expected_lists:
            value = raw.get(key)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"README absorber state field {key!r} must be a list of strings")

        project_name = raw.get("project_name")
        if not isinstance(project_name, str) or not project_name.strip():
            raise ValueError("README absorber state project_name must be a non-empty string")
        return raw

    def _save(self, state: dict[str, object]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        self.state_path.write_text(encoded, encoding="utf-8")

    def ingest(
        self,
        *,
        message: str,
        project_name: str | None = None,
        confirmed: Iterable[str] = (),
        derived: Iterable[str] = (),
        proposed: Iterable[str] = (),
    ) -> AbsorbResult:
        if not isinstance(message, str):
            raise TypeError("message must be a string")

        state = self.load()
        if project_name is not None:
            clean_project = project_name.strip()
            if not clean_project:
                raise ValueError("project_name must not be empty")
            state["project_name"] = clean_project

        _append_unique(state["confirmed"], confirmed)  # type: ignore[arg-type]
        _append_unique(state["derived"], derived)  # type: ignore[arg-type]
        _append_unique(state["proposed"], proposed)  # type: ignore[arg-type]

        clean_message = message.strip()
        if clean_message:
            interactions = state["interactions"]
            assert isinstance(interactions, list)
            interactions.append(clean_message)

        self._save(state)

        triggered = has_readme_trigger(message)
        output_file: str | None = None
        if triggered:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self.output_path.write_text(self.render(state), encoding="utf-8")
            output_file = str(self.output_path)

        return AbsorbResult(
            triggered=triggered,
            state_file=str(self.state_path),
            output_file=output_file,
            confirmed_count=len(state["confirmed"]),
            derived_count=len(state["derived"]),
            proposed_count=len(state["proposed"]),
            interaction_count=len(state["interactions"]),
        )

    def render(self, state: dict[str, object] | None = None) -> str:
        current = state or self.load()
        project_name = str(current["project_name"])
        confirmed = current["confirmed"]
        derived = current["derived"]
        proposed = current["proposed"]
        assert isinstance(confirmed, list)
        assert isinstance(derived, list)
        assert isinstance(proposed, list)

        def section(title: str, items: list[str], empty: str) -> str:
            body = "\n".join(f"- {item}" for item in items) if items else f"- {empty}"
            return f"## {title}\n\n{body}\n"

        parts = [
            f"# {project_name}\n",
            (
                "> Generated incrementally by WARPBLACK README Absorber. "
                "Confirmed, derived, and proposed information remain explicitly separated.\n"
            ),
            section("Confirmed Facts", confirmed, "No confirmed facts captured yet."),
            section("Derived Architecture", derived, "No derived architecture captured yet."),
            section("Proposed / Unconfirmed", proposed, "No proposals captured yet."),
            (
                "## Execution Contract\n\n"
                "- `dame el README` materializes project memory into this document.\n"
                "- Absorption alone does not execute shell commands or modify application code.\n"
                "- Build, test, review, publish, push, or merge require separate explicit commands.\n"
                "- Proposed items never become confirmed facts automatically.\n"
            ),
        ]
        return "\n".join(parts).rstrip() + "\n"
