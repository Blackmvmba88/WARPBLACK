from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .construct import PatchConstructor, ConstructResult
from .readme_absorb import AbsorbResult, ReadmeAbsorber


@dataclass(frozen=True)
class ReadmeHandoffResult:
    absorb: AbsorbResult
    construct: ConstructResult | None


class ReadmeHandoff:
    def __init__(self, workspace_root: str | Path) -> None:
        root = Path(workspace_root).resolve()
        self.absorber = ReadmeAbsorber(root)
        self.constructor = PatchConstructor(root, absorber=self.absorber)

    def run(
        self,
        *,
        message: str,
        objective: str,
        patch: str,
        checks: Sequence[Sequence[str]] = (),
        task_id: str | None = None,
        approved: bool = False,
    ) -> ReadmeHandoffResult:
        absorb = self.absorber.ingest(message=message)
        if not absorb.triggered:
            return ReadmeHandoffResult(absorb=absorb, construct=None)
        construct = self.constructor.construct(
            message="construyelo",
            objective=objective,
            patch=patch,
            checks=checks,
            task_id=task_id,
            approved=approved,
        )
        return ReadmeHandoffResult(absorb=absorb, construct=construct)
