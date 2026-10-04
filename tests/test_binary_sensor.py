"""Binary sensor entities."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
)
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
    """Only the binary sensor platform."""
    return [Platform.BINARY_SENSOR]


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
async def test_relays(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    await setup_integration(hass, config_entry)
    relays = sorted(
        state.name
        for state in hass.states.async_all("binary_sensor")
        if "relay" in state.entity_id or "valve" in state.entity_id
    )
    # The valves of the thermostats that are not installed (1.6, 1.7) are left out.
    assert relays == [
        "Home Cooling relay",
        "Home Heating relay",
        "Home Pump relay",
        "Home Valve 1 (Living room)",
        "Home Valve 2 (Kitchen)",
        "Home Valve 3 (Bedroom)",
        "Home Valve 4 (Bathroom)",
        "Home Valve 5 (Office)",
    ]
    cooling = hass.states.get("binary_sensor.home_cooling_relay")
    assert cooling is not None and cooling.state == STATE_ON


def _custom_relays(raw: dict[str, Any]) -> None:
    relays = raw["CFG"]["ICON1"]["RELAY"]
    relays["R6"]["FUNC"] = "Bathroom towel"  # renamed by the installer
    relays["R7"]["FUNC"] = "S1.8"  # switched output
    relays["R5"]["OR"] = ["A1.4", "A1.5"]  # one valve for two rooms
    relays["R4"]["OR"] = ["I1.2"]  # a valve switched by an input
    del raw["CFG"]["ICON1"]["STATUS"]["R6"]  # state not reported


async def test_relay_names(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.return_value.get_state.return_value = make_state(_custom_relays)
    await setup_integration(hass, config_entry)
    names = {
        state.entity_id: state.name
        for state in hass.states.async_all("binary_sensor")
        if state.entity_id.startswith("binary_sensor.home_")
    }
    assert names["binary_sensor.home_bathroom_towel"] == "Home Bathroom towel"
    assert (
        names["binary_sensor.home_switched_output_relay"]
        == "Home Switched output relay"
    )
    assert names["binary_sensor.home_valve_5"] == "Home Valve 5"
    assert names["binary_sensor.home_valve_4"] == "Home Valve 4"
    towel = hass.states.get("binary_sensor.home_bathroom_towel")
    assert towel is not None and towel.state == STATE_UNKNOWN


async def test_slave_relays(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.return_value.get_state.return_value = make_state(add_slave)
    await setup_integration(hass, config_entry)
    assert hass.states.get("binary_sensor.home_2_valve_1_attic") is not None
    assert hass.states.get("binary_sensor.home_2_valve_2") is None  # not installed

    # The relay disappears from the configuration.
    def remove_relay(raw: dict[str, Any]) -> None:
        add_slave(raw)
        del raw["CFG"]["ICON2"]["RELAY"]["R1"]

    mock_client.return_value.get_state.return_value = make_state(remove_relay)
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get("binary_sensor.home_2_valve_1_attic")
    assert state is not None and state.state == STATE_UNKNOWN


async def test_connected_stays_available(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    mock_client.return_value.get_state.return_value = make_state(
        dp={"1.2": {"LIVE": 0}}
    )
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    connected = hass.states.get("binary_sensor.kitchen_connected")
    assert connected is not None and connected.state == STATE_OFF
    output = hass.states.get("binary_sensor.kitchen_output_active")
    assert output is not None and output.state == STATE_UNAVAILABLE
