"""The command line tool against a simulated controller."""

from __future__ import annotations

import ipaddress
import json
from typing import Self

from icon_test_support import (
    SYSID,
    WRONG_SYSID,
    FakeIconServer,
    SimulatedController,
    load,
)
import pytest

from pyngbsicon import cli, parse_state


def run(server: FakeIconServer, *args: str) -> list[str]:
    """Build the argument list for a command that talks to the fake server."""
    command, *rest = args
    return [command, "127.0.0.1", "--port", str(server.port), "--timeout", "2", *rest]


def test_status_text(
    threaded_server: FakeIconServer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(run(threaded_server, "status")) == 0
    out = capsys.readouterr().out
    assert f"SYSID {SYSID}" in out and "cooling, ECO on" in out
    assert "1.1 Living room" in out and "H/C master" in out
    assert "R9 R1.COOL" in out and "cooling_changeover  ON" in out
    assert "1.6 Kids room" not in out  # not configured


def test_status_json(
    threaded_server: FakeIconServer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(run(threaded_server, "status", "--json")) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["sysid"] == SYSID
    assert data["hc_mode"] == 1 and data["hc_master"] == "H1.1"
    assert data["thermostats"]["1.1"]["setpoints"]["eco_cool"] == 30
    assert data["controllers"]["1"]["relays"]["R0"]["driven_by"] == ["I1.5"]
    assert "raw" not in data and "KEY" not in json.dumps(data)


def test_status_shows_problems_and_offline(
    threaded_server: FakeIconServer,
    controller: SimulatedController,
    capsys: pytest.CaptureFixture[str],
) -> None:
    controller.full.update(ERR=1, OVERHEAT=1)
    controller.full["DP"]["1.2"]["LIVE"] = 0
    cli.main(run(threaded_server, "status"))
    out = capsys.readouterr().out
    assert "! FAULT, OVERHEAT" in out
    assert "1.2 Kitchen        offline" in out


def test_set_eco_lock_mode(
    threaded_server: FakeIconServer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        cli.main(
            run(threaded_server, "set", "1.2", "--heat", "21", "--eco-heat", "18.5")
        )
        == 0
    )
    assert "heat 21.0" in capsys.readouterr().out
    assert (
        cli.main(run(threaded_server, "set", "1.2", "--cool", "29", "--no-confirm"))
        == 0
    )
    assert cli.main(run(threaded_server, "eco", "off", "--thermostat", "1.5")) == 0
    assert "1.5 Office" in capsys.readouterr().out
    assert cli.main(run(threaded_server, "eco", "on")) == 0
    assert "ECO on" in capsys.readouterr().out
    assert cli.main(run(threaded_server, "lock", "1.5", "on")) == 0
    assert "locked" in capsys.readouterr().out
    assert cli.main(run(threaded_server, "mode", "heating")) == 0
    assert "heating" in capsys.readouterr().out


def test_raw_adds_sysid_and_hides_key(
    threaded_server: FakeIconServer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(run(threaded_server, "raw", '{"RELOAD": ""}')) == 0
    data = json.loads(capsys.readouterr().out)
    assert "CFG" in data and "KEY" not in data
    assert threaded_server.requests[-1] == {"SYSID": SYSID, "RELOAD": ""}

    assert cli.main(run(threaded_server, "raw", '{"RELOAD": 6}')) == 0
    assert threaded_server.requests[-1] == {"RELOAD": 6}

    assert cli.main(run(threaded_server, "raw", "[1]")) == 2


def test_restart_needs_confirmation(
    threaded_server: FakeIconServer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(run(threaded_server, "restart")) == 2
    assert cli.main(run(threaded_server, "restart", "--yes")) == 0
    assert threaded_server.requests[-1] == {"SYSID": SYSID, "RELOAD": 8}


def test_scan(
    threaded_server: FakeIconServer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["scan", "127.0.0.1/32", "--port", str(threaded_server.port)]) == 0
    assert (
        f"127.0.0.1  SYSID {SYSID}, firmware 1079, 1 controller(s)"
        in capsys.readouterr().out
    )
    assert (
        cli.main(
            ["scan", "127.0.0.1/32", "--port", str(threaded_server.port), "--json"]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)[0]["sysid"] == SYSID


def test_scan_reports_old_firmware_and_nothing_found(
    threaded_server: FakeIconServer,
    controller: SimulatedController,
    capsys: pytest.CaptureFixture[str],
) -> None:
    controller.firmware_reveals_sysid = False
    cli.main(["scan", "127.0.0.1/32", "--port", str(threaded_server.port)])
    assert "too old to reveal the SYSID" in capsys.readouterr().out
    cli.main(["scan", "127.0.0.1/32", "--port", "1"])
    assert "No iCON controller found" in capsys.readouterr().out


def test_local_network(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSocket:
        def __init__(self, *args: object) -> None:
            self.target: object = None

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def connect(self, target: object) -> None:
            self.target = (
                target  # a UDP connect sends nothing; it only picks the interface
            )

        def getsockname(self) -> tuple[str, int]:
            return ("192.0.2.77", 40000)

    monkeypatch.setattr(cli.socket, "socket", FakeSocket)
    assert str(cli._local_network()) == "192.0.2.0/24"


def test_scan_default_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[object] = []

    async def fake_discover(networks: list[object], **kwargs: object) -> list[object]:
        seen.extend(networks)
        return []

    monkeypatch.setattr(
        cli, "_local_network", lambda: ipaddress.IPv4Network("192.0.2.0/24")
    )
    monkeypatch.setattr(cli, "discover", fake_discover)
    assert cli.main(["scan"]) == 0
    assert [str(network) for network in seen] == ["192.0.2.0/24"]
    assert "No iCON controller found in 192.0.2.0/24" in capsys.readouterr().out


def test_errors(
    threaded_server: FakeIconServer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(run(threaded_server, "status", "--sysid", WRONG_SYSID)) == 1
    assert "rejected SYSID" in capsys.readouterr().err
    assert cli.main(run(threaded_server, "set", "1.2", "--heat", "21.3")) == 2
    assert "multiple of 0.5" in capsys.readouterr().err
    assert cli.main(["--debug", *run(threaded_server, "status")]) == 0


def test_raw_with_given_sysid(
    threaded_server: FakeIconServer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(run(threaded_server, "raw", "{}", "--sysid", SYSID)) == 0
    assert threaded_server.requests == [{"SYSID": SYSID}]


def test_describe_without_configuration() -> None:
    text = cli._describe(parse_state(load("state_poll")))
    assert "switched by" not in text  # masters are only known with the configuration
    assert "Controller" not in text  # no relay data either
    assert "iCON system" in text
