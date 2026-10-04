"""Repair issues."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.ngbs_icon.const import DOMAIN

from .conftest import make_state, setup_integration


async def _poll(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, minutes: int
) -> None:
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_old_firmware(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    issue_registry: ir.IssueRegistry,
) -> None:
    raw_info = {"FIRMWARE": 1060, "UPTIME": 5, "TASK": []}
    mock_client.return_value.get_state.return_value = make_state(INFO=raw_info)
    await setup_integration(hass, config_entry)
    issue = issue_registry.async_get_issue(
        DOMAIN, f"old_firmware_{config_entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders == {
        "title": "NGBS iCON (Home)",
        "firmware": "1060",
        "required": "1079",
    }

    mock_client.return_value.get_state.return_value = make_state()
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert not issue_registry.async_get_issue(
        DOMAIN, f"old_firmware_{config_entry.entry_id}"
    )


async def test_thermostat_offline(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_integration(hass, config_entry)
    issue_id = f"thermostat_offline_{config_entry.entry_id}_1.2"
    mock_client.return_value.get_state.return_value = make_state(
        dp={"1.2": {"LIVE": 0}}
    )
    await _poll(hass, freezer, 1)
    assert not issue_registry.async_get_issue(DOMAIN, issue_id)  # not yet an hour

    await _poll(hass, freezer, 60)
    issue = issue_registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders == {
        "name": "Kitchen",
        "id": "1.2",
        "title": "NGBS iCON (Home)",
    }

    mock_client.return_value.get_state.return_value = make_state()
    await _poll(hass, freezer, 1)
    assert not issue_registry.async_get_issue(DOMAIN, issue_id)


async def test_hc_issue_removed_when_a_thermostat_becomes_master(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    issue_registry: ir.IssueRegistry,
) -> None:
    mock_client.return_value.get_state.return_value = make_state(
        cfg={"HCMASTER": "I1.4"}
    )
    await setup_integration(hass, config_entry)
    issue_id = f"hc_switch_external_{config_entry.entry_id}"
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="hc_switch_external",
    )
    mock_client.return_value.get_state.return_value = make_state()
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert not issue_registry.async_get_issue(DOMAIN, issue_id)


async def test_issues_removed_with_the_entry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    issue_registry: ir.IssueRegistry,
) -> None:
    mock_client.return_value.get_state.return_value = make_state(
        INFO={"FIRMWARE": 1060}
    )
    await setup_integration(hass, config_entry)
    ir.async_create_issue(
        hass,
        DOMAIN,
        "other_issue_of_another_entry",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="old_firmware",
    )
    assert await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    remaining = [
        issue_id for domain, issue_id in issue_registry.issues if domain == DOMAIN
    ]
    assert remaining == ["other_issue_of_another_entry"]
