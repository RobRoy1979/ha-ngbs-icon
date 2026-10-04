"""Setting up, unloading and migrating config entries."""

from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock, patch

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_IP_ADDRESS, CONF_MAC, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ngbs_icon.const import CONF_SYSID, DOMAIN
import pyngbsicon

from .conftest import HOST, MAC, SYSID, add_slave, make_state, setup_integration


@pytest.mark.usefixtures("mock_client")
async def test_setup_and_unload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    controller = device_registry.async_get_device_by_identifier(
        (DOMAIN, SYSID), config_entry.entry_id
    )
    assert controller is not None
    assert controller.name == "Home"
    assert controller.serial_number == SYSID
    assert controller.sw_version == "1079"
    assert controller.connections == {(dr.CONNECTION_NETWORK_MAC, MAC)}
    assert controller.configuration_url == f"http://{HOST}/"

    room = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{SYSID}-1.1"), config_entry.entry_id
    )
    assert room is not None
    assert room.name == "Living room"
    assert room.via_device_id == controller.id
    # Only configured thermostats get a device.
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, f"{SYSID}-1.6"), config_entry.entry_id
        )
        is None
    )

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_slave_controllers_get_devices(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    state = make_state()
    slave = dataclasses.replace(state.controllers[1], address=2, is_master=False)
    state = dataclasses.replace(state, controllers={1: state.controllers[1], 2: slave})
    mock_client.return_value.get_state.return_value = state
    await setup_integration(hass, config_entry)

    master = device_registry.async_get_device_by_identifier(
        (DOMAIN, SYSID), config_entry.entry_id
    )
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{SYSID}-controller-2"), config_entry.entry_id
    )
    assert master is not None and device is not None
    assert device.name == "Home 2"
    assert device.via_device_id == master.id


async def test_mac_is_stored(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    hass_entry_data = {**config_entry.data, CONF_MAC: None}
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=SYSID, data=hass_entry_data, version=2, options={}
    )
    await setup_integration(hass, entry)
    assert entry.data[CONF_MAC] == MAC


@pytest.mark.parametrize(
    ("error", "state"),
    [
        (pyngbsicon.IconConnectionError("down"), ConfigEntryState.SETUP_RETRY),
        (pyngbsicon.IconProtocolError("garbage"), ConfigEntryState.SETUP_RETRY),
        (pyngbsicon.IconAuthenticationError("no"), ConfigEntryState.SETUP_ERROR),
    ],
)
async def test_setup_failures(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    error: Exception,
    state: ConfigEntryState,
) -> None:
    mock_client.return_value.get_state.side_effect = error
    await setup_integration(hass, config_entry)
    assert config_entry.state is state
    reauth = [
        f
        for f in hass.config_entries.flow.async_progress()
        if f["context"]["source"] == SOURCE_REAUTH
    ]
    assert bool(reauth) == (state is ConfigEntryState.SETUP_ERROR)


@pytest.mark.usefixtures("mock_client")
async def test_setup_without_sysid_starts_reauth(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"host:{HOST}",
        data={CONF_HOST: HOST, CONF_SYSID: "", CONF_MAC: None},
        version=2,
    )
    await setup_integration(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


def _v1_entry(
    data: dict[str, object], *, title: str = HOST, unique_id: str | None = None
) -> MockConfigEntry:
    """An entry as the earlier integration of the same domain created it."""
    return MockConfigEntry(
        domain=DOMAIN, title=title, unique_id=unique_id, data=data, version=1
    )


# The shape found on a real installation, and the shape of later versions.
V1_HOST_PORT = {CONF_HOST: HOST, "port": 502, "scan_interval": 10, "slave": 1}
V1_WITH_ID = {CONF_IP_ADDRESS: HOST, "id": SYSID, "scan_interval": 60, "inventory": {}}


async def test_migrate_v1(
    hass: HomeAssistant,
    mock_client: MagicMock,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    entry = _v1_entry(V1_HOST_PORT)
    entry.add_to_hass(hass)
    old_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "old-room")}
    )
    old_entity = entity_registry.async_get_or_create(
        "climate",
        DOMAIN,
        "old_room_climate",
        config_entry=entry,
        device_id=old_device.id,
    )

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == 2
    assert entry.minor_version == 1
    assert entry.unique_id == SYSID
    assert entry.title == "NGBS iCON (Home)"
    assert entry.data == {CONF_HOST: HOST, CONF_SYSID: SYSID, CONF_MAC: MAC}
    assert entry.options == {CONF_SCAN_INTERVAL: 10}
    assert entity_registry.async_get(old_entity.entity_id) is None
    assert device_registry.async_get(old_device.id) is None
    mock_client.assert_any_call(HOST, None)  # the SYSID was discovered
    assert len(hass.states.async_entity_ids("climate")) == 5


async def test_migrate_v1_with_stored_sysid(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    entry = _v1_entry(V1_WITH_ID, title="Upstairs", unique_id=SYSID)
    await setup_integration(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.title == "Upstairs"  # chosen by the user: kept
    assert entry.options == {CONF_SCAN_INTERVAL: 60}
    mock_client.assert_any_call(HOST, SYSID)


@pytest.mark.parametrize(
    ("interval", "expected"), [(3, 10), (900, 300), ("bogus", 30), (None, 30)]
)
@pytest.mark.usefixtures("mock_client")
async def test_migrate_v1_interval(
    hass: HomeAssistant, interval: object, expected: int
) -> None:
    entry = _v1_entry({**V1_HOST_PORT, "scan_interval": interval})
    await setup_integration(hass, entry)
    assert entry.options == {CONF_SCAN_INTERVAL: expected}


async def test_migrate_v1_without_reachable_controller(
    hass: HomeAssistant, mock_client: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    mock_client.return_value.get_state.side_effect = pyngbsicon.IconConnectionError(
        "down"
    )
    entry = _v1_entry(V1_HOST_PORT)
    await setup_integration(hass, entry)
    assert entry.version == 2
    assert entry.unique_id is None
    assert entry.title == "NGBS iCON"
    assert entry.data == {CONF_HOST: HOST, CONF_SYSID: "", CONF_MAC: None}
    assert entry.state is ConfigEntryState.SETUP_ERROR  # reauth asks for the SYSID
    assert "Could not read the NGBS iCON system" in caplog.text


async def test_migrate_v1_unreachable_keeps_stored_sysid(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    mock_client.return_value.get_state.side_effect = pyngbsicon.IconConnectionError(
        "down"
    )
    entry = _v1_entry(V1_WITH_ID, title="NGBS iCON")
    await setup_integration(hass, entry)
    assert entry.unique_id == SYSID
    assert entry.data[CONF_SYSID] == SYSID
    assert entry.title == "NGBS iCON"
    assert entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.usefixtures("mock_client")
async def test_migrate_v1_when_the_system_is_set_up_twice(
    hass: HomeAssistant, config_entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
) -> None:
    config_entry.add_to_hass(hass)
    entry = _v1_entry(V1_HOST_PORT)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.version == 2
    assert entry.unique_id is None  # the new entry keeps the SYSID
    assert "is also set up as NGBS iCON (Home)" in caplog.text
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"duplicate_system_{entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders == {
        "title": "NGBS iCON (Home)",
        "other": "NGBS iCON (Home)",
    }


@pytest.mark.usefixtures("mock_client")
async def test_migrate_v1_without_host(hass: HomeAssistant) -> None:
    entry = _v1_entry({"scan_interval": 30}, title="NGBS iCON")
    await setup_integration(hass, entry)
    assert entry.version == 2
    assert entry.data == {CONF_HOST: "", CONF_SYSID: "", CONF_MAC: None}


@pytest.mark.usefixtures("mock_client")
async def test_migrate_from_the_future_fails(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={}, version=3)
    await setup_integration(hass, entry)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR


@pytest.mark.usefixtures("mock_client")
async def test_current_version_is_not_changed(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """An older minor version of the current major version needs no migration."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SYSID,
        data=dict(config_entry.data),
        options=dict(config_entry.options),
        version=2,
        minor_version=0,
    )
    await setup_integration(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data == config_entry.data


async def test_new_thermostat_gets_entities(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """A thermostat installed while Home Assistant runs appears at the next poll."""
    await setup_integration(hass, config_entry)
    assert hass.states.get("climate.kids_room") is None
    mock_client.return_value.get_state.return_value = make_state(
        dp={"1.6": {"ON": 1, "LIVE": 1, "TEMP": 21.0}}
    )
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("climate.kids_room") is not None
    assert hass.states.get("sensor.kids_room_temperature") is not None
    assert hass.states.get("binary_sensor.home_valve_6_kids_room") is not None
    assert device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{SYSID}-1.6"), config_entry.entry_id
    )


async def test_new_slave_controller_gets_a_device(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    mock_client.return_value.get_state.return_value = make_state(add_slave)
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    master = device_registry.async_get_device_by_identifier(
        (DOMAIN, SYSID), config_entry.entry_id
    )
    slave = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{SYSID}-controller-2"), config_entry.entry_id
    )
    attic = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{SYSID}-2.1"), config_entry.entry_id
    )
    assert master and slave and attic
    assert attic.via_device_id == slave.id
    assert slave.via_device_id == master.id
    assert hass.states.get("climate.attic") is not None


async def test_uninstalled_thermostat_is_removed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    identifier = (DOMAIN, f"{SYSID}-1.5")
    assert device_registry.async_get_device_by_identifier(
        identifier, config_entry.entry_id
    )

    # Missing from the answer (e.g. its controller does not respond): kept.
    state = make_state()
    gone = {k: v for k, v in state.thermostats.items() if k != "1.5"}
    mock_client.return_value.get_state.return_value = dataclasses.replace(
        state, thermostats=gone
    )
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert device_registry.async_get_device_by_identifier(
        identifier, config_entry.entry_id
    )

    # Uninstalled in the controller configuration: removed, the entry reloads.
    mock_client.return_value.get_state.return_value = make_state(dp={"1.5": {"ON": 0}})
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert not device_registry.async_get_device_by_identifier(
        identifier, config_entry.entry_id
    )
    assert entity_registry.async_get("climate.office") is None
    assert config_entry.state is ConfigEntryState.LOADED


async def test_remove_device_manually(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    assert await async_setup_component(hass, "config", {})
    await setup_integration(hass, config_entry)
    old = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={(DOMAIN, f"{SYSID}-3.1")}
    )
    current = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{SYSID}-1.1"), config_entry.entry_id
    )
    assert current is not None
    module = hass.data["integrations"][DOMAIN].get_component()
    assert await module.async_remove_config_entry_device(hass, config_entry, old)
    assert not await module.async_remove_config_entry_device(
        hass, config_entry, current
    )


async def test_slave_firmware_from_discovery(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Slaves report their firmware only in the SYSID discovery answer."""
    client = mock_client.return_value
    client.get_state.return_value = make_state(add_slave)
    client.discover_sysid.return_value = pyngbsicon.SysidInfo(
        sysid=SYSID, firmware={1: 1079, 2: 1078}, download=0
    )
    await setup_integration(hass, config_entry)
    slave = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{SYSID}-controller-2"), config_entry.entry_id
    )
    assert slave is not None and slave.sw_version == "1078"


async def test_firmware_unknown_on_old_controllers(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    client = mock_client.return_value
    client.get_state.return_value = make_state(add_slave)
    client.discover_sysid.side_effect = pyngbsicon.IconUnsupportedError("old")
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    slave = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{SYSID}-controller-2"), config_entry.entry_id
    )
    assert slave is not None and slave.sw_version is None


async def test_renamed_thermostat_reloads(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Device and relay names follow a room renamed in the controller."""
    await setup_integration(hass, config_entry)
    renamed = make_state(dp={"1.2": {"NAME": "Pantry"}})
    mock_client.return_value.get_state.return_value = renamed
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{SYSID}-1.2"), config_entry.entry_id
    )
    assert device is not None and device.name == "Pantry"
    valve = hass.states.get("binary_sensor.home_valve_2_kitchen")
    assert valve is not None and valve.name == "Home Valve 2 (Pantry)"

    # A thermostat installed later is not a rename.
    mock_client.return_value.get_state.return_value = make_state(
        dp={"1.2": {"NAME": "Pantry"}, "1.6": {"ON": 1, "LIVE": 1}}
    )
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        await config_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
    reload.assert_not_called()
