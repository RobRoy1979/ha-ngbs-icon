"""Number entities."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.components.number import (
    ATTR_MAX,
    ATTR_MIN,
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

import pyngbsicon

from .conftest import make_state, setup_integration


@pytest.fixture
def platforms() -> list[Platform]:
    """Only the number platform."""
    return [Platform.NUMBER]


@pytest.mark.usefixtures("mock_client", "entity_registry_enabled_by_default")
async def test_entities(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await setup_integration(hass, config_entry)
    await snapshot_platform(hass, entity_registry, snapshot, config_entry.entry_id)


@pytest.mark.usefixtures("mock_client")
async def test_ranges(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    await setup_integration(hass, config_entry)
    # System defaults 20 / 26 / 17 / 30 °C, limit 10: clamped to 5-35 °C.
    expected = {
        "heating_setpoint": (10, 30),
        "cooling_setpoint": (16, 35),
        "eco_heating_setpoint": (7, 27),
        "eco_cooling_setpoint": (20, 35),
    }
    for key, (low, high) in expected.items():
        state = hass.states.get(f"number.kitchen_{key}")
        assert state is not None, key
        assert (state.attributes[ATTR_MIN], state.attributes[ATTR_MAX]) == (low, high)


async def test_range_without_limit(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.return_value.get_state.return_value = make_state(
        dp={"1.2": {"LIM": None}}
    )
    await setup_integration(hass, config_entry)
    state = hass.states.get("number.kitchen_heating_setpoint")
    assert state is not None
    assert (state.attributes[ATTR_MIN], state.attributes[ATTR_MAX]) == (5, 35)


@pytest.mark.parametrize(
    ("entity_id", "method", "args"),
    [
        (
            "number.kitchen_cooling_setpoint",
            "set_setpoint",
            ("1.2", pyngbsicon.SetpointKind.COOL, 24.5),
        ),
        (
            "number.kitchen_eco_heating_setpoint",
            "set_setpoint",
            ("1.2", pyngbsicon.SetpointKind.ECO_HEAT, 24.5),
        ),
    ],
)
async def test_set_setpoint(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    entity_id: str,
    method: str,
    args: tuple[object, ...],
) -> None:
    await setup_integration(hass, config_entry)
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: 24.5},
        blocking=True,
    )
    getattr(mock_client.return_value, method).assert_awaited_once_with(*args)


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize(
    ("entity_id", "field"),
    [
        ("number.kitchen_setpoint_limit", "LIM"),
        ("number.kitchen_b_loop_heating_offset", "DXH"),
        ("number.kitchen_b_loop_cooling_offset", "DXC"),
    ],
)
async def test_set_service_setting(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    entity_id: str,
    field: str,
) -> None:
    await setup_integration(hass, config_entry)
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: 2.5},
        blocking=True,
    )
    mock_client.return_value.set_thermostat.assert_awaited_once_with(
        "1.2", **{field: 2.5}
    )


async def test_out_of_range_is_refused(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: "number.kitchen_heating_setpoint", ATTR_VALUE: 31},
            blocking=True,
        )
    mock_client.return_value.set_setpoint.assert_not_called()
