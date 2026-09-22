from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


DEFAULT_PROJECTS_FILE = "~/.warpblack/projects.json"
PROJECT_MARKERS = (
    ".git",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "Makefile",
)


class ProjectRegistryError(RuntimeError):
    pass


@dataclass
class ProjectEntry:
    id: str
    name: str
    path: str
    order: int
    group: str | None = None
    status: str = "active"
    kind: str = "folder"
    added_at: str = ""
    last_seen_at: str = ""
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectEntry":
        return cls(
            id=str(payload["id"]),
            name=str(payload["name"]),
            path=str(payload["path"]),
            order=int(payload["order"]),
            group=payload.get("group"),
            status=str(payload.get("status", "active")),
            kind=str(payload.get("kind", "folder")),
            added_at=str(payload.get("added_at", "")),
            last_seen_at=str(payload.get("last_seen_at", "")),
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        )


class ProjectRegistry:
    """Persistent logical project ordering independent of filesystem layout."""

    def __init__(self, state_file: str | Path = DEFAULT_PROJECTS_FILE) -> None:
        self.state_file = Path(state_file).expanduser()
        self._entries: list[ProjectEntry] = []
        self._load()

    @property
    def entries(self) -> tuple[ProjectEntry, ...]:
        return tuple(sorted(self._entries, key=lambda item: item.order))

    def add(
        self,
        path: str | Path,
        *,
        name: str | None = None,
        group: str | None = None,
        status: str = "active",
        position: int | None = None,
    ) -> ProjectEntry:
        resolved = Path(path).expanduser().resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise ProjectRegistryError(f"project folder does not exist: {resolved}")

        existing = self._find_by_path(resolved)
        now = _utc_now()
        metadata = _inspect_project(resolved)

        if existing is not None:
            existing.name = name or existing.name
            existing.group = group if group is not None else existing.group
            existing.status = status or existing.status
            existing.last_seen_at = now
            existing.kind = metadata["kind"]
            existing.metadata = metadata
            if position is not None:
                self.move(existing.id, position)
            else:
                self._save()
            return existing

        entry = ProjectEntry(
            id=_project_id(resolved),
            name=name or resolved.name,
            path=str(resolved),
            order=len(self._entries),
            group=group,
            status=status,
            kind=metadata["kind"],
            added_at=now,
            last_seen_at=now,
            metadata=metadata,
        )
        self._entries.append(entry)
        if position is not None:
            self._reorder(entry.id, position)
        else:
            self._normalize_order()
        self._save()
        return entry

    def scan(
        self,
        root: str | Path,
        *,
        max_depth: int = 2,
        group: str | None = None,
    ) -> list[ProjectEntry]:
        root_path = Path(root).expanduser().resolve()
        if not root_path.exists() or not root_path.is_dir():
            raise ProjectRegistryError(f"scan root does not exist: {root_path}")
        if max_depth < 0:
            raise ProjectRegistryError("max_depth must be >= 0")

        found: list[ProjectEntry] = []
        for path in _discover_projects(root_path, max_depth=max_depth):
            before = self._find_by_path(path)
            entry = self.add(path, group=group)
            if before is None:
                found.append(entry)
        return found

    def move(self, project: str, position: int) -> ProjectEntry:
        entry = self.get(project)
        self._reorder(entry.id, position)
        self._save()
        return entry

    def remove(self, project: str) -> ProjectEntry:
        entry = self.get(project)
        self._entries = [item for item in self._entries if item.id != entry.id]
        self._normalize_order()
        self._save()
        return entry

    def refresh(self, project: str | None = None) -> list[ProjectEntry]:
        targets = [self.get(project)] if project else list(self._entries)
        now = _utc_now()
        for entry in targets:
            path = Path(entry.path)
            if path.exists() and path.is_dir():
                metadata = _inspect_project(path)
                entry.last_seen_at = now
                entry.kind = metadata["kind"]
                entry.metadata = metadata
            else:
                entry.status = "missing"
        self._save()
        return targets

    def get(self, project: str) -> ProjectEntry:
        exact = [item for item in self._entries if item.id == project]
        if exact:
            return exact[0]

        lowered = project.casefold()
        by_name = [item for item in self._entries if item.name.casefold() == lowered]
        if len(by_name) == 1:
            return by_name[0]
        if len(by_name) > 1:
            raise ProjectRegistryError(f"project name is ambiguous: {project}")

        path = Path(project).expanduser()
        if path.exists():
            resolved = path.resolve()
            existing = self._find_by_path(resolved)
            if existing is not None:
                return existing

        raise ProjectRegistryError(f"unknown project: {project}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "projects": [asdict(item) for item in self.entries],
        }

    def _find_by_path(self, path: Path) -> ProjectEntry | None:
        target = os.path.normcase(str(path))
        for entry in self._entries:
            if os.path.normcase(entry.path) == target:
                return entry
        return None

    def _reorder(self, project_id: str, position: int) -> None:
        ordered = list(self.entries)
        entry = next((item for item in ordered if item.id == project_id), None)
        if entry is None:
            raise ProjectRegistryError(f"unknown project id: {project_id}")
        ordered.remove(entry)

        bounded = max(0, min(position, len(ordered)))
        ordered.insert(bounded, entry)
        self._entries = ordered
        self._normalize_order()

    def _normalize_order(self) -> None:
        self._entries.sort(key=lambda item: item.order)
        for index, entry in enumerate(self._entries):
            entry.order = index

    def _load(self) -> None:
        if not self.state_file.exists():
            return
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectRegistryError(f"cannot read project registry: {exc}") from exc

        raw = payload.get("projects", []) if isinstance(payload, dict) else []
        if not isinstance(raw, list):
            raise ProjectRegistryError("invalid project registry format")
        self._entries = [
            ProjectEntry.from_dict(item)
            for item in raw
            if isinstance(item, dict)
        ]
        self._normalize_order()

    def _save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.state_file.parent,
            prefix=".projects-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        temp_path.replace(self.state_file)


def _project_id(path: Path) -> str:
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _inspect_project(path: Path) -> dict[str, Any]:
    markers = [marker for marker in PROJECT_MARKERS if (path / marker).exists()]
    languages: list[str] = []
    if "pyproject.toml" in markers:
        languages.append("python")
    if "package.json" in markers:
        languages.append("javascript")
    if "Cargo.toml" in markers:
        languages.append("rust")
    if "go.mod" in markers:
        languages.append("go")
    if "pom.xml" in markers or "build.gradle" in markers:
        languages.append("java")

    git_dir = path / ".git"
    kind = "git" if git_dir.exists() else "project"
    return {
        "kind": kind,
        "markers": markers,
        "languages": languages,
    }


def _discover_projects(root: Path, *, max_depth: int) -> list[Path]:
    root_parts = len(root.parts)
    found: list[Path] = []
    for current, dirs, files in os.walk(root):
        path = Path(current)
        depth = len(path.parts) - root_parts
        if depth > max_depth:
            dirs[:] = []
            continue

        dirs[:] = [
            name
            for name in dirs
            if name not in {".git", ".venv", "venv", "node_modules", "__pycache__"}
            and not name.startswith(".")
        ]

        markers = set(files) | set(dirs)
        if path == root and any((path / marker).exists() for marker in PROJECT_MARKERS):
            found.append(path)
            dirs[:] = []
            continue

        if any(marker in markers for marker in PROJECT_MARKERS):
            found.append(path)
            dirs[:] = []

    return sorted(set(found), key=lambda item: str(item).casefold())
