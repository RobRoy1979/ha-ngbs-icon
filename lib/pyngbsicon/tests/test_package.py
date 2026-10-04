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
