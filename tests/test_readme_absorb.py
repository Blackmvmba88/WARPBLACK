from __future__ import annotations

import json
from pathlib import Path

import pytest

from warpblack.readme_absorb import ReadmeAbsorber, has_readme_trigger


def test_magic_phrase_is_case_and_punctuation_tolerant() -> None:
    assert has_readme_trigger("bro, DAME EL README!!!") is True
    assert has_readme_trigger("dame el read-me") is True
    assert has_readme_trigger("solo guarda contexto") is False


def test_incremental_absorption_does_not_materialize_without_trigger(tmp_path: Path) -> None:
    absorber = ReadmeAbsorber(tmp_path)
    result = absorber.ingest(
        message="añade FFT",
        project_name="MEngine",
        confirmed=["Live microphone input", "FFT"],
        derived=["Audio buffering is required"],
        proposed=["Consider AudioWorklet"],
    )

    assert result.triggered is False
    assert result.output_file is None
    assert not (tmp_path / "README.generated.md").exists()

    state = json.loads((tmp_path / ".warpblack/readme_state.json").read_text())
    assert state["project_name"] == "MEngine"
    assert state["confirmed"] == ["Live microphone input", "FFT"]
    assert state["derived"] == ["Audio buffering is required"]
    assert state["proposed"] == ["Consider AudioWorklet"]


def test_trigger_materializes_readme_with_provenance_boundaries(tmp_path: Path) -> None:
    absorber = ReadmeAbsorber(tmp_path)
    absorber.ingest(
        message="primera interacción",
        project_name="Bridge Demo",
        confirmed=["The bridge acts only on explicit commands"],
        derived=["A persistent project state is required"],
        proposed=["Add a richer section planner later"],
    )

    result = absorber.ingest(message="dame el README")

    assert result.triggered is True
    readme = (tmp_path / "README.generated.md").read_text(encoding="utf-8")
    assert "# Bridge Demo" in readme
    assert "## Confirmed Facts" in readme
    assert "The bridge acts only on explicit commands" in readme
    assert "## Derived Architecture" in readme
    assert "A persistent project state is required" in readme
    assert "## Proposed / Unconfirmed" in readme
    assert "Add a richer section planner later" in readme
    assert "does not execute shell commands" in readme


def test_absorption_deduplicates_semantically_equivalent_items(tmp_path: Path) -> None:
    absorber = ReadmeAbsorber(tmp_path)
    absorber.ingest(
        message="uno",
        confirmed=["FFT", "fft", "  FFT  "],
    )
    state = absorber.load()
    assert state["confirmed"] == ["FFT"]


def test_paths_cannot_escape_workspace(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inside workspace"):
        ReadmeAbsorber(tmp_path, output_file="../README.md")
