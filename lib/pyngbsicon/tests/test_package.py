"""Packaging basics of pyngbsicon."""

from __future__ import annotations

from importlib import resources
import re

import pyngbsicon


def test_version_is_pep440() -> None:
    """The version string is a valid PEP 440 version."""
    assert re.fullmatch(
        r"\d+\.\d+\.\d+(?:\.dev\d+|(?:a|b|rc)\d+)?", pyngbsicon.__version__
    )


def test_package_is_typed() -> None:
    """The package ships a py.typed marker (PEP 561)."""
    assert resources.files("pyngbsicon").joinpath("py.typed").is_file()


def test_sdist_never_ships_raw_captures() -> None:
    """Unredacted captures stay out of the source distribution."""
    import tomllib
    from pathlib import Path

    config = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    sdist = config["tool"]["hatch"]["build"]["targets"]["sdist"]
    assert "tests/fixtures/raw" in sdist["exclude"]
