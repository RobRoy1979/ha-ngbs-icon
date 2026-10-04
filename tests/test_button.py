"""The restart button."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

import pyngbsicon

from .conftest import setup_integration

RESTART = "button.home_restart"


@pytest.fixture
def platforms() -> list[Platform]:
    """Only the button platform."""
    return [Platform.BUTTON]


@pytest.mark.usefixtures("mock_client")
async def test_entities(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await setup_integration(hass, config_entry)
    await snapshot_platform(hass, entity_registry, snapshot, config_entry.entry_id)


async def test_restart(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: RESTART}, blocking=True
    )
    mock_client.return_value.restart.assert_awaited_once()

    mock_client.return_value.restart.side_effect = pyngbsicon.IconConnectionError("x")
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: RESTART}, blocking=True
        )
    assert err.value.translation_key == "write_failed"
