"""The translations stay in step with strings.json."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import pytest

COMPONENT = Path(__file__).parents[1] / "custom_components" / "ngbs_icon"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _load(name: str) -> dict[str, Any]:
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            flat |= _flatten(value, f"{path}.")
        else:
            flat[path] = value
    return flat


def test_english_is_strings_json() -> None:
    assert _load("translations/en.json") == _load("strings.json")


@pytest.mark.parametrize("language", ["hu"])
def test_translation_matches(language: str) -> None:
    source = _flatten(_load("strings.json"))
    translated = _flatten(_load(f"translations/{language}.json"))
    assert translated.keys() == source.keys()
    for key, text in source.items():
        expected = set(PLACEHOLDER.findall(text))
        assert set(PLACEHOLDER.findall(translated[key])) == expected, key
