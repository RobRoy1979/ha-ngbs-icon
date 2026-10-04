"""Polling: failures make the entities unavailable, a rejected SYSID starts reauth."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

import pyngbsicon

from .conftest import make_state, setup_integration

KITCHEN = "climate.kitchen"


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(timedelta(seconds=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_poll_interval_and_recovery(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_integration(hass, config_entry)
    client = mock_client.return_value
    assert client.get_state.await_count == 1
    client.get_state.assert_awaited_with(include_config=True)

    client.get_state.side_effect = pyngbsicon.IconConnectionError("down")
    await _tick(hass, freezer)
    assert client.get_state.await_count == 2
    # One failed poll is ridden out; the next attempt comes after 10 s.
    state = hass.states.get(KITCHEN)
    assert state is not None and state.state == "cool"
    freezer.tick(timedelta(seconds=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert client.get_state.await_count == 3
    state = hass.states.get(KITCHEN)
    assert state is not None and state.state == STATE_UNAVAILABLE
    await _tick(hass, freezer)  # still failing: the normal interval again
    assert client.get_state.await_count == 4

    client.get_state.side_effect = None
    client.get_state.return_value = make_state(dp={"1.2": {"TEMP": 21.5}})
    await _tick(hass, freezer)
    state = hass.states.get(KITCHEN)
    assert state is not None and state.attributes["current_temperature"] == 21.5


async def test_options_change_the_interval(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_integration(hass, config_entry)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 120}
    )
    await hass.async_block_till_done()  # the entry is reloaded
    client = mock_client.return_value
    calls = client.get_state.await_count
    await _tick(hass, freezer)
    assert client.get_state.await_count == calls
    freezer.tick(timedelta(seconds=90))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert client.get_state.await_count == calls + 1


@pytest.mark.parametrize("error", [pyngbsicon.IconAuthenticationError("no")])
async def test_rejected_sysid_starts_reauth(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
    error: Exception,
) -> None:
    await setup_integration(hass, config_entry)
    mock_client.return_value.get_state.side_effect = error
    await _tick(hass, freezer)
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_starting_controller_keeps_the_previous_state(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Placeholder values of a restarting controller do not reach the entities."""
    await setup_integration(hass, config_entry)
    starting = make_state(HC=0, INFO={"FIRMWARE": 1079}, dp={"1.2": {"TEMP": 5}})
    assert starting.starting
    mock_client.return_value.get_state.return_value = starting
    await _tick(hass, freezer)
    state = hass.states.get(KITCHEN)
    assert state is not None
    assert state.state == "cool"
    assert state.attributes["current_temperature"] == 23.4

    # A firmware that never reports the task list is not frozen for long.
    await _tick(hass, freezer)  # 30 s into the starting phase: still kept
    freezer.tick(timedelta(seconds=40))
    await _tick(hass, freezer)
    state = hass.states.get(KITCHEN)
    assert state is not None and state.attributes["current_temperature"] == 5

    # A normal answer ends the starting phase.
    mock_client.return_value.get_state.return_value = make_state()
    await _tick(hass, freezer)
    assert config_entry.runtime_data._starting_since is None


async def test_single_failure_is_not_logged_as_error(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await setup_integration(hass, config_entry)
    client = mock_client.return_value
    client.get_state.side_effect = pyngbsicon.IconProtocolError("empty answer")
    await _tick(hass, freezer)
    client.get_state.side_effect = None
    client.get_state.return_value = make_state(dp={"1.2": {"TEMP": 22.0}})
    freezer.tick(timedelta(seconds=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    state = hass.states.get(KITCHEN)
    assert state is not None and state.attributes["current_temperature"] == 22.0
    assert "Error fetching" not in caplog.text
    statistics = config_entry.runtime_data.statistics
    assert statistics.failures == 1

    # The interval is back to normal and a later single failure is tolerated again.
    client.get_state.side_effect = pyngbsicon.IconConnectionError("down")
    await _tick(hass, freezer)
    state = hass.states.get(KITCHEN)
    assert state is not None and state.state == "cool"
