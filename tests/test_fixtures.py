"""The recorded controller responses are valid, anonymised and keep the device's quirks."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
ANON_SYSID = "123456789012"


def _secret_checker() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "check_no_secrets.py"
    spec = importlib.util.spec_from_file_location("check_no_secrets", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["sysid", "state_poll", "state_full", "error"])
def test_fixture_is_valid_and_anonymised(name: str) -> None:
    """Every fixture parses and contains no identifier of a real installation."""
    text = (FIXTURES / f"{name}.json").read_text(encoding="utf-8")
    json.loads(text)
    assert _secret_checker().check_text(text, []) == []


def test_sysid_discovery_keeps_firmware_quirk() -> None:
    """The discovery answer keeps the controller's "VER:" key (trailing colon)."""
    data = _load("sysid")
    assert data["SYSID"] == ANON_SYSID
    assert data["ICON1"]["FIRMWARE"] == 1079
    assert "VER:" in data["ICON1"]


def test_full_state_has_configuration_and_poll_does_not() -> None:
    """Only the RELOAD request returns KEY, CFG and EVENTLOG."""
    full, poll = _load("state_full"), _load("state_poll")
    assert {"KEY", "CFG", "EVENTLOG"} <= full.keys()
    assert not {"KEY", "CFG", "EVENTLOG"} & poll.keys()
    assert full["KEY"] == ANON_SYSID
    assert full["INFO"]["NETL"]["MAC"] == "02:00:00:00:00:01"
    assert set(full["DP"]) == {f"1.{n}" for n in range(1, 9)}


def test_wrong_sysid_answer() -> None:
    """A wrong SYSID is answered with ERR 1."""
    assert _load("error") == {"ERR": 1}
