"""The keypad lock."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.components.lock import (
    DOMAIN as LOCK_DOMAIN,
    SERVICE_LOCK,
    SERVICE_UNLOCK,
    LockState,
)
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from .conftest import make_state, setup_integration

LOCK = "lock.kitchen_child_lock"


@pytest.fixture
def platforms() -> list[Platform]:
    """Only the lock platform."""
    return [Platform.LOCK]


@pytest.mark.usefixtures("mock_client")
async def test_entities(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await setup_integration(hass, config_entry)
    await snapshot_platform(hass, entity_registry, snapshot, config_entry.entry_id)


async def test_lock_and_unlock(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    client = mock_client.return_value
    client.set_lock.return_value = make_state(dp={"1.2": {"PL": 1}})
    await hass.services.async_call(
        LOCK_DOMAIN, SERVICE_LOCK, {ATTR_ENTITY_ID: LOCK}, blocking=True
    )
    client.set_lock.assert_awaited_with("1.2", True)
    state = hass.states.get(LOCK)
    assert state is not None and state.state == LockState.LOCKED

    client.set_lock.return_value = make_state()
    await hass.services.async_call(
        LOCK_DOMAIN, SERVICE_UNLOCK, {ATTR_ENTITY_ID: LOCK}, blocking=True
    )
    client.set_lock.assert_awaited_with("1.2", False)
