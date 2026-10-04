"""Diagnostics."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator
from syrupy.assertion import SnapshotAssertion
from syrupy.filters import props

import pyngbsicon

from .conftest import HOST, MAC, SYSID, load_raw, setup_integration


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    snapshot: SnapshotAssertion,
) -> None:
    await setup_integration(hass, config_entry)
    result = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)
    assert result == snapshot(exclude=props("last_duration_ms"))
    text = str(result)
    for secret in (SYSID, HOST, MAC, "Home"):
        assert secret not in text, secret


async def test_diagnostics_when_the_controller_does_not_answer(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
) -> None:
    await setup_integration(hass, config_entry)
    mock_client.return_value.get_state.side_effect = pyngbsicon.IconConnectionError(
        f"cannot connect to {HOST}:7992: refused"
    )
    await config_entry.runtime_data.async_refresh()
    result = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)
    statistics = result["coordinator"]["statistics"]
    assert statistics["failures"] == 1
    assert statistics["last_error"] == (
        "IconConnectionError: cannot connect to **REDACTED**:7992: refused"
    )
    assert statistics["diagnostics_read_error"].startswith("IconConnectionError")
    assert HOST not in str(result)
    assert result["system"]["thermostats"] == ["1.1", "1.2", "1.3", "1.4", "1.5"]


async def test_diagnostics_after_a_write(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
) -> None:
    """A write publishes a state without the configuration; that is shown as is."""
    await setup_integration(hass, config_entry)
    without_config = pyngbsicon.parse_state(load_raw("state_poll"))
    config_entry.runtime_data.async_set_updated_data(without_config)
    mock_client.return_value.get_state.side_effect = pyngbsicon.IconConnectionError("x")
    result = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)
    assert "CFG" not in result["state"]
    assert result["state"]["SYSID"] == "**REDACTED**"
