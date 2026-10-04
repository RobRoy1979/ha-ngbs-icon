"""The integration's actions."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ngbs_icon.const import DOMAIN
import pyngbsicon

from .conftest import make_state, setup_integration

KITCHEN = "climate.kitchen"


async def test_set_setpoints(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    await hass.services.async_call(
        DOMAIN,
        "set_setpoints",
        {
            ATTR_ENTITY_ID: [KITCHEN, "climate.office"],
            "heating": 21.3,
            "eco_cooling": 28,
        },
        blocking=True,
    )
    client = mock_client.return_value
    assert client.set_setpoints.await_count == 2
    client.set_setpoints.assert_any_await(
        "1.2", heat=21.5, cool=None, eco_heat=None, eco_cool=28.0
    )
    client.set_setpoints.assert_any_await(
        "1.5", heat=21.5, cool=None, eco_heat=None, eco_cool=28.0
    )


@pytest.mark.parametrize(
    ("data", "key"),
    [({}, "no_setpoint"), ({"heating": 31}, "setpoint_out_of_range")],
)
async def test_set_setpoints_invalid(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    data: dict[str, float],
    key: str,
) -> None:
    await setup_integration(hass, config_entry)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "set_setpoints", {ATTR_ENTITY_ID: KITCHEN, **data}, blocking=True
        )
    assert err.value.translation_key == key
    mock_client.return_value.set_setpoints.assert_not_called()


async def test_set_system_mode(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    # The only system is used when none is given.
    await hass.services.async_call(
        DOMAIN, "set_system_mode", {"mode": "heating"}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN,
        "set_system_mode",
        {"mode": "cooling", "config_entry_id": config_entry.entry_id},
        blocking=True,
    )
    client = mock_client.return_value
    assert [call.args for call in client.set_hc_mode.await_args_list] == [
        (pyngbsicon.HeatCool.HEATING,),
        (pyngbsicon.HeatCool.COOLING,),
    ]


async def test_set_system_mode_external(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    issue_registry: ir.IssueRegistry,
) -> None:
    mock_client.return_value.get_state.return_value = make_state(
        cfg={"HCMASTER": "I1.4"}
    )
    await setup_integration(hass, config_entry)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "set_system_mode", {"mode": "heating"}, blocking=True
        )
    assert err.value.translation_key == "hc_switch_external"
    assert issue_registry.async_get_issue(
        DOMAIN, f"hc_switch_external_{config_entry.entry_id}"
    )
    mock_client.return_value.set_hc_mode.assert_not_called()


async def test_restart_controller(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    await hass.services.async_call(DOMAIN, "restart_controller", {}, blocking=True)
    mock_client.return_value.restart.assert_awaited_once()

    mock_client.return_value.restart.side_effect = pyngbsicon.IconConnectionError("x")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "restart_controller", {}, blocking=True)


@pytest.mark.usefixtures("mock_client")
async def test_unknown_or_unloaded_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "restart_controller", {"config_entry_id": "nope"}, blocking=True
        )
    await hass.config_entries.async_unload(config_entry.entry_id)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "restart_controller",
            {"config_entry_id": config_entry.entry_id},
            blocking=True,
        )
