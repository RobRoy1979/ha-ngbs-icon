"""Sensor entities."""

from __future__ import annotations

import dataclasses
from typing import Any
from unittest.mock import MagicMock

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from .conftest import add_slave, make_state, setup_integration


@pytest.fixture
def platforms() -> list[Platform]:
    """Only the sensor platform."""
    return [Platform.SENSOR]


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
async def test_disabled_by_default(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    for entity_id in (
        "sensor.home_uptime",
        "sensor.home_supply_voltage",
        "sensor.home_default_heating_setpoint",
        "sensor.home_configuration_version",
    ):
        entry = entity_registry.async_get(entity_id)
        assert entry is not None, entity_id
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    # No outdoor sensor connected: the controller sends an error value, no fault.
    assert hass.states.get("sensor.home_outdoor_temperature") is None
    # A thermostat switches heating/cooling: the mode is a select, not a sensor.
    assert hass.states.get("sensor.home_system_mode") is None


async def test_outdoor_sensor_appears(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    mock_client.return_value.get_state.return_value = make_state(ETEMP=12.5)
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.home_outdoor_temperature")
    assert state is not None and state.state == "12.5"

    # A sensor fault keeps the entity, with an unknown value.
    mock_client.return_value.get_state.return_value = make_state(SIG=8)
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.home_outdoor_temperature")
    assert state is not None and state.state == STATE_UNKNOWN


async def test_system_mode_sensor_with_external_changeover(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.return_value.get_state.return_value = make_state(
        cfg={"HCMASTER": "I1.4"}
    )
    await setup_integration(hass, config_entry)
    state = hass.states.get("sensor.home_system_mode")
    assert state is not None
    assert state.state == "cooling"
    assert state.attributes["options"] == ["heating", "cooling"]


async def test_slave_controller(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.return_value.get_state.return_value = make_state(add_slave)
    await setup_integration(hass, config_entry)
    assert hass.states.get("sensor.home_2_mixing_valve") is not None
    assert hass.states.get("sensor.attic_temperature") is not None

    # The slave disappears from the answer: its entities become unavailable.
    state = make_state(add_slave)
    controllers = {1: state.controllers[1]}
    mock_client.return_value.get_state.return_value = dataclasses.replace(
        state, controllers=controllers
    )
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    valve = hass.states.get("sensor.home_2_mixing_valve")
    assert valve is not None and valve.state == STATE_UNAVAILABLE


async def test_offline_thermostat(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    mock_client.return_value.get_state.return_value = make_state(
        dp={"1.2": {"LIVE": 0}}
    )
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.kitchen_temperature")
    assert state is not None and state.state == STATE_UNAVAILABLE


async def test_controller_without_status(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    """Values the controller does not report get no entity."""

    def no_valve(raw: dict[str, Any]) -> None:
        del raw["CFG"]["ICON1"]["STATUS"]["AO"]

    mock_client.return_value.get_state.return_value = make_state(no_valve)
    await setup_integration(hass, config_entry)
    assert hass.states.get("sensor.home_mixing_valve") is None
    assert hass.states.get("sensor.home_water_temperature") is not None
