"""Context-aware routine learning for WARPBLACK.

This module learns repeatable workflows from *semantic activity events* rather
than blindly replaying raw mouse coordinates. It is intentionally execution-free:
it produces a routine plan that WARPBLACK can later execute through bounded
capabilities.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class Context:
    app: str
    window_title: str = ""
    project: str | None = None
    site: str | None = None


@dataclass(frozen=True)
class SemanticEvent:
    action: str
    context: Context
    target: str | None = None
    artifact: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoutineStep:
    action: str
    target: str | None = None
    artifact_role: str | None = None
    context_app: str | None = None
    context_site: str | None = None


@dataclass(frozen=True)
class Routine:
    name: str
    trigger: str
    steps: tuple[RoutineStep, ...]
    requires_confirmation: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "trigger": self.trigger,
            "requires_confirmation": self.requires_confirmation,
            "steps": [asdict(step) for step in self.steps],
        }


_ARTIFACT_ACTIONS = {
    "download": "current_artifact",
    "export": "current_artifact",
    "save": "current_artifact",
    "render": "current_artifact",
}


class RoutineLearner:
    """Convert a trace into a portable semantic routine.

    The learner replaces concrete output file paths with artifact roles so a
    future replay operates on the file created in *that* run.
    """

    def learn(self, name: str, trigger: str, events: Iterable[SemanticEvent]) -> Routine:
        steps: list[RoutineStep] = []
        current_artifact_seen = False

        for event in events:
            artifact_role: str | None = None
            if event.action in _ARTIFACT_ACTIONS:
                current_artifact_seen = True
                artifact_role = _ARTIFACT_ACTIONS[event.action]
            elif event.action in {"upload", "attach", "publish", "distribute"} and current_artifact_seen:
                artifact_role = "current_artifact"

            step = RoutineStep(
                action=event.action,
                target=event.target,
                artifact_role=artifact_role,
                context_app=event.context.app or None,
                context_site=event.context.site,
            )

            # Collapse exact consecutive duplicates. Repeated navigation noise
            # should not become part of the learned procedure.
            if steps and step == steps[-1]:
                continue
            steps.append(step)

        if not steps:
            raise ValueError("cannot learn an empty routine")

        return Routine(name=name, trigger=trigger, steps=tuple(steps))


def music_publish_example() -> Routine:
    """Reference workflow: generator -> download -> distributor upload."""
    learner = RoutineLearner()
    return learner.learn(
        "music_publish",
        "cuando termine una canción, prepara la publicación",
        [
            SemanticEvent(
                "download",
                Context(app="browser", site="music-generator"),
                target="download audio",
                artifact="song.wav",
            ),
            SemanticEvent(
                "open",
                Context(app="browser", site="distributor"),
                target="new release",
            ),
            SemanticEvent(
                "upload",
                Context(app="browser", site="distributor"),
                target="audio file",
                artifact="song.wav",
            ),
        ],
    )


def image_publish_example() -> Routine:
    """Reference workflow: image tool -> export -> destination upload."""
    learner = RoutineLearner()
    return learner.learn(
        "image_publish",
        "cuando termine una imagen, prepara la subida",
        [
            SemanticEvent(
                "export",
                Context(app="browser", site="image-tool"),
                target="final image",
                artifact="cover.png",
            ),
            SemanticEvent(
                "open",
                Context(app="browser", site="destination"),
                target="upload",
            ),
            SemanticEvent(
                "upload",
                Context(app="browser", site="destination"),
                target="image file",
                artifact="cover.png",
            ),
        ],
    )
