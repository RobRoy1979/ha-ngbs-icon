"""The system mode select."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

import pyngbsicon

from .conftest import make_state, setup_integration

MODE = "select.home_system_mode"


@pytest.fixture
def platforms() -> list[Platform]:
    """Only the select platform."""
    return [Platform.SELECT]


@pytest.mark.usefixtures("mock_client")
async def test_entities(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await setup_integration(hass, config_entry)
    await snapshot_platform(hass, entity_registry, snapshot, config_entry.entry_id)


async def test_select_mode(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    client = mock_client.return_value
    client.set_hc_mode.return_value = make_state(HC=0, dp={"1.1": {"HC": 0}})
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: MODE, ATTR_OPTION: "heating"},
        blocking=True,
    )
    client.set_hc_mode.assert_awaited_once_with(pyngbsicon.HeatCool.HEATING)
    state = hass.states.get(MODE)
    assert state is not None and state.state == "heating"


async def test_external_changeover(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.return_value.get_state.return_value = make_state(
        cfg={"HCMASTER": "I1.4"}
    )
    await setup_integration(hass, config_entry)
    assert hass.states.get(MODE) is None


async def test_changeover_moves_to_an_input(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    mock_client.return_value.get_state.return_value = make_state(
        cfg={"HCMASTER": "I1.4"}
    )
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(MODE)
    assert state is not None and state.state == STATE_UNAVAILABLE
