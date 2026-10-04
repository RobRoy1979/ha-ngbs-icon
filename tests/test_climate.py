"""Climate entities."""

from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
)
from homeassistant.components.climate.const import (
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODE,
    ATTR_HVAC_MODES,
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ATTR_PRESET_MODE,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    STATE_UNAVAILABLE,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er, issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from custom_components.ngbs_icon.const import DOMAIN
import pyngbsicon

from .conftest import make_state, setup_integration

LIVING = "climate.living_room"  # the H/C master
KITCHEN = "climate.kitchen"


@pytest.fixture
def platforms() -> list[Platform]:
    """Only the climate platform."""
    return [Platform.CLIMATE]


@pytest.mark.usefixtures("mock_client")
async def test_entities(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await setup_integration(hass, config_entry)
    await snapshot_platform(hass, entity_registry, snapshot, config_entry.entry_id)


@pytest.mark.usefixtures("mock_client")
async def test_master_and_ranges(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    living = hass.states.get(LIVING)
    assert living is not None
    assert living.state == HVACMode.COOL
    assert living.attributes[ATTR_HVAC_MODES] == [HVACMode.HEAT, HVACMode.COOL]
    assert living.attributes[ATTR_PRESET_MODE] == "eco"
    assert living.attributes[ATTR_HVAC_ACTION] == HVACAction.IDLE
    # ECO cooling default 30 °C +/- LIM 10, within the absolute 5-35 °C.
    assert living.attributes[ATTR_MIN_TEMP] == 20
    assert living.attributes[ATTR_MAX_TEMP] == 35

    kitchen = hass.states.get(KITCHEN)
    assert kitchen is not None
    assert kitchen.attributes[ATTR_HVAC_MODES] == [HVACMode.COOL]
    assert hass.states.get("climate.kids_room") is None  # not configured


async def test_states_follow_the_controller(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.return_value.get_state.return_value = make_state(
        dp={"1.1": {"HC": 0, "CE": 0, "OUT": 1}, "1.2": {"OUT": 1, "LIM": None}}
    )
    await setup_integration(hass, config_entry)
    living = hass.states.get(LIVING)
    assert living is not None
    assert living.state == HVACMode.HEAT
    assert living.attributes[ATTR_PRESET_MODE] == "comfort"
    assert living.attributes[ATTR_HVAC_ACTION] == HVACAction.HEATING
    assert living.attributes[ATTR_MIN_TEMP] == 10  # heating default 20 ± 10
    assert living.attributes[ATTR_MAX_TEMP] == 30

    kitchen = hass.states.get(KITCHEN)
    assert kitchen is not None
    assert kitchen.attributes[ATTR_HVAC_ACTION] == HVACAction.COOLING
    assert kitchen.attributes[ATTR_MIN_TEMP] == 5  # no limit known: absolute range
    assert kitchen.attributes[ATTR_MAX_TEMP] == 35


async def test_unavailable_thermostat(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    state = make_state()
    gone = {k: v for k, v in state.thermostats.items() if k != "1.2"}
    mock_client.return_value.get_state.return_value = dataclasses.replace(
        state, thermostats=gone
    )
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    kitchen = hass.states.get(KITCHEN)
    assert kitchen is not None and kitchen.state == STATE_UNAVAILABLE
    assert kitchen.attributes[ATTR_HVAC_MODES] == [HVACMode.COOL]  # last known

    mock_client.return_value.get_state.return_value = state
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    kitchen = hass.states.get(KITCHEN)
    assert kitchen is not None and kitchen.state == HVACMode.COOL


async def test_set_temperature(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    client = mock_client.return_value
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: KITCHEN, ATTR_TEMPERATURE: 24.3},
        blocking=True,
    )
    client.set_setpoint.assert_awaited_once_with(
        "1.2", pyngbsicon.SetpointKind.ECO_COOL, 24.5
    )


async def test_set_temperature_with_mode(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    client = mock_client.return_value
    client.set_hc_mode.return_value = make_state(HC=0, dp={"1.1": {"HC": 0}})
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: LIVING, ATTR_HVAC_MODE: HVACMode.HEAT, ATTR_TEMPERATURE: 21},
        blocking=True,
    )
    client.set_hc_mode.assert_awaited_once_with(pyngbsicon.HeatCool.HEATING)
    # The setpoint of the new mode (the published state is heating, ECO).
    client.set_setpoint.assert_awaited_once_with(
        "1.1", pyngbsicon.SetpointKind.ECO_HEAT, 21.0
    )


async def test_set_preset(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    client = mock_client.return_value
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: KITCHEN, ATTR_PRESET_MODE: "comfort"},
        blocking=True,
    )
    client.set_eco.assert_awaited_once_with(False, "1.2")


async def test_set_hvac_mode(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    client = mock_client.return_value
    client.set_hc_mode.return_value = make_state(HC=0, dp={"1.1": {"HC": 0}})
    for mode in (
        HVACMode.COOL,
        HVACMode.HEAT,
    ):  # the first is the current mode: no write
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: LIVING, ATTR_HVAC_MODE: mode},
            blocking=True,
        )
    client.set_hc_mode.assert_awaited_once_with(pyngbsicon.HeatCool.HEATING)

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: LIVING, ATTR_HVAC_MODE: HVACMode.COOL},
        blocking=True,
    )
    client.set_hc_mode.assert_awaited_with(pyngbsicon.HeatCool.COOLING)


@pytest.mark.parametrize(
    ("hc_master", "master_name"),
    [("H1.1", "Living room"), ("H1.9", "1.9")],
)
async def test_hvac_mode_only_on_the_master(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    hc_master: str,
    master_name: str,
) -> None:
    mock_client.return_value.get_state.return_value = make_state(
        cfg={"HCMASTER": hc_master}
    )
    await setup_integration(hass, config_entry)
    # Home Assistant itself rejects a mode that is not offered...
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: KITCHEN, ATTR_HVAC_MODE: HVACMode.HEAT},
            blocking=True,
        )
    # ...but not when it comes with a temperature.
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {
                ATTR_ENTITY_ID: KITCHEN,
                ATTR_HVAC_MODE: HVACMode.HEAT,
                ATTR_TEMPERATURE: 21,
            },
            blocking=True,
        )
    assert err.value.translation_key == "hc_switch_not_allowed"
    assert err.value.translation_placeholders == {"master": master_name}
    mock_client.return_value.set_hc_mode.assert_not_called()
    mock_client.return_value.set_setpoint.assert_not_called()


@pytest.mark.parametrize(
    ("error", "exception", "key"),
    [
        (ValueError("bad"), ServiceValidationError, "invalid_value"),
        (
            pyngbsicon.IconRejectedError("1.2", "XAC", 4.0, 26.5),
            HomeAssistantError,
            "value_rejected",
        ),
        (pyngbsicon.IconConnectionError("down"), HomeAssistantError, "write_failed"),
        (pyngbsicon.IconAuthenticationError("no"), HomeAssistantError, "auth_failed"),
    ],
)
async def test_write_errors(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    error: Exception,
    exception: type[Exception],
    key: str,
) -> None:
    await setup_integration(hass, config_entry)
    mock_client.return_value.set_setpoint.side_effect = error
    with pytest.raises(exception) as err:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: KITCHEN, ATTR_TEMPERATURE: 25},
            blocking=True,
        )
    assert err.value.translation_key == key
    reauth = [
        f
        for f in hass.config_entries.flow.async_progress()
        if f["context"]["source"] == "reauth"
    ]
    assert bool(reauth) == (key == "auth_failed")


async def test_written_state_is_published(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    mock_client.return_value.set_setpoint.return_value = make_state(
        dp={"1.2": {"ECOC": 25}}
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: KITCHEN, ATTR_TEMPERATURE: 25},
        blocking=True,
    )
    kitchen = hass.states.get(KITCHEN)
    assert kitchen is not None
    assert kitchen.attributes[ATTR_TEMPERATURE] == 25


async def test_hvac_mode_with_external_changeover(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    issue_registry: ir.IssueRegistry,
) -> None:
    """With an input switching heating/cooling, a mode change explains why it fails."""
    mock_client.return_value.get_state.return_value = make_state(
        cfg={"HCMASTER": "I1.4"}
    )
    await setup_integration(hass, config_entry)
    living = hass.states.get(LIVING)
    assert living is not None
    assert living.attributes[ATTR_HVAC_MODES] == [HVACMode.COOL]
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {
                ATTR_ENTITY_ID: LIVING,
                ATTR_HVAC_MODE: HVACMode.HEAT,
                ATTR_TEMPERATURE: 21,
            },
            blocking=True,
        )
    assert err.value.translation_key == "hc_switch_external"
    issue = issue_registry.async_get_issue(
        DOMAIN, f"hc_switch_external_{config_entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders == {
        "title": "NGBS iCON (Home)",
        "source": "I1.4",
    }
    mock_client.return_value.set_hc_mode.assert_not_called()
