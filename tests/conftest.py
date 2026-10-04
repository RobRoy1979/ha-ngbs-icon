"""Fixtures for the integration tests.

The integration is tested against the pyngbsicon API: the client is replaced by a mock
that answers with models parsed from the recorded (anonymised) controller responses.
"""

from __future__ import annotations

from collections.abc import Generator
import copy
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_HOST, CONF_MAC, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ngbs_icon.const import CONF_SYSID, DOMAIN
import pyngbsicon

FIXTURES = Path(__file__).parents[1] / "lib" / "pyngbsicon" / "tests" / "fixtures"
SYSID = "123456789012"
HOST = "192.0.2.10"
MAC = "02:00:00:00:00:01"
DHCP_MAC = "020000000001"  # allow-secret: MAC above in DHCP form
OTHER_SYSID = "123456780000"  # allow-secret: a second, made-up system
WRONG_SYSID = "999999990000"  # allow-secret: rejected by the controller


def load_raw(name: str = "state_full") -> dict[str, Any]:
    """A recorded controller answer."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def make_state(**changes: Any) -> pyngbsicon.IconSystem:
    """The recorded system, optionally with top-level or thermostat changes.

    ``changes`` may contain top-level fields and ``dp={"1.1": {"TEMP": 20}}``.
    """
    raw = copy.deepcopy(load_raw())
    for thermostat_id, fields in changes.pop("dp", {}).items():
        raw["DP"][thermostat_id].update(fields)
    for key, value in changes.pop("cfg", {}).items():
        raw["CFG"][key] = value
    raw.update(changes)
    return pyngbsicon.parse_state(raw)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components."""


@pytest.fixture
def state() -> pyngbsicon.IconSystem:
    """The system state the mocked controller reports."""
    return make_state()


@pytest.fixture
def mock_client(state: pyngbsicon.IconSystem) -> Generator[MagicMock]:
    """Replace pyngbsicon.IconClient; the instance is ``mock_client.return_value``."""
    with patch("pyngbsicon.IconClient", autospec=True) as client_class:
        client = client_class.return_value
        client.get_state = AsyncMock(return_value=state)
        client.discover_sysid = AsyncMock(
            return_value=pyngbsicon.SysidInfo(
                sysid=SYSID, firmware={1: 1079}, download=0
            )
        )
        for name in (
            "set_setpoint",
            "set_setpoints",
            "set_eco",
            "set_lock",
            "set_hc_mode",
        ):
            setattr(client, name, AsyncMock(return_value=state))
        yield client_class


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Keep config flow tests from setting up the entries they create."""
    with patch(
        "custom_components.ngbs_icon.async_setup_entry", return_value=True
    ) as setup_entry:
        yield setup_entry


@pytest.fixture
def mock_discover() -> Generator[AsyncMock]:
    """Replace the network scan; returns nothing unless the test sets results."""
    with patch(
        "custom_components.ngbs_icon.config_flow.async_scan", new_callable=AsyncMock
    ) as scan:
        scan.return_value = []
        yield scan


@pytest.fixture
def mock_probe() -> Generator[AsyncMock]:
    """Replace the single-host probe used by DHCP discovery."""
    with patch("pyngbsicon.probe", new_callable=AsyncMock) as probe:
        probe.return_value = found()
        yield probe


def found(
    host: str = HOST, sysid: str | None = SYSID, *, needs_sysid: bool = False
) -> pyngbsicon.DiscoveredIcon:
    """A discovery result."""
    return pyngbsicon.DiscoveredIcon(
        host=host,
        sysid=None if needs_sysid else sysid,
        firmware=None if needs_sysid else 1079,
        controllers=0 if needs_sysid else 1,
        needs_sysid=needs_sysid,
    )


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A config entry of the current version."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="NGBS iCON (Home)",
        unique_id=SYSID,
        data={CONF_HOST: HOST, CONF_SYSID: SYSID, CONF_MAC: MAC},
        options={CONF_SCAN_INTERVAL: 30},
        version=2,
        minor_version=1,
    )


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add the entry and set it up."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
