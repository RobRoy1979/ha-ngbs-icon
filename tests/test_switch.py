"""Switch entities."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from .conftest import make_state, setup_integration

ECO = "switch.home_eco_mode"


@pytest.fixture
def platforms() -> list[Platform]:
    """Only the switch platform."""
    return [Platform.SWITCH]


@pytest.mark.usefixtures("mock_client")
async def test_entities(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await setup_integration(hass, config_entry)
    await snapshot_platform(hass, entity_registry, snapshot, config_entry.entry_id)
    # No relay is configured as the switched output.
    assert hass.states.get("switch.home_switched_output") is None


async def test_system_eco(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    client = mock_client.return_value
    for service, on in ((SERVICE_TURN_OFF, False), (SERVICE_TURN_ON, True)):
        await hass.services.async_call(
            SWITCH_DOMAIN, service, {ATTR_ENTITY_ID: ECO}, blocking=True
        )
        client.set_eco.assert_awaited_with(on)


def _switched_output(raw: dict[str, Any]) -> None:
    raw["CFG"]["ICON1"]["RELAY"]["R7"]["FUNC"] = "S1.8"
    raw["SW"] = 1


async def test_switched_output(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.return_value.get_state.return_value = make_state(_switched_output)
    await setup_integration(hass, config_entry)
    state = hass.states.get("switch.home_switched_output")
    assert state is not None and state.state == STATE_ON
    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: "switch.home_switched_output"},
        blocking=True,
    )
    mock_client.return_value.set_switched_output.assert_awaited_once_with(False)
